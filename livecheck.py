"""Dashboard + script "live check" runner (v1.5.1).

One shared implementation so the button in the Opportunities page and
scripts/verify_live.py prove the same thing the same way:

- Open up to 3 real Viagogo public pages in a REAL browser (Playwright
  + stealth, the same code the scanner uses) and report what the
  browser actually saw: lowest price, currency, listings, people,
  demand signals — plus diagnostics (page title, final URL, text
  length, a 500-char excerpt, challenge kind, screenshot) so a failed
  check says WHY instead of returning silent all-None values.
- Open sell.viagogo.com and confirm it reaches the login gate — then
  STOP. No login, no listing, no purchase, no credentials.

Nothing here posts anything or logs in. A run never crashes the
caller: every failure is a result with a plain-English reason.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("viagogo-listing-automation.livecheck")

SELL_URL = "https://sell.viagogo.com/selltickets"
MAX_LIVE_CHECK_URLS = 3


def new_run_id() -> str:
    """Short unique id for a run (used in the API + evidence filenames)."""
    return uuid.uuid4().hex[:8]


def format_diag(diag: dict) -> str:
    """Diagnostics as printable lines: title, URL, text length, excerpt,
    challenge, reason, screenshot. This is what the user reads when a
    live check fails — it must name the cause, not hide it."""
    lines = [
        f"  page title: {diag.get('title') or '(no title)'}",
        f"  final URL: {diag.get('final_url') or diag.get('event_url') or '?'}",
        f"  HTTP status: {diag.get('http_status')}",
        f"  readable text: {diag.get('text_chars')} chars in {diag.get('elapsed_s')}s",
    ]
    excerpt = (diag.get("text_excerpt") or "").strip().replace("\n", " ")
    lines.append(f"  page text (first 500 chars): {excerpt[:500] or '(empty)'}")
    if diag.get("challenge"):
        lines.append(f"  challenge detected: {diag['challenge']}")
    if diag.get("screenshot"):
        lines.append(f"  screenshot: {diag['screenshot']}")
    if diag.get("reason"):
        lines.append(f"  reason: {diag['reason']}")
    return "\n".join(lines)


def format_result(result: dict) -> str:
    """One live-check result as printable lines for the console / evidence file."""
    snap = result.get("snapshot") or {}
    diag = result.get("diagnostics") or {}
    lines = [
        f"{result.get('event_name')}",
        f"  URL: {result.get('event_url')}",
        f"  source: {snap.get('source')}  lowest: {snap.get('currency')} "
        f"{snap.get('lowest_price')}  avg: {snap.get('avg_price')}  "
        f"listings: {snap.get('listings_count')}  "
        f"people: {snap.get('people_searching')}  "
        f"signals: {snap.get('demand_signals')}",
    ]
    if snap.get("page_kind"):
        lines.append(f"  page kind: {snap.get('page_kind')}"
                     + (f" ({snap.get('events_count')} events)" if snap.get("events_count") else ""))
    if snap.get("page_note"):
        lines.append(f"  note: {snap['page_note']}")
    if result.get("status") != "ok":
        lines.append(f"  FAILED — {result.get('reason') or snap.get('source')}")
    lines.append(format_diag(diag))
    return "\n".join(lines)


def write_evidence(evidence_dir: Path, run_id: str, run: dict) -> Path:
    """Human-readable evidence file for a run: every result + diagnostics
    + the sell-gate outcome. Returns the file path."""
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"live-check-{run_id}.txt"
    lines = [
        f"Viagogo live check — run {run_id}",
        f"Started: {run.get('started_at')}",
        f"Finished: {run.get('finished_at')}",
        f"Status: {run.get('status')}",
        f"Show browser: {run.get('headed')}",
        "",
    ]
    for result in run.get("results") or []:
        lines.append(format_result(result))
        lines.append("")
    gate = run.get("sell_gate") or {}
    lines.append("Sell portal login gate:")
    if gate:
        lines.append(f"  URL: {gate.get('url')}")
        lines.append(f"  title: {gate.get('title')}")
        lines.append(f"  HTTP status: {gate.get('http_status')}")
        lines.append(f"  login gate reached: {gate.get('login_gate_reached')}")
        lines.append(f"  page text: {gate.get('page_text_chars')} chars")
        if gate.get("text_excerpt"):
            lines.append(f"  page text (first 500 chars): "
                         f"{gate['text_excerpt'][:500]}")
        if gate.get("screenshot"):
            lines.append(f"  screenshot: {gate['screenshot']}")
        if gate.get("error"):
            lines.append(f"  error: {gate['error']}")
    else:
        lines.append("  (not run)")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def check_sell_gate(headed: bool = False, screenshot_dir=None,
                    timeout_ms: int = 60000,
                    progress=None) -> dict:
    """Open the sell portal and report whether the login gate appears.

    No credentials, no search, no listing — stop at the gate. Every
    step prints progress (via `progress`, default print) BEFORE the
    slow part starts, so a cut-off log still shows where it stopped.
    Total time is bounded by the goto/inner_text timeouts — this never
    hangs forever.
    """
    from playwright.sync_api import sync_playwright

    from stealth import new_stealth_context

    def _say(msg: str) -> None:
        if progress is not None:
            progress(msg)
        else:
            print(msg, flush=True)

    started = time.time()
    out: dict = {"url": SELL_URL, "title": "", "http_status": None,
                 "login_gate_reached": False, "page_text_chars": 0,
                 "text_excerpt": "", "challenge": None, "screenshot": None,
                 "elapsed_s": 0.0, "error": None}
    _say("Opening the sell portal (sell.viagogo.com) — this takes about 20 seconds…")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not headed)
            try:
                context = new_stealth_context(browser)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                _say("Browser open — loading sell.viagogo.com…")
                resp = page.goto(SELL_URL, wait_until="domcontentloaded",
                                 timeout=min(timeout_ms, 30000))
                out["http_status"] = resp.status if resp else None
                time.sleep(3)
                _say("Page loaded — reading it…")
                try:
                    out["title"] = page.title()
                except Exception:
                    out["title"] = ""
                out["url"] = page.url
                try:
                    text = page.inner_text("body", timeout=15000)
                except Exception as exc:
                    out["error"] = f"Could not read the page text: {type(exc).__name__}"
                    text = ""
                out["page_text_chars"] = len(text)
                out["text_excerpt"] = text[:500]
                lowered = text.lower()
                out["login_gate_reached"] = any(
                    word in lowered for word in
                    ("sign in", "log in", "email address", "create account"))
                if screenshot_dir:
                    shot = (Path(screenshot_dir) /
                            f"live-sell-gate-{int(time.time())}.png")
                    try:
                        page.screenshot(path=str(shot))
                        out["screenshot"] = str(shot)
                    except Exception as exc:
                        logger.debug("sell-gate screenshot failed: %s", exc)
                if not out["login_gate_reached"] and not out["error"]:
                    out["error"] = ("The sell portal loaded but no login form was found — "
                                    "it may be a bot-check page or a redirect. "
                                    "See the screenshot / page text.")
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 — report, never raise
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    out["elapsed_s"] = round(time.time() - started, 1)
    return out


def run_live_check(watchlist: list[dict], settings: dict | None = None,
                   headed: bool = False, captcha_solver=None,
                   progress=None, evidence_dir: Path | None = None,
                   run_id: str | None = None) -> dict:
    """Run one live check over the first MAX_LIVE_CHECK_URLS watchlist
    entries, then the sell-portal gate.

    `settings` is the dashboard settings dict (proxy, scan delay, page
    timeout, stealth, headless) — None keeps the MarketMonitor defaults.
    `progress` receives plain strings as each step starts/finishes.
    Returns the run dict (also written to the evidence file when
    evidence_dir is given). Never raises: a failed step is a result
    with a reason.
    """
    from market import MarketMonitor

    run_id = run_id or new_run_id()
    started_at = datetime.now(timezone.utc).isoformat()
    run: dict = {"run_id": run_id, "started_at": started_at, "finished_at": None,
                 "status": "running", "headed": bool(headed), "results": [],
                 "sell_gate": None, "evidence_file": None}

    def _say(msg: str) -> None:
        if progress is not None:
            progress(msg)

    settings = dict(settings or {})
    events = list(watchlist or [])[:MAX_LIVE_CHECK_URLS]
    monitor = MarketMonitor(
        live=True, captcha_solver=captcha_solver,
        proxy=settings.get("proxy_url") or None,
        delay_s=float(settings.get("scan_delay_s", 5.0)),
        scan_live=True,
        headless=not headed,
        page_timeout_ms=int(settings.get("page_timeout_ms", 60000)),
        stealth_locale=settings.get("stealth_locale"),
        stealth_timezone=settings.get("stealth_timezone"),
        stealth_enabled=settings.get("stealth_enabled"))
    for i, event in enumerate(events):
        name = event.get("event_name") or "Unnamed event"
        _say(f"[{i + 1}/{len(events)}] Checking {name} — opening the browser…")
        try:
            snap, diag = monitor.collect_with_diagnostics(
                event, screenshot_dir=evidence_dir, headed=headed)
        except Exception as exc:  # noqa: BLE001 — one bad event must not kill the run
            from market import parse_snapshot_text

            snap = parse_snapshot_text("", event)
            snap["source"] = "live-failed"
            diag = {"event_name": name, "event_url": event.get("event_url"),
                    "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "text_chars": 0, "text_excerpt": ""}
        ok = bool(snap.get("source") == "live" and snap.get("lowest_price") is not None)
        result = {"event_name": name, "event_url": event.get("event_url"),
                  "snapshot": snap, "diagnostics": diag,
                  "status": "ok" if ok else "failed",
                  "reason": "" if ok else (diag.get("reason") or
                                            snap.get("page_note") or
                                            f"no prices found (source={snap.get('source')})")}
        run["results"].append(result)
        _say(f"[{i + 1}/{len(events)}] {name}: "
             f"{'lowest ' + str(snap.get('currency')) + ' ' + str(snap.get('lowest_price')) if ok else 'FAILED — ' + result['reason']}")
        if i + 1 < len(events):
            time.sleep(monitor.delay_s)
    _say("Checking the sell portal login gate…")
    run["sell_gate"] = check_sell_gate(headed=headed, screenshot_dir=evidence_dir,
                                       timeout_ms=int(settings.get("page_timeout_ms", 60000)),
                                       progress=progress)
    ok_markets = sum(1 for r in run["results"] if r["status"] == "ok")
    gate_ok = bool((run["sell_gate"] or {}).get("login_gate_reached"))
    run["status"] = "passed" if (ok_markets >= 1 and gate_ok) else "failed"
    run["finished_at"] = datetime.now(timezone.utc).isoformat()
    if evidence_dir:
        run["evidence_file"] = str(write_evidence(Path(evidence_dir), run_id, run))
    return run


# --- small thread-safe store for the dashboard API ---------------------------
class LiveCheckStore:
    """In-memory runs for GET /api/live-check/<id>. The app keeps only
    the last few runs; evidence files in logs/ are the durable record."""

    def __init__(self, max_runs: int = 5):
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}
        self._order: list[str] = []
        self._max_runs = max_runs

    def start(self, run: dict) -> None:
        with self._lock:
            self._runs[run["run_id"]] = run
            self._order.append(run["run_id"])
            while len(self._order) > self._max_runs:
                self._runs.pop(self._order.pop(0), None)

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            return self._runs.get(run_id)

    def running(self) -> bool:
        with self._lock:
            return any(r.get("status") == "running" for r in self._runs.values())

    def list(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in self._runs[rid].items()
                     if k in {"run_id", "started_at", "finished_at", "status", "headed"}}
                    for rid in reversed(self._order)]


def event_link_hint(event_name: str) -> str:
    """Text to click on an artist page to reach one event, e.g.
    "Real Madrid CF vs Villarreal CF" from "Real Madrid CF (artist
    page) — Real Madrid CF vs Villarreal CF". Falls back to the event
    name itself when no hint can be derived."""
    name = (event_name or "").strip()
    if " — " in name:
        return name.split(" — ", 1)[1].strip()
    if " - " in name:
        tail = name.split(" - ", 1)[1].strip()
        return tail or name
    return name
