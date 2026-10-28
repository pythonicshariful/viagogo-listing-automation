"""Viagogo public market monitor — collects price/demand snapshots.

No login is needed for PUBLIC event pages (the buy-side pages anyone can
open). The seller pipeline (sell.viagogo.com) is a different, logged-in
flow and is handled by viagogo_bot.py — never mix the two.

Rate limits / politeness: at least SCAN_DELAY_S seconds between event
pages, max 2 attempts per page, 60s page timeout. Proxy via the existing
VIAGOGO_PROXY env var (Fayed asked "for proxy it's ok?" — yes: set
VIAGOGO_PROXY=http://user:pass@host:port in .env; residential rotating
proxies are recommended for market monitoring).

Stealth (v1.2.1, stealth.py): live scans launch through the shared
stealth helper (randomised desktop UA/viewport, seller-store locale +
timezone, init script hiding the usual automation tells). It reduces
detection risk but does NOT guarantee invisibility. By default a
CAPTCHA / Cloudflare challenge stops the scan for that event with
source "live-challenge". OPTIONAL NopeCHA path (v1.2.2, captcha.py):
only when the operator enables it AND configures their own NopeCHA
API key does the scanner attempt ONE solve per challenge page; solving
a CAPTCHA may violate Viagogo's terms and increases ban risk, and a
Cloudflare interstitial (no sitekey) cannot be solved by the Token API.

All fields are optional: a page that does not show a value returns None
for that field instead of crashing, and scoring.py lowers confidence
accordingly (R10). Never invent a price that was not on the page.

MOCK MODE (default for scans): no network at all. Snapshots come from
mock/sample_snapshots.json — numbers there are labelled SAMPLE and exist
only so the scanner, scoring and Discord alert can be demoed and tested
offline. Live scrape runs ONLY when SCAN_LIVE=True in the environment.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from captcha import solver_from_env
from stealth import ChallengeDetectedError, check_challenge_or_solve, new_stealth_context

logger = logging.getLogger("viagogo-listing-automation.market")

BASE = Path(__file__).resolve().parent
SAMPLE_FILE = BASE / "mock" / "sample_snapshots.json"
PAGE_TIMEOUT_MS = int(os.environ.get("VIAGOGO_TIMEOUT_MS", "60000"))
SCAN_DELAY_S = float(os.environ.get("SCAN_DELAY_S", "5"))
MAX_ATTEMPTS = 2

_PRICE_RE = re.compile(r"[£$€]\s*([\d,]+(?:\.\d{1,2})?)")
_PEOPLE_RE = re.compile(r"(\d[\d,]*)\s+people are (?:currently )?searching", re.I)
_LISTINGS_RE = re.compile(r"(\d[\d,]*)\s+(?:tickets?|listings?) (?:available|listed)", re.I)


def parse_prices(text: str) -> list[float]:
    """All currency amounts found in page text, as floats, in order."""
    out: list[float] = []
    for m in _PRICE_RE.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return out


def parse_people_searching(text: str) -> int | None:
    """'152 people are currently searching for tickets' -> 152."""
    m = _PEOPLE_RE.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def parse_listings_count(text: str) -> int | None:
    """'37 tickets available' / '12 listings available' -> count."""
    m = _LISTINGS_RE.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def parse_snapshot_text(text: str, event: dict) -> dict:
    """Turn raw page text into a snapshot dict. Missing values stay None."""
    prices = parse_prices(text or "")
    # Filter out absurd values (e.g. years, fees text) — ticket prices only.
    prices = [p for p in prices if 1 <= p <= 100000]
    return {
        "event_name": event.get("event_name", "Unknown event"),
        "event_url": event.get("event_url"),
        "category": event.get("category", "football"),
        "section": event.get("section", "General"),
        "currency": event.get("currency", "GBP"),
        "lowest_price": min(prices) if prices else None,
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "listings_count": parse_listings_count(text or ""),
        "people_searching": parse_people_searching(text or ""),
        "recent_sold_prices": [],
        "days_to_event": event.get("days_to_event"),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source": "live",
    }


def load_sample_snapshots() -> list[dict]:
    """SAMPLE data only — every number is labelled sample in the file."""
    if not SAMPLE_FILE.exists():
        return []
    with open(SAMPLE_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for snap in data.get("snapshots", []):
        snap = dict(snap)
        snap["source"] = "mock-sample"
        snap.setdefault("snapshot_at", datetime.now(timezone.utc).isoformat())
        out.append(snap)
    return out


class MarketMonitor:
    """Collect one snapshot per watched event. Mock by default."""

    def __init__(self, proxy: str | None = None, live: bool = False,
                 mock_snapshots: list[dict] | None = None,
                 delay_s: float = SCAN_DELAY_S, captcha_solver=None):
        self.proxy = proxy or os.environ.get("VIAGOGO_PROXY") or None
        self.live = live
        self.delay_s = delay_s
        # Optional NopeCHA solver (captcha.py): env by default; the web
        # app passes one built from the dashboard config. No key -> inert.
        self._captcha_solver = (captcha_solver if captcha_solver is not None
                                else solver_from_env())
        self._mock = mock_snapshots if mock_snapshots is not None else load_sample_snapshots()
        self.log: list[str] = []

    def scan_live(self) -> bool:
        return bool(self.live and os.environ.get("SCAN_LIVE", "False").lower() == "true")

    def collect(self, event: dict) -> dict:
        """One event -> one snapshot. Mock mode matches by event_url, else
        returns an empty snapshot (all None) so scoring lowers confidence
        instead of inventing numbers."""
        if not self.scan_live():
            for snap in self._mock:
                if snap.get("event_url") and snap.get("event_url") == event.get("event_url"):
                    result = dict(snap)
                    result.setdefault("event_name", event.get("event_name"))
                    result.setdefault("category", event.get("category", "football"))
                    result.setdefault("section", event.get("section", "General"))
                    result["snapshot_at"] = datetime.now(timezone.utc).isoformat()
                    self.log.append(f"mock snapshot: {result['event_name']} lowest={result.get('lowest_price')}")
                    return result
            # No mock data for this event: honest empty snapshot.
            empty = parse_snapshot_text("", event)
            empty["source"] = "mock-sample"
            self.log.append(f"mock snapshot: {event.get('event_name')} — no sample data, all fields None")
            return empty
        return self._collect_live(event)

    def _collect_live(self, event: dict) -> dict:
        """Live public-page scrape. One page, retries, then give up with
        an empty snapshot rather than raising into the scan.

        A CAPTCHA / Cloudflare challenge is NOT retried: with no NopeCHA
        key the run stops for that event with source "live-challenge".
        With NopeCHA enabled + configured, ONE solve is attempted for
        that page (see captcha.py); if it fails, the event is still
        recorded as "live-challenge"."""
        from playwright.sync_api import sync_playwright

        url = event.get("event_url") or ""
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with sync_playwright() as pw:
                    launch = {"headless": os.environ.get("PLAYWRIGHT_HEADLESS", "True").lower() != "false"}
                    if self.proxy:
                        # Proxy is set at browser launch, so it keeps
                        # working with stealth on (stealth only
                        # configures the context).
                        launch["proxy"] = {"server": self.proxy}
                    browser = pw.chromium.launch(**launch)
                    try:
                        context = new_stealth_context(browser)
                        page = context.new_page()
                        page.set_default_timeout(PAGE_TIMEOUT_MS)
                        page.goto(url, wait_until="domcontentloaded")
                        check_challenge_or_solve(page, self._captcha_solver)
                        time.sleep(random.uniform(2.0, 4.0))  # let React render
                        text = page.inner_text("body")
                    finally:
                        browser.close()
                snap = parse_snapshot_text(text, event)
                self.log.append(f"live snapshot: {snap['event_name']} lowest={snap.get('lowest_price')}")
                return snap
            except ChallengeDetectedError as exc:
                logger.error("market collect STOPPED for %s: %s", url, exc)
                self.log.append(f"live snapshot BLOCKED by challenge: {event.get('event_name')} — stopped, not solved")
                empty = parse_snapshot_text("", event)
                empty["source"] = "live-challenge"
                return empty
            except Exception as exc:  # noqa: BLE001 — live pages fail often; record and retry/empty
                last_exc = exc
                logger.warning("market collect attempt %d/%d failed for %s: %s",
                               attempt, MAX_ATTEMPTS, url, exc)
                time.sleep(2 ** attempt)
        logger.error("market collect failed for %s: %s", url, last_exc)
        empty = parse_snapshot_text("", event)
        empty["source"] = "live-failed"
        return empty

    def scan(self, watchlist: list[dict]) -> list[dict]:
        """Scan every watched event, with a polite delay between LIVE pages.
        Mock scans need no delay (no network)."""
        out: list[dict] = []
        for i, event in enumerate(watchlist):
            if i and self.scan_live():
                time.sleep(self.delay_s + random.uniform(0, 2.0))
            out.append(self.collect(event))
        return out
