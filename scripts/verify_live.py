"""Live verification for a REAL machine (v1.5.0).

Run this on a normal computer with normal internet (NOT on the dev VM:
its egress proxy answers Chromium's CONNECT with 403 policy_denied —
see LIVE_VERIFICATION.md § "Why this could not run on the dev VM" —
so no Playwright run there can reach Viagogo at all).

    python scripts/verify_live.py

What it does (public pages only, NO login, NO listing, NO purchase):
1. Runs the REAL MarketMonitor (Playwright + stealth, the same code the
   app uses) against 3 REAL Viagogo public pages and prints the real
   lowest price / currency / listing count / demand signals it finds.
2. Opens sell.viagogo.com in the same browser and confirms it reaches
   the login gate — then STOPS. No credentials are entered.
Exit code 0 = at least one market page returned real prices AND the
sell gate was reached. Anything else prints exactly what failed.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market import MarketMonitor

# Real Viagogo public pages, verified to exist on 2026-10-28 (see
# LIVE_VERIFICATION.md for what each page showed that day).
EVENTS = [
    {"event_name": "Metallica - Sphere, Las Vegas (artist page)",
     "event_url": "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets",
     "category": "concert", "section": "100 Level", "currency": "USD"},
    {"event_name": "Real Madrid CF (artist page)",
     "event_url": "https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-151961718",
     "category": "football", "section": "General Admission", "currency": "EUR"},
    {"event_name": "FC Barcelona (artist page)",
     "event_url": "https://www.viagogo.co.uk/Sports-Tickets/Football/International-Football/Spanish-Premier-League/FC-Barcelona-Tickets",
     "category": "football", "section": "General Admission", "currency": "GBP"},
]

SELL_URL = "https://sell.viagogo.com/selltickets"


def check_sell_gate() -> dict:
    """Open the sell portal and report whether the login gate appears.
    No credentials, no search, no listing — stop at the gate."""
    from playwright.sync_api import sync_playwright

    from stealth import new_stealth_context

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = new_stealth_context(browser)
            page = context.new_page()
            page.set_default_timeout(60000)
            resp = page.goto(SELL_URL, wait_until="domcontentloaded")
            time.sleep(5)
            text = page.inner_text("body")
            lowered = text.lower()
            gate = any(word in lowered for word in
                       ("sign in", "log in", "email address", "create account"))
            return {"url": page.url, "title": page.title(),
                    "http_status": resp.status if resp else None,
                    "login_gate_reached": gate,
                    "page_text_chars": len(text)}
        finally:
            browser.close()


def main() -> int:
    print("Viagogo LIVE verification — public pages only, no login, no listing")
    print("=" * 72)
    monitor = MarketMonitor(live=True, scan_live=True)
    ok = 0
    for event in EVENTS:
        snap = monitor.collect(event)
        print(f"\n{event['event_name']}\n  URL: {event['event_url']}")
        print(f"  source: {snap.get('source')}  lowest: {snap.get('currency')} "
              f"{snap.get('lowest_price')}  avg: {snap.get('avg_price')}  "
              f"listings: {snap.get('listings_count')}  "
              f"people: {snap.get('people_searching')}  "
              f"signals: {snap.get('demand_signals')}")
        if snap.get("source") == "live" and snap.get("lowest_price") is not None:
            ok += 1
        else:
            print(f"  FAILED — source={snap.get('source')}; see logs/app.log")
    print("\nSell portal login gate:")
    try:
        gate = check_sell_gate()
        print(f"  URL: {gate['url']}\n  title: {gate['title']}\n  HTTP: {gate['http_status']}\n"
              f"  login gate reached: {gate['login_gate_reached']} "
              f"(page text {gate['page_text_chars']} chars)")
        gate_ok = bool(gate["login_gate_reached"])
    except Exception as exc:  # noqa: BLE001 — report, don't crash
        print(f"  FAILED — {type(exc).__name__}: {str(exc)[:200]}")
        gate_ok = False
    print("\n" + "=" * 72)
    print(f"Market pages with real prices: {ok}/{len(EVENTS)}")
    print(f"Sell login gate reached: {gate_ok}")
    if ok >= 1 and gate_ok:
        print("LIVE VERIFICATION PASSED")
        return 0
    print("LIVE VERIFICATION FAILED — see the failures above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
