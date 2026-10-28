"""Flask UI + API for the Viagogo listing automation system (v1.2.2).

Listing-only + Opportunity Scanner (heuristic scoring, NO ML).
DRY_RUN=True by default — bulk creation stores listings as `draft` and
the bot simulates posting (fake DRY-xxxx ids). Nothing touches
Viagogo unless LIVE_MODE=True + DRY_RUN=False + a saved session exists
+ LIVE_CONFIRM=yes. Market scans are mock/sample by default; a live
scrape needs SCAN_LIVE=True.

NopeCHA CAPTCHA solving (v1.2.2) is OPTIONAL and OFF by default: the
bot stops on a challenge unless the operator enables it in Settings
and pastes their own NopeCHA API key (or sets NOPECHA_API_KEY). The
key is stored in the SQLite config, shown back only masked, and never
logged. See captcha.py for the honest limits.

Run:  python app.py   -> http://127.0.0.1:5002
See DELIVERY.md for Windows / Linux / Docker setup.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import db as store
from captcha import NopechaSolver, mask_key, solver_from_config
from discord_notify import is_valid_webhook_url, notify_opportunity, notify_sale, send_test
from market import MarketMonitor
from pricing import compute_listing_price, validate_rules
from scoring import crosses_threshold, rank_opportunities, score_opportunity
from viagogo_bot import ViagogoBot

load_dotenv()
BASE = Path(__file__).resolve().parent
VERSION = "1.2.2"
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE / "data" / "listings.db"))
LOG_DIR = BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- structured logging: console + logs/app.log (never log secrets) -------
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")],
)
logger = logging.getLogger("viagogo-listing-automation")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def dry_run() -> bool:
    return os.environ.get("DRY_RUN", "True").lower() != "false"


def live_mode() -> bool:
    return os.environ.get("LIVE_MODE", "False").lower() == "true"


def session_file() -> str:
    return os.environ.get("VIAGOGO_SESSION_FILE", "auth_state.json")


def check_live_config() -> list[str]:
    """Startup guard: refuse a live run unless every live requirement holds.

    Returns a list of blocking problems (empty = OK to start in live mode).
    Dry-run always passes.
    """
    if not live_mode() or dry_run():
        return []
    problems = []
    if not Path(session_file()).exists():
        problems.append(f"Saved session not found: {session_file()} — log in once and save it (see DELIVERY.md)")
    if os.environ.get("LIVE_CONFIRM", "").lower() != "yes":
        problems.append("LIVE_CONFIRM=yes is required — set it only after the client accepted the speculative-listing risk in writing")
    return problems


# --- validation helpers ----------------------------------------------------
CATEGORIES = {"football", "concert", "sport", "theatre", "other"}


def _bad(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _valid_url(value) -> bool:
    if value is None or value == "":
        return True
    try:
        parsed = urlparse(str(value))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _validate_listing_payload(data: dict) -> list[str]:
    """Validate a single-listing / bulk payload. Returns error strings."""
    errors: list[str] = []
    name = data.get("event_name")
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        errors.append("event_name is required (1-200 characters)")
    if not _valid_url(data.get("event_url")):
        errors.append("event_url must be a valid http(s) URL")
    if data.get("category") and data["category"] not in CATEGORIES:
        errors.append(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    section = data.get("section", "General Admission")
    if not isinstance(section, str) or not section.strip() or len(section) > 100:
        errors.append("section must be 1-100 characters")
    try:
        qty = int(data.get("quantity", data.get("quantity_per_listing", 2)))
        if not 1 <= qty <= 10:
            errors.append("quantity must be 1-10")
    except (TypeError, ValueError):
        errors.append("quantity must be an integer 1-10")
    try:
        face = float(data["face_price"])
        if not 0 < face <= 10000:
            errors.append("face_price must be > 0 and <= 10000")
    except (KeyError, TypeError, ValueError):
        errors.append("face_price is required and must be a number > 0")
    return errors


def _conn():
    return store.connect(DB_PATH)


def _config() -> dict:
    with _conn() as conn:
        cfg = store.get_config(conn, "price_rules") or {}
    cfg.setdefault("markup_pct", 80)
    cfg.setdefault("min_price", 50)
    cfg.setdefault("max_price", 500)
    cfg.setdefault("round_to", 0.99)
    cfg.setdefault("currency", "GBP")
    return cfg


def _webhook() -> str:
    with _conn() as conn:
        saved = store.get_config(conn, "discord_webhook_url") or ""
    return saved or os.environ.get("DISCORD_WEBHOOK_URL", "")


# --- NopeCHA CAPTCHA solver (v1.2.2, optional, OFF by default) -----------
def _captcha_config() -> dict:
    """Effective NopeCHA config: key from env first, then the dashboard
    (SQLite config); toggle from env override, else the dashboard.
    The full key is NEVER returned — only the masked form."""
    with _conn() as conn:
        db_enabled = store.get_config(conn, "nopecha_enabled")
        db_key = store.get_config(conn, "nopecha_api_key") or ""
    env_key = (os.environ.get("NOPECHA_API_KEY") or "").strip()
    key = env_key or str(db_key).strip()
    source = "env" if env_key else ("dashboard" if key else "none")
    env_toggle = os.environ.get("NOPECHA_ENABLED")
    if env_toggle is not None:
        enabled = env_toggle.strip().lower() in {"true", "1", "yes", "on"}
    else:
        enabled = bool(db_enabled)
    return {"enabled": enabled, "configured": bool(key),
            "api_key_masked": mask_key(key), "source": source}


def _captcha_solver() -> NopechaSolver:
    """Solver built from the effective config (env key first, then DB)."""
    with _conn() as conn:
        db_enabled = store.get_config(conn, "nopecha_enabled")
        db_key = store.get_config(conn, "nopecha_api_key") or ""
    return solver_from_config(db_enabled, db_key)


def _bot() -> ViagogoBot:
    """Listing bot wired with the dashboard NopeCHA solver (inert when
    no key is configured — challenge pages still stop the bot)."""
    return ViagogoBot(dry_run=dry_run(), mock_url=os.environ.get("MOCK_PORTAL_URL") or None,
                      captcha_solver=_captcha_solver())


# --- Opportunity Scanner helpers -------------------------------------------
def _scanner_thresholds() -> dict:
    with _conn() as conn:
        saved = store.get_config(conn, "scanner_thresholds") or {}
    return {"min_profit": float(saved.get("min_profit", 50.0)),
            "min_confidence": int(saved.get("min_confidence", 50))}


def _score_all(conn) -> list[dict]:
    """Score the latest snapshot of every watched event (heuristic only)."""
    watch = {w["event_url"]: w for w in store.list_watchlist(conn)}
    snapshots = store.latest_snapshots(conn)
    rules = _config()
    scored: list[dict] = []
    for snap in snapshots:
        entry = watch.get(snap.get("event_url") or "")
        buy_cost = entry.get("face_price") if entry else None
        qty = int(entry.get("quantity", 2)) if entry else 2
        scored.append(score_opportunity(snap, buy_cost=buy_cost, quantity=qty,
                                        rules=rules))
    return rank_opportunities(scored)


# --- error handlers (always JSON, never a stack trace to the client) -------
@app.errorhandler(404)
def _handle_404(exc):
    return jsonify({"ok": False, "error": "not found"}), 404


@app.errorhandler(405)
def _handle_405(exc):
    return jsonify({"ok": False, "error": "method not allowed"}), 405


@app.errorhandler(400)
def _handle_400(exc):
    return jsonify({"ok": False, "error": "bad request"}), 400


@app.errorhandler(500)
def _handle_500(exc):
    logger.exception("Unhandled error")
    return jsonify({"ok": False, "error": "internal server error"}), 500


@app.before_request
def _log_request():
    logger.info("%s %s", request.method, request.path)


# --- routes ----------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"ok": True, "status": "healthy", "version": VERSION,
                    "dry_run": dry_run(), "live_mode": live_mode()})


@app.route("/")
def index():
    return render_template("index.html", dry_run=dry_run(),
                           live=os.environ.get("LIVE_MODE", "False"))


@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "GET":
        return jsonify({"price_rules": _config(), "discord_webhook_url": _webhook(),
                        "dry_run": dry_run(), "live_mode": live_mode()})
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    rules = data.get("price_rules", {})
    if not isinstance(rules, dict):
        return _bad("price_rules must be an object")
    errors = validate_rules(rules)
    if "currency" in rules and not (isinstance(rules["currency"], str) and len(rules["currency"]) == 3):
        errors.append("currency must be a 3-letter code, e.g. GBP")
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    if "discord_webhook_url" in data and data["discord_webhook_url"]:
        if not is_valid_webhook_url(data["discord_webhook_url"]):
            return _bad("discord_webhook_url must be a https://discord.com/api/webhooks/... URL")
    with _conn() as conn:
        store.set_config(conn, "price_rules", rules)
        if "discord_webhook_url" in data:
            store.set_config(conn, "discord_webhook_url", data["discord_webhook_url"])
    logger.info("Config updated")
    return jsonify({"ok": True, "price_rules": _config()})


@app.route("/api/listings", methods=["GET", "POST"])
def listings():
    if request.method == "GET":
        status = request.args.get("status") or None
        if status and status not in {"draft", "active", "paused", "sold", "failed", "deleted"}:
            return _bad("invalid status filter")
        with _conn() as conn:
            return jsonify(store.list_listings(conn, status))
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    errors = _validate_listing_payload(data)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    rules = _config()
    try:
        price = compute_listing_price(float(data["face_price"]), rules)
    except ValueError as exc:
        return _bad(str(exc))
    row = {"event_name": data["event_name"].strip(), "event_url": data.get("event_url"),
           "category": data.get("category", "football"),
           "section": data.get("section", "General Admission"),
           "quantity": int(data.get("quantity", 2)),
           "face_price": float(data["face_price"]), "listing_price": price,
           "currency": rules.get("currency", "GBP"), "status": "draft"}
    with _conn() as conn:
        row["id"] = store.create_listing(conn, row)
    logger.info("Listing %s created (draft) for %s", row["id"], row["event_name"])
    return jsonify({"ok": True, "listing": row}), 201


@app.route("/api/bulk", methods=["POST"])
def bulk():
    """Create N listings for ONE event (volume control).
    Body: {event_name, event_url, category, section, face_price,
           listings_per_event, quantity_per_listing}"""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    errors = _validate_listing_payload(data)
    try:
        n = int(data.get("listings_per_event", 1))
        if not 1 <= n <= 50:
            errors.append("listings_per_event must be 1-50")
    except (TypeError, ValueError):
        errors.append("listings_per_event must be an integer 1-50")
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    rules = _config()
    try:
        price = compute_listing_price(float(data["face_price"]), rules)
    except ValueError as exc:
        return _bad(str(exc))
    created = []
    with _conn() as conn:
        for _ in range(n):
            row = {"event_name": data["event_name"].strip(), "event_url": data.get("event_url"),
                   "category": data.get("category", "football"),
                   "section": data.get("section", "General Admission"),
                   "quantity": int(data.get("quantity_per_listing", 2)),
                   "face_price": float(data["face_price"]), "listing_price": price,
                   "currency": rules.get("currency", "GBP"), "status": "draft"}
            row["id"] = store.create_listing(conn, row)
            created.append(row)
    logger.info("Bulk created %d drafts for %s @ %s", len(created), data["event_name"], price)
    return jsonify({"ok": True, "created": len(created), "listing_price": price,
                    "listings": created}), 201


@app.route("/api/listings/<int:listing_id>/post", methods=["POST"])
def post_listing(listing_id):
    """Post one draft via the bot (simulated in dry-run)."""
    with _conn() as conn:
        row = store.get_listing(conn, listing_id)
    if not row:
        return jsonify({"ok": False, "error": "not found"}), 404
    bot = _bot()
    try:
        result = bot.create_listing(row)
    except Exception as exc:  # bot failures must not crash the API
        logger.exception("Bot create_listing failed for listing %s", listing_id)
        with _conn() as conn:
            store.update_listing(conn, listing_id, status="failed", last_error=str(exc))
        return jsonify({"ok": False, "error": str(exc)}), 502
    with _conn() as conn:
        store.update_listing(conn, listing_id, status="active" if result.get("ok") else "failed",
                             viagogo_listing_id=result.get("viagogo_listing_id"),
                             last_error=None if result.get("ok") else str(result))
    logger.info("Listing %s post result ok=%s id=%s", listing_id, result.get("ok"),
                result.get("viagogo_listing_id"))
    return jsonify({"ok": result.get("ok", False), "bot": result, "log": bot.log})


@app.route("/api/listings/<int:listing_id>/<action>", methods=["POST"])
def listing_action(listing_id, action):
    mapping = {"pause": "paused", "resume": "active", "delete": "deleted", "relist": "active"}
    if action not in mapping:
        return jsonify({"ok": False, "error": "unknown action"}), 400
    with _conn() as conn:
        row = store.get_listing(conn, listing_id)
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        if row.get("viagogo_listing_id"):
            bot = _bot()
            try:
                bot.set_listing_status(row["viagogo_listing_id"], "pause" if action == "pause"
                                       else "resume" if action == "resume"
                                       else "delete" if action == "delete" else "relist")
            except Exception:
                logger.exception("Bot set_listing_status failed for listing %s", listing_id)
        store.update_listing(conn, listing_id, status=mapping[action])
    return jsonify({"ok": True, "status": mapping[action]})


@app.route("/api/listings/<int:listing_id>/reprice", methods=["POST"])
def reprice(listing_id):
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    rules = _config()
    try:
        if "face_price" in data:
            face = float(data["face_price"])
            if not 0 < face <= 10000:
                return _bad("face_price must be > 0 and <= 10000")
            price = compute_listing_price(face, rules)
        elif "listing_price" in data:
            price = float(data["listing_price"])
            if not 0 < price <= 10000:
                return _bad("listing_price must be > 0 and <= 10000")
        else:
            return _bad("send face_price or listing_price")
    except (TypeError, ValueError):
        return _bad("price must be a number")
    with _conn() as conn:
        row = store.get_listing(conn, listing_id)
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        if row.get("viagogo_listing_id"):
            try:
                _bot().update_price(row["viagogo_listing_id"], price)
            except Exception:
                logger.exception("Bot update_price failed for listing %s", listing_id)
        store.update_listing(conn, listing_id, listing_price=price)
    return jsonify({"ok": True, "listing_price": price})


@app.route("/api/discord/test", methods=["POST"])
def discord_test():
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return _bad("JSON body required")
    url = data.get("webhook_url") or _webhook()
    if url and not is_valid_webhook_url(url):
        return _bad("webhook_url must be a https://discord.com/api/webhooks/... URL")
    if data.get("webhook_url"):
        with _conn() as conn:
            store.set_config(conn, "discord_webhook_url", url)
    return jsonify(send_test(url, dry_run=dry_run()))


@app.route("/api/sales/check", methods=["POST"])
def check_sales():
    """Poll the seller dashboard; on a new sale, record it + notify Discord.
    In dry-run this returns no sales — use /api/sales/simulate to test the
    Discord path end-to-end without Viagogo. NOTE: live sale detection is
    still a stub until the live sales-page selectors are verified."""
    bot = _bot()
    sales = bot.check_sales()
    notified = 0
    with _conn() as conn:
        for s in sales:
            store.record_sale(conn, s["listing_id"], s["sale_price"])
            store.update_listing(conn, s["listing_id"], status="sold")
            row = store.get_listing(conn, s["listing_id"])
            if row and notify_sale(_webhook(), row, s["sale_price"], dry_run=dry_run()).get("sent"):
                notified += 1
    return jsonify({"ok": True, "sales_found": len(sales), "discord_notified": notified,
                    "note": "live sale detection is a stub until selector verification"})


@app.route("/api/sales/simulate", methods=["POST"])
def simulate_sale():
    """Test-only: mark a listing sold and fire the Discord notification
    (dry-run payload if no webhook / in dry-run)."""
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict) or "listing_id" not in data:
        return _bad("listing_id is required")
    try:
        listing_id = int(data["listing_id"])
    except (TypeError, ValueError):
        return _bad("listing_id must be an integer")
    with _conn() as conn:
        row = store.get_listing(conn, listing_id)
        if not row:
            return jsonify({"ok": False, "error": "not found"}), 404
        store.record_sale(conn, row["id"], row["listing_price"])
        store.update_listing(conn, row["id"], status="sold")
    result = notify_sale(_webhook(), row, row["listing_price"], dry_run=dry_run())
    return jsonify({"ok": True, "discord": result})


@app.route("/opportunities")
def opportunities_page():
    return render_template("opportunities.html", dry_run=dry_run(),
                           live=os.environ.get("LIVE_MODE", "False"))


@app.route("/api/opportunities")
def opportunities():
    """Ranked opportunities from the latest snapshots (heuristic scoring)."""
    with _conn() as conn:
        scored = _score_all(conn)
    return jsonify(scored)


@app.route("/api/scan", methods=["POST"])
def run_scan():
    """Run a market scan over the watchlist and score it.

    Default = mock/sample mode (no network, no Viagogo). A live scrape
    needs SCAN_LIVE=True in the environment AND body {"live": true}.
    Snapshots are stored so price history accumulates for future ML.
    Opportunities crossing the alert thresholds are sent to Discord.
    """
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return _bad("JSON body required")
    want_live = bool(data.get("live")) and os.environ.get("SCAN_LIVE", "False").lower() == "true"
    with _conn() as conn:
        watch = store.list_watchlist(conn)
        if not watch:
            return _bad("watchlist is empty — add events first (POST /api/watchlist or seed the example)")
        monitor = MarketMonitor(live=want_live, captcha_solver=_captcha_solver())
        snapshots = monitor.scan(watch)
        for snap in snapshots:
            store.save_snapshot(conn, snap)
        scored = _score_all(conn)
    thresholds = _scanner_thresholds()
    notified = 0
    alerts = []
    for opp in scored:
        if crosses_threshold(opp, thresholds["min_profit"], thresholds["min_confidence"]):
            result = notify_opportunity(_webhook(), opp, dry_run=dry_run())
            alerts.append({"event": opp["event_name"], "discord": result})
            if result.get("sent"):
                notified += 1
    logger.info("Scan done: %d snapshots, %d opportunities, %d Discord alerts sent",
                len(snapshots), len(scored), notified)
    return jsonify({"ok": True, "mode": "live" if want_live else "mock-sample",
                    "scanned": len(snapshots), "opportunities": scored,
                    "alerts": alerts, "discord_notified": notified,
                    "thresholds": thresholds, "log": monitor.log})


@app.route("/api/watchlist", methods=["GET", "POST"])
def watchlist():
    if request.method == "GET":
        with _conn() as conn:
            return jsonify(store.list_watchlist(conn))
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    name = data.get("event_name")
    url = data.get("event_url")
    errors = []
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        errors.append("event_name is required (1-200 characters)")
    if not _valid_url(url):
        errors.append("event_url must be a valid http(s) URL")
    if data.get("category") and data["category"] not in CATEGORIES:
        errors.append(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
    try:
        face = float(data["face_price"]) if data.get("face_price") is not None else None
        if face is not None and not 0 < face <= 10000:
            errors.append("face_price must be > 0 and <= 10000")
    except (TypeError, ValueError):
        errors.append("face_price must be a number")
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    row = {"event_name": name.strip(), "event_url": url,
           "category": data.get("category", "football"),
           "section": data.get("section", "General"),
           "currency": data.get("currency", "GBP"),
           "face_price": face, "quantity": int(data.get("quantity", 2))}
    with _conn() as conn:
        row["id"] = store.add_watchlist(conn, row)
    return jsonify({"ok": True, "watchlist": row}), 201


@app.route("/api/watchlist/<int:watch_id>", methods=["DELETE"])
def watchlist_delete(watch_id):
    with _conn() as conn:
        if not store.remove_watchlist(conn, watch_id):
            return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/watchlist/seed", methods=["POST"])
def watchlist_seed():
    """Load watchlist.example.json into the watchlist (skips duplicates)."""
    path = BASE / "watchlist.example.json"
    if not path.exists():
        return _bad("watchlist.example.json not found")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    added = 0
    with _conn() as conn:
        existing = {w["event_url"] for w in store.list_watchlist(conn)}
        for entry in data.get("watchlist", []):
            if entry.get("event_url") in existing:
                continue
            store.add_watchlist(conn, entry)
            added += 1
    logger.info("Watchlist seeded: %d events added", added)
    return jsonify({"ok": True, "added": added})


@app.route("/api/snapshots")
def snapshots():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        return _bad("limit must be an integer")
    limit = max(1, min(limit, 200))
    with _conn() as conn:
        return jsonify(store.list_snapshots(conn, request.args.get("event_url"), limit))


@app.route("/api/opportunities/test-discord", methods=["POST"])
def opportunities_test_discord():
    """Send the top-ranked opportunity to Discord (dry-run payload if no webhook)."""
    with _conn() as conn:
        scored = _score_all(conn)
    if not scored:
        return _bad("no opportunities yet — run a scan first (POST /api/scan)")
    return jsonify(notify_opportunity(_webhook(), scored[0], dry_run=dry_run()))


@app.route("/api/events/search")
def event_search():
    q = (request.args.get("q") or "").strip()
    if not q or len(q) > 200:
        return _bad("q query parameter is required (1-200 characters)")
    bot = _bot()
    return jsonify(bot.search_event(q, request.args.get("category", "football")))


# --- NopeCHA CAPTCHA solver (v1.2.2, optional, OFF by default) -----------
@app.route("/api/captcha/config", methods=["GET", "POST"])
def captcha_config():
    """GET returns the effective config (key masked, never in full).
    POST saves {enabled: bool, api_key: str}: a non-empty api_key is
    saved to the SQLite config; an empty string clears the saved key
    (an env NOPECHA_API_KEY, if set, still wins at runtime)."""
    if request.method == "GET":
        return jsonify({"ok": True, **_captcha_config()})
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    if "api_key" in data and not isinstance(data["api_key"], str):
        return _bad("api_key must be a string")
    if "enabled" in data and not isinstance(data["enabled"], bool):
        return _bad("enabled must be a boolean")
    with _conn() as conn:
        if "enabled" in data:
            store.set_config(conn, "nopecha_enabled", bool(data["enabled"]))
        if "api_key" in data:
            store.set_config(conn, "nopecha_api_key", data["api_key"].strip())
    logger.info("NopeCHA config updated (key %s)",
                _captcha_config()["api_key_masked"] or "none")
    return jsonify({"ok": True, **_captcha_config()})


@app.route("/api/captcha/status", methods=["POST"])
def captcha_status():
    """Check the key against NopeCHA (GET https://api.nopecha.com/v1/status).
    No key -> 'not configured' (no HTTP call). The key is never returned."""
    return jsonify(_captcha_solver().status())


@app.route("/api/captcha/test", methods=["POST"])
def captcha_test():
    """Mock solve only — proves the wiring without spending credits and
    without any real NopeCHA API call. Use 'Check status' to verify a
    real key."""
    return jsonify(_captcha_solver().mock_solve())


if __name__ == "__main__":
    problems = check_live_config()
    if problems:
        for problem in problems:
            logger.error("LIVE MODE BLOCKED: %s", problem)
        print("Refusing to start in LIVE_MODE: " + "; ".join(problems), file=sys.stderr)
        sys.exit(1)
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5002"))
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    if debug:
        logger.warning("FLASK_DEBUG=True — do not use debug mode in production")
    logger.info("Viagogo Listing Automation v%s starting — DRY_RUN=%s LIVE_MODE=%s on %s:%d",
                VERSION, dry_run(), live_mode(), host, port)
    print(f"Viagogo Listing Automation v{VERSION} — DRY_RUN={dry_run()}  LIVE_MODE={live_mode()}")
    print("Listing-only. No ticket buying in this system.")
    app.run(host=host, port=port, debug=debug)
