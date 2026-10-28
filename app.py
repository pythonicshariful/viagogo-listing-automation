"""Flask UI + API for the Viagogo listing automation system (v1.4.0).

Listing-only + Opportunity Scanner (heuristic scoring, NO ML).
DRY-RUN is the safe default — bulk creation stores listings as `draft`
and the bot simulates posting (fake DRY-xxxx ids). Nothing touches
Viagogo unless live mode is switched on in the dashboard Settings
(two-step confirmation: tick + type LIVE) AND a saved session exists
AND the card / face-value / payout pre-flight passes.

NO .env FILE NEEDED (v1.3.0): the app runs with sensible defaults and
every setting is changeable in the dashboard and stored in the SQLite
config. Environment variables remain ONLY as an optional override for
advanced users — the app never requires one. Market scans are
mock/sample by default; a live scrape needs the "Live scans" toggle
in Settings.

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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import db as store
import settings as app_settings
from captcha import NopechaSolver, mask_key, solver_from_config
from discord_notify import is_valid_webhook_url, notify_opportunity, notify_sale, send_test
from market import MarketMonitor
from pricing import compute_listing_price, validate_rules
from scoring import DEFAULT_FEE_PCT, crosses_threshold, rank_opportunities, score_opportunity
from viagogo_bot import ViagogoBot

load_dotenv()
BASE = Path(__file__).resolve().parent
VERSION = "1.4.0"
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


def _conn():
    return store.connect(DB_PATH)


# --- Dashboard settings (v1.3.0) — stored in SQLite, env is override only
def _effective_settings() -> tuple[dict, list[str]]:
    """Effective settings: DB values, with env vars overriding where set.

    Returns (settings, env_overrides) — env_overrides lists the keys an
    environment variable is currently forcing, so the UI can say so
    instead of pretending the dashboard value applies.
    """
    with _conn() as conn:
        saved = store.get_config(conn, "settings")
    settings = app_settings.merge_settings(saved)
    overrides: list[str] = []

    def _env_bool(name: str) -> bool | None:
        raw = os.environ.get(name)
        return None if raw is None else raw.strip().lower() in {"true", "1", "yes", "on"}

    def _env_float(name: str) -> float | None:
        try:
            return float(os.environ[name]) if name in os.environ else None
        except (KeyError, ValueError):
            return None

    def _env_int(name: str) -> int | None:
        try:
            return int(os.environ[name]) if name in os.environ else None
        except (KeyError, ValueError):
            return None

    if "DRY_RUN" in os.environ:
        settings["mode"] = "dry" if _env_bool("DRY_RUN") else "live"
        overrides.append("mode")
    elif "LIVE_MODE" in os.environ:
        settings["mode"] = "live" if _env_bool("LIVE_MODE") else "dry"
        overrides.append("mode")
    if "VIAGOGO_SESSION_FILE" in os.environ:
        settings["session_file"] = os.environ["VIAGOGO_SESSION_FILE"]
        overrides.append("session_file")
    if "SCAN_LIVE" in os.environ:
        settings["scan_live"] = bool(_env_bool("SCAN_LIVE"))
        overrides.append("scan_live")
    if _env_float("SCAN_DELAY_S") is not None:
        settings["scan_delay_s"] = _env_float("SCAN_DELAY_S")  # type: ignore[assignment]
        overrides.append("scan_delay_s")
    if _env_int("VIAGOGO_TIMEOUT_MS") is not None:
        settings["page_timeout_ms"] = _env_int("VIAGOGO_TIMEOUT_MS")  # type: ignore[assignment]
        overrides.append("page_timeout_ms")
    if "PLAYWRIGHT_HEADLESS" in os.environ:
        settings["headless"] = bool(_env_bool("PLAYWRIGHT_HEADLESS"))
        overrides.append("headless")
    if "VIAGOGO_PROXY" in os.environ:
        settings["proxy_url"] = os.environ["VIAGOGO_PROXY"]
        overrides.append("proxy_url")
    if "STEALTH_ENABLED" in os.environ:
        settings["stealth_enabled"] = bool(_env_bool("STEALTH_ENABLED"))
        overrides.append("stealth_enabled")
    if "STEALTH_LOCALE" in os.environ:
        settings["stealth_locale"] = os.environ["STEALTH_LOCALE"]
        overrides.append("stealth_locale")
    if "STEALTH_TIMEZONE" in os.environ:
        settings["stealth_timezone"] = os.environ["STEALTH_TIMEZONE"]
        overrides.append("stealth_timezone")
    if "FLASK_HOST" in os.environ:
        settings["host"] = os.environ["FLASK_HOST"]
        overrides.append("host")
    if _env_int("FLASK_PORT") is not None:
        settings["port"] = _env_int("FLASK_PORT")  # type: ignore[assignment]
        overrides.append("port")
    if "LOG_LEVEL" in os.environ:
        settings["log_level"] = os.environ["LOG_LEVEL"].upper()
        overrides.append("log_level")
    return settings, overrides


def _settings() -> dict:
    return _effective_settings()[0]


def dry_run() -> bool:
    return _settings()["mode"] != "live"


def live_mode() -> bool:
    return _settings()["mode"] == "live"


def _live_confirmed() -> bool:
    """Two-step UI confirmation (typed LIVE) or the env override."""
    if os.environ.get("LIVE_CONFIRM", "").lower() == "yes":
        return True
    with _conn() as conn:
        return bool(store.get_config(conn, "live_confirmed_at"))


def session_file() -> str:
    return _settings()["session_file"]


def _session_path() -> Path:
    """Absolute path of the saved session file (relative names live
    next to app.py, so a launch from another folder still finds it)."""
    path = Path(session_file())
    return path if path.is_absolute() else BASE / path


def _session_status() -> dict:
    """Session presence only — contents are never read or returned."""
    path = _session_path()
    if not path.exists():
        return {"present": False, "file": path.name, "size_bytes": None,
                "modified": None}
    stat = path.stat()
    return {"present": True, "file": path.name, "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()}


def _fee_pct() -> float:
    return float(_settings().get("fee_pct", DEFAULT_FEE_PCT))


def check_live_config() -> list[str]:
    """Live-mode blockers (empty = OK to run live).

    The app now always STARTS (v1.3.0) so the user can fix these in the
    dashboard — e.g. upload the session file. Live ACTIONS are still
    refused until every problem here is gone.
    """
    if not live_mode():
        return []
    problems = []
    if not _session_status()["present"]:
        problems.append(f"Saved session not found: {session_file()} — upload it in Settings (Seller session)")
    if not _live_confirmed():
        problems.append("Live mode was not confirmed — switch it on in Settings (tick the box and type LIVE)")
    return problems


def _server_settings() -> dict:
    """Host / port / log level for startup: dashboard values, env wins."""
    settings, _ = _effective_settings()
    return {"host": settings["host"], "port": int(settings["port"]),
            "log_level": settings["log_level"]}


# --- validation helpers ----------------------------------------------------
CATEGORIES = {"football", "concert", "sport", "theatre", "other"}


def _bad(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


def _plain_error(exc: Exception) -> str:
    """One plain-English line for the UI, never a traceback. Our own
    RuntimeErrors are already plain English and are passed through;
    anything else (e.g. a long Playwright error) is shortened to its
    first line and capped, so the dashboard stays readable and a
    non-technical user can act on it. The full traceback stays in
    logs/app.log only."""
    text = str(exc).strip().splitlines()
    first = text[0] if text else "something went wrong"
    if "Traceback" in first or first.startswith("File \""):
        return "Something went wrong — please check logs/app.log and send the last lines to Shariful."
    return first[:300]


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
    # Payout (v1.4.0): one payout method per listing / per bulk batch.
    payout = data.get("payout_method", "PayPal")
    if payout not in {"PayPal", "Direct deposit"}:
        errors.append("payout_method must be 'PayPal' or 'Direct deposit'")
    elif payout == "PayPal":
        email = data.get("paypal_email")
        if not isinstance(email, str) or not email.strip():
            errors.append("paypal_email is required when payout_method is PayPal — "
                          "enter the PayPal email that should receive the money")
        elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            errors.append("paypal_email must be a valid email address")
    return errors


def _conn():
    return store.connect(DB_PATH)


def _config() -> dict:
    with _conn() as conn:
        cfg = store.get_config(conn, "price_rules") or {}
    cfg.setdefault("markup_pct", 80)
    cfg.setdefault("min_price", 50)
    cfg.setdefault("max_price", 1500)  # v1.4.0: USD events (Metallica ~$860) need a higher cap
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
    """Listing bot wired with the dashboard settings + NopeCHA solver
    (inert when no key is configured — challenge pages still stop the bot)."""
    settings = _settings()
    return ViagogoBot(
        dry_run=dry_run(), mock_url=os.environ.get("MOCK_PORTAL_URL") or None,
        mock_sales_url=os.environ.get("MOCK_SALES_URL") or None,
        captcha_solver=_captcha_solver(),
        live_mode=live_mode(), live_confirmed=_live_confirmed(),
        proxy=settings["proxy_url"] or None,
        session_file=str(_session_path()),
        headless=bool(settings["headless"]),
        page_timeout_ms=int(settings["page_timeout_ms"]),
        stealth_locale=settings["stealth_locale"],
        stealth_timezone=settings["stealth_timezone"],
        stealth_enabled=bool(settings["stealth_enabled"]))


# --- Opportunity Scanner helpers -------------------------------------------
def _scanner_thresholds() -> dict:
    with _conn() as conn:
        saved = store.get_config(conn, "scanner_thresholds") or {}
    return {"min_profit": float(saved.get("min_profit", 50.0)),
            "min_confidence": int(saved.get("min_confidence", 50))}


def _score_all(conn) -> list[dict]:
    """Score the latest snapshot of every watched event (heuristic only).
    Profit uses the seller fee % from Settings, not the hardcoded default."""
    watch = {w["event_url"]: w for w in store.list_watchlist(conn)}
    snapshots = store.latest_snapshots(conn)
    rules = _config()
    fee_pct = _fee_pct()
    scored: list[dict] = []
    for snap in snapshots:
        entry = watch.get(snap.get("event_url") or "")
        buy_cost = entry.get("face_price") if entry else None
        qty = int(entry.get("quantity", 2)) if entry else 2
        scored.append(score_opportunity(snap, buy_cost=buy_cost, quantity=qty,
                                        fee_pct=fee_pct, rules=rules))
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
                    "dry_run": dry_run(), "live_mode": live_mode(),
                    "mode": "live" if live_mode() else "dry",
                    "session_present": _session_status()["present"],
                    "live_blockers": check_live_config()})


@app.route("/")
def index():
    return render_template("index.html", dry_run=dry_run(),
                           live=live_mode())


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
            return jsonify([store.public_listing(r) for r in store.list_listings(conn, status)])
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
           "currency": rules.get("currency", "GBP"),
           "payout_method": data.get("payout_method", "PayPal"),
           "paypal_email": (data.get("paypal_email") or "").strip() or None,
           "status": "draft"}
    with _conn() as conn:
        row["id"] = store.create_listing(conn, row)
    logger.info("Listing %s created (draft) for %s", row["id"], row["event_name"])
    return jsonify({"ok": True, "listing": store.public_listing(row)}), 201


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
                   "currency": rules.get("currency", "GBP"),
                   "payout_method": data.get("payout_method", "PayPal"),
                   "paypal_email": (data.get("paypal_email") or "").strip() or None,
                   "status": "draft"}
            row["id"] = store.create_listing(conn, row)
            created.append(store.public_listing(row))
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
            store.update_listing(conn, listing_id, status="failed", last_error=_plain_error(exc))
        return jsonify({"ok": False, "error": _plain_error(exc)}), 502
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

    v1.4.0: real sale detection (viagogo_bot.check_sales) drives the
    logged-in seller dashboard (or the mock sales page when
    MOCK_SALES_URL is set). In dry-run, or live without a saved session,
    it returns available=false with a plain-English reason and NEVER
    fakes a sale. Use /api/sales/simulate to test the Discord path
    without Viagogo."""
    bot = _bot()
    with _conn() as conn:
        # Only listings that could have sold: not already sold/deleted.
        open_listings = [r for r in store.list_listings(conn)
                         if r.get("status") in {"active", "paused", "draft"}]
    try:
        result = bot.check_sales(open_listings)
    except Exception as exc:  # browser errors must not crash the API
        logger.exception("Sale check failed")
        return jsonify({"ok": False, "available": False, "sales_found": 0,
                        "discord_notified": 0,
                        "error": _plain_error(exc)}), 502
    if not result.get("available"):
        return jsonify({"ok": True, "available": False, "sales_found": 0,
                        "discord_notified": 0, "note": result.get("reason", "")})
    sales = result.get("sales") or []
    notified = 0
    with _conn() as conn:
        for s in sales:
            row = store.get_listing(conn, s["listing_id"])
            if not row or row.get("status") == "sold":
                continue  # already recorded — never notify twice
            store.record_sale(conn, s["listing_id"], s.get("sale_price"))
            store.update_listing(conn, s["listing_id"], status="sold")
            if notify_sale(_webhook(), row, s.get("sale_price"), dry_run=dry_run()).get("sent"):
                notified += 1
    return jsonify({"ok": True, "available": True, "sales_found": len(sales),
                    "discord_notified": notified,
                    "sales": [{**s, "matched_text": s.get("matched_text", "")[:120]}
                              for s in sales],
                    "note": "Sale detection is live but its selectors are not yet "
                            "verified against a real sale — confirm the first real "
                            "sale by hand in the seller dashboard."})


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
                           live=live_mode())


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
    needs the "Live scans" toggle ON in Settings (or SCAN_LIVE=True);
    the request body can still say {"live": false} to force a mock run.
    Snapshots are stored so price history accumulates for future ML.
    Opportunities crossing the alert thresholds are sent to Discord.
    """
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return _bad("JSON body required")
    settings = _settings()
    want_live = bool(data.get("live", True)) and bool(settings["scan_live"])
    with _conn() as conn:
        watch = store.list_watchlist(conn)
        if not watch:
            return _bad("watchlist is empty — add events first (POST /api/watchlist or seed the example)")
        monitor = MarketMonitor(
            live=want_live, captcha_solver=_captcha_solver(),
            proxy=settings["proxy_url"] or None,
            delay_s=float(settings["scan_delay_s"]),
            scan_live=bool(settings["scan_live"]),
            headless=bool(settings["headless"]),
            page_timeout_ms=int(settings["page_timeout_ms"]),
            stealth_locale=settings["stealth_locale"],
            stealth_timezone=settings["stealth_timezone"],
            stealth_enabled=bool(settings["stealth_enabled"]))
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


# --- Dashboard settings (v1.3.0) — everything in the UI, no .env needed
@app.route("/api/settings", methods=["GET", "POST"])
def settings_route():
    """GET returns every setting (proxy shown masked, never in full) plus
    session status and live-mode blockers. POST saves a partial update.

    Switching mode to "live" needs the two-step confirmation in the body:
    {"mode": "live", "confirm_live": true, "confirm_text": "LIVE"}.
    Without it the request is rejected — the app must never go live by
    accident. Switching back to "dry" clears the confirmation.
    Host / port / log level apply on the next restart (the response says so).
    """
    if request.method == "GET":
        settings, env_overrides = _effective_settings()
        return jsonify({"ok": True, "settings": settings,
                        "env_overrides": env_overrides,
                        "proxy_url_masked": app_settings.mask_proxy(settings["proxy_url"]),
                        "session": _session_status(),
                        "live_blockers": check_live_config(),
                        "locales": app_settings.LOCALES,
                        "timezones": app_settings.TIMEZONES,
                        "log_levels": app_settings.LOG_LEVELS,
                        "restart_required_for": sorted(app_settings.RESTART_KEYS)})
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        return _bad("JSON body required")
    # Confirmation fields are not settings — pull them out before validation.
    confirm_live = data.pop("confirm_live", None)
    confirm_text = data.pop("confirm_text", None)
    cleaned, errors = app_settings.validate_settings(data)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    if cleaned.get("mode") == "live":
        if confirm_live is not True or confirm_text != "LIVE":
            return jsonify({"ok": False, "error": "To switch to LIVE mode: tick the "
                           "confirmation box AND type LIVE — live posts real listings on Viagogo"}), 400
    with _conn() as conn:
        saved = store.get_config(conn, "settings") or {}
        saved.update(cleaned)
        if cleaned.get("mode") == "live":
            store.set_config(conn, "live_confirmed_at",
                             datetime.now(timezone.utc).isoformat())
        elif cleaned.get("mode") == "dry":
            store.set_config(conn, "live_confirmed_at", None)
        store.set_config(conn, "settings", saved)
    restart_needed = bool(set(app_settings.RESTART_KEYS) & set(cleaned))
    if "log_level" in cleaned:
        logging.getLogger().setLevel(cleaned["log_level"].upper())
        logger.setLevel(cleaned["log_level"].upper())
    logger.info("Settings updated: %s (restart needed: %s)",
                sorted(cleaned), restart_needed)
    settings, env_overrides = _effective_settings()
    return jsonify({"ok": True, "settings": settings,
                    "env_overrides": env_overrides,
                    "proxy_url_masked": app_settings.mask_proxy(settings["proxy_url"]),
                    "session": _session_status(),
                    "live_blockers": check_live_config(),
                    "restart_required": restart_needed,
                    "restart_note": ("Host / port / log level apply after restarting the app."
                                     if restart_needed else None)})


@app.route("/api/session/upload", methods=["POST"])
def session_upload():
    """Upload a saved Playwright storage_state (auth_state.json).

    Multipart form, file field "file". The file must be a JSON object
    with a "cookies" or "origins" list — anything else is rejected.
    Contents are never returned or logged; only presence/size/date.
    """
    if "file" not in request.files:
        return _bad("no file uploaded — send a multipart form with field 'file'")
    upload = request.files["file"]
    raw = upload.read()
    data, error = app_settings.validate_storage_state(raw)
    if error:
        return _bad(error)
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    logger.info("Session file uploaded: %s (%d bytes, %d cookies)",
                path.name, len(raw), len(data.get("cookies") or []))
    return jsonify({"ok": True, "session": _session_status(),
                    "live_blockers": check_live_config()})


@app.route("/api/session/clear", methods=["POST"])
def session_clear():
    """Delete the saved session file (log out). Live actions are refused
    until a new session is uploaded."""
    path = _session_path()
    removed = False
    if path.exists():
        path.unlink()
        removed = True
    logger.info("Session file cleared: %s (was present: %s)", path.name, removed)
    return jsonify({"ok": True, "removed": removed, "session": _session_status(),
                    "live_blockers": check_live_config()})


@app.route("/api/proxy/test", methods=["POST"])
def proxy_test():
    """Test the configured (or supplied) proxy with a quick request to
    https://example.com. The proxy URL — including any credentials —
    is never logged; the response shows it only masked."""
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return _bad("JSON body required")
    proxy_url = data.get("proxy_url") or _settings()["proxy_url"]
    if not proxy_url:
        return _bad("no proxy configured — enter a proxy URL first")
    parsed = urlparse(str(proxy_url))
    if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
        return _bad("proxy_url must look like http://host:port or http://user:pass@host:port")
    result = app_settings.probe_proxy(proxy_url)
    return jsonify({"ok": result["ok"], **result,
                    "proxy_url_masked": app_settings.mask_proxy(proxy_url)})


if __name__ == "__main__":
    # v1.3.0: the app ALWAYS starts, even in live mode with blockers —
    # the user fixes them in the dashboard (e.g. uploads the session).
    # Live ACTIONS are still refused until every blocker is gone.
    problems = check_live_config()
    for problem in problems:
        logger.warning("LIVE MODE BLOCKED (fix in Settings): %s", problem)
    server = _server_settings()
    host, port = server["host"], server["port"]
    try:
        logging.getLogger().setLevel(server["log_level"].upper())
    except ValueError:
        pass
    debug = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    if debug:
        logger.warning("FLASK_DEBUG=True — do not use debug mode in production")
    logger.info("Viagogo Listing Automation v%s starting — DRY_RUN=%s LIVE_MODE=%s on %s:%d",
                VERSION, dry_run(), live_mode(), host, port)
    print(f"Viagogo Listing Automation v{VERSION} — DRY_RUN={dry_run()}  LIVE_MODE={live_mode()}")
    print("Listing-only. No ticket buying in this system.")
    print("No .env needed — open the dashboard and use Settings for everything.")
    app.run(host=host, port=port, debug=debug)
