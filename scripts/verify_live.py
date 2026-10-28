"""Live verification for a REAL machine (v1.5.1).

Run this on a normal computer with normal internet (NOT on the dev VM:
its egress proxy answers Chromium's CONNECT with 403 policy_denied —
see LIVE_VERIFICATION.md § "Why this could not run on the dev VM" —
so no Playwright run there can reach Viagogo at all).

    python scripts/verify_live.py            # hidden browser (default)
    python scripts/verify_live.py --headed   # SHOW the browser on screen

What it does (public pages only, NO login, NO listing, NO purchase):
1. Metallica artist page — CONTROL. It lists many events and shows
   per-event "From $X" prices, so the parser should find prices here.
2. Click-through from that artist page to the Metallica Oct 29 single
   event — the page the scanner actually needs. Artist pages are NOT
   a valid scan target: they have no prices for ONE event (see
   LIVE_VERIFICATION.md — this was the 2026-10-28 root cause).
3. Click-through from the Real Madrid artist page to one single event.
4. Open sell.viagogo.com and confirm it reaches the login gate —
   then STOP. No credentials are entered.

Every step prints progress BEFORE the slow part starts (a cut-off log
still shows where it stopped), and every result prints diagnostics:
page title, final URL, text length, the first 500 chars of visible
text, whether a challenge was detected, and a screenshot path.
Nothing is silent: a failure always says WHY in plain words.
Evidence is written to logs/live-check-<timestamp>.txt.

Exit code 0 = at least one market check returned real prices AND the
sell gate was reached. Anything else prints exactly what failed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livecheck import check_sell_gate, format_result, new_run_id, write_evidence
from market import MarketMonitor

BASE = Path(__file__).resolve().parents[1]
LOG_DIR = BASE / "logs"

# Real Viagogo public pages, verified to exist on 2026-10-28 (see
# LIVE_VERIFICATION.md for what each page showed that day).
METALLICA_ARTIST = {
    "event_name": "Metallica (artist page) — control",
    "event_url": "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets",
    "category": "concert", "section": "100 Level", "currency": "USD"}
METALLICA_EVENT = {
    "event_name": "Metallica (artist page) — Metallica - 2 Day Pass (October 29 & 31)",
    "event_url": METALLICA_ARTIST["event_url"],
    "category": "concert", "section": "100 Level", "currency": "USD"}
REAL_MADRID_EVENT = {
    "event_name": "Real Madrid CF (artist page) — Real Madrid CF vs Villarreal CF",
    "event_url": "https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-151961718",
    "category": "football", "section": "General Admission", "currency": "EUR"}


def _say(msg: str) -> None:
    print(msg, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headed", action="store_true",
                        help="show the browser window on screen instead of running it hidden")
    args = parser.parse_args()
    headed = bool(args.headed)

    run_id = new_run_id()
    from datetime import datetime, timezone

    started_at = datetime.now(timezone.utc).isoformat()
    _say("Viagogo LIVE verification — public pages only, no login, no listing")
    _say("Browser: " + ("VISIBLE on your screen (--headed)" if headed
                        else "hidden (use --headed to watch it)"))
    _say("=" * 72)
    monitor = MarketMonitor(live=True, scan_live=True, headless=not headed)
    results: list[dict] = []

    # 1 — control: the artist page itself (per-event "From" prices).
    _say("\n[1/4] Metallica artist page (control) — opening the browser…")
    snap, diag = monitor.collect_with_diagnostics(
        METALLICA_ARTIST, screenshot_dir=LOG_DIR, headed=headed)
    results.append({"event_name": METALLICA_ARTIST["event_name"],
                    "event_url": METALLICA_ARTIST["event_url"],
                    "snapshot": snap, "diagnostics": diag,
                    "status": "ok" if snap.get("lowest_price") is not None else "failed",
                    "reason": diag.get("reason", "")})
    _say(format_result(results[-1]))

    # 2 — click-through to the single event (the page the scanner needs).
    _say("\n[2/4] Metallica single event (click-through from the artist page)…")
    snap, diag = monitor.collect_event_via_artist(
        METALLICA_EVENT, screenshot_dir=LOG_DIR, headed=headed)
    results.append({"event_name": "Metallica - 2 Day Pass (Oct 29 & 31, Sphere)",
                    "event_url": METALLICA_EVENT["event_url"],
                    "snapshot": snap, "diagnostics": diag,
                    "status": "ok" if snap.get("lowest_price") is not None else "failed",
                    "reason": diag.get("reason", "")})
    _say(format_result(results[-1]))

    # 3 — same click-through for Real Madrid (the page that returned
    # all-None on 2026-10-28 because the artist page has no prices).
    _say("\n[3/4] Real Madrid single event (click-through from the artist page)…")
    snap, diag = monitor.collect_event_via_artist(
        REAL_MADRID_EVENT, screenshot_dir=LOG_DIR, headed=headed)
    results.append({"event_name": "Real Madrid CF vs Villarreal CF",
                    "event_url": REAL_MADRID_EVENT["event_url"],
                    "snapshot": snap, "diagnostics": diag,
                    "status": "ok" if snap.get("lowest_price") is not None else "failed",
                    "reason": diag.get("reason", "")})
    _say(format_result(results[-1]))

    # 4 — sell portal login gate (with timeouts, never hangs).
    _say("\n[4/4] Sell portal login gate:")
    gate = check_sell_gate(headed=headed, screenshot_dir=LOG_DIR,
                           progress=_say)
    gate_ok = bool(gate.get("login_gate_reached"))
    _say(f"  URL: {gate.get('url')}\n  title: {gate.get('title')}\n"
         f"  HTTP status: {gate.get('http_status')}\n"
         f"  login gate reached: {gate_ok} (page text "
         f"{gate.get('page_text_chars')} chars, {gate.get('elapsed_s')}s)")
    if gate.get("text_excerpt"):
        _say(f"  page text (first 500 chars): {gate['text_excerpt'][:500]}")
    if gate.get("screenshot"):
        _say(f"  screenshot: {gate['screenshot']}")
    if gate.get("error"):
        _say(f"  error: {gate['error']}")

    ok = sum(1 for r in results if r["status"] == "ok")
    status = "passed" if (ok >= 1 and gate_ok) else "failed"
    run = {"run_id": run_id, "started_at": started_at,
           "finished_at": datetime.now(timezone.utc).isoformat(),
           "status": status, "headed": headed, "results": results,
           "sell_gate": gate, "evidence_file": None}
    evidence = write_evidence(LOG_DIR, run_id, run)
    _say("\n" + "=" * 72)
    _say(f"Market checks with real prices: {ok}/{len(results)}")
    _say(f"Sell login gate reached: {gate_ok}")
    _say(f"Evidence file: {evidence}")
    _say("LIVE VERIFICATION " + ("PASSED" if status == "passed" else "FAILED")
         + (" — see the reasons above" if status != "passed" else ""))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
