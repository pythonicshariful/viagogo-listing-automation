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
offline. A live scrape runs ONLY when live scans are switched on in the
dashboard Settings (or SCAN_LIVE=True in the environment).
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
# Viagogo artist pages say "3,895 people viewed Real Madrid CF events in
# the past hour" (observed live 2026-10-28) — same signal, different words.
_PEOPLE_VIEWED_RE = re.compile(r"(\d[\d,]*)\s+people viewed", re.I)
_LISTINGS_RE = re.compile(r"(\d[\d,]*)\s+(?:tickets?|listings?) (?:available|listed)", re.I)
# "20 tickets left" / "1 ticket left" — Viagogo listing rows (observed in
# the wild on resale pages) use "left" instead of "available".
_LISTINGS_LEFT_RE = re.compile(r"(\d[\d,]*)\s+tickets?\s+left", re.I)
# Headline price on a real event page: "Tickets from $860", "From $813".
_FROM_PRICE_RE = re.compile(r"(?:tickets\s+)?from\s+([£$€])\s*([\d,]+(?:\.\d{1,2})?)", re.I)
# Scarcity wording seen on real Viagogo pages (observed live 2026-10-28):
# "Only 1% of tickets left", "Selling fast", "Top seller".
_ONLY_PCT_RE = re.compile(r"only\s+(\d+)\s*%\s+of tickets left", re.I)

_CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR"}


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
    """'152 people are currently searching for tickets' -> 152.
    Also Viagogo's '3,895 people viewed ... events in the past hour'."""
    m = _PEOPLE_RE.search(text or "") or _PEOPLE_VIEWED_RE.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def parse_listings_count(text: str) -> int | None:
    """'37 tickets available' / '12 listings available' -> count.
    Also '20 tickets left' (resale listing rows)."""
    m = _LISTINGS_RE.search(text or "") or _LISTINGS_LEFT_RE.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def parse_from_price(text: str) -> tuple[float | None, str | None]:
    """Headline price on a real event page: 'Tickets from $860' ->
    (860.0, 'USD'). None when the page shows no 'from' price."""
    m = _FROM_PRICE_RE.search(text or "")
    if not m:
        return None, None
    try:
        return float(m.group(2).replace(",", "")), _CURRENCY_SYMBOLS.get(m.group(1))
    except ValueError:
        return None, None


def parse_currency(text: str) -> str | None:
    """Currency of the first price on the page: '$' -> USD, '£' -> GBP,
    '€' -> EUR. None when the page shows no price at all."""
    m = re.search(r"([£$€])\s*[\d,]+", text or "")
    return _CURRENCY_SYMBOLS.get(m.group(1)) if m else None


def parse_scarcity(text: str) -> list[str]:
    """Demand/scarcity wording exactly as Viagogo shows it, e.g.
    ['only_1pct_left', 'selling_fast', 'top_seller']. Empty when none."""
    out: list[str] = []
    m = _ONLY_PCT_RE.search(text or "")
    if m:
        out.append(f"only_{int(m.group(1))}pct_left")
    lowered = (text or "").lower()
    if "selling fast" in lowered:
        out.append("selling_fast")
    if "top seller" in lowered:
        out.append("top_seller")
    return out


def parse_snapshot_text(text: str, event: dict) -> dict:
    """Turn raw page text into a snapshot dict. Missing values stay None.

    Real-page rules (see LIVE_VERIFICATION.md for the pages these were
    observed on):
    - lowest_price is the page's headline 'From $X' price when the page
      shows one (that IS Viagogo's cheapest listing); otherwise the
      lowest currency amount on the page.
    - currency comes from the page itself ($/£/€), falling back to the
      event's currency — never assume GBP for a US event.
    - demand signals are Viagogo's own words ('Only 1% of tickets
      left', 'Selling fast', 'Top seller'), kept verbatim as tags.
    """
    prices = parse_prices(text or "")
    # Filter out absurd values (e.g. years, fees text) — ticket prices only.
    prices = [p for p in prices if 1 <= p <= 100000]
    from_price, from_currency = parse_from_price(text or "")
    lowest = from_price if from_price is not None else (min(prices) if prices else None)
    page_currency = from_currency or parse_currency(text or "")
    return {
        "event_name": event.get("event_name", "Unknown event"),
        "event_url": event.get("event_url"),
        "category": event.get("category", "football"),
        "section": event.get("section", "General"),
        "currency": page_currency or event.get("currency", "GBP"),
        "lowest_price": lowest,
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "listings_count": parse_listings_count(text or ""),
        "people_searching": parse_people_searching(text or ""),
        "recent_sold_prices": [],
        "days_to_event": event.get("days_to_event"),
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "source": "live",
        "from_price": from_price,
        "demand_signals": parse_scarcity(text or ""),
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
    """Collect one snapshot per watched event. Mock by default.

    Dashboard settings (v1.3.0) arrive as constructor arguments; None
    keeps the old environment behaviour (SCAN_LIVE / PLAYWRIGHT_HEADLESS /
    VIAGOGO_TIMEOUT_MS / VIAGOGO_PROXY) as an advanced-user override.
    """

    def __init__(self, proxy: str | None = None, live: bool = False,
                 mock_snapshots: list[dict] | None = None,
                 delay_s: float = SCAN_DELAY_S, captcha_solver=None,
                 scan_live: bool | None = None, headless: bool | None = None,
                 page_timeout_ms: int | None = None,
                 stealth_locale: str | None = None,
                 stealth_timezone: str | None = None,
                 stealth_enabled: bool | None = None):
        self.proxy = proxy or os.environ.get("VIAGOGO_PROXY") or None
        self.live = live
        self.delay_s = delay_s
        self._scan_live_override = scan_live
        self.headless = (headless if headless is not None
                         else os.environ.get("PLAYWRIGHT_HEADLESS", "True").lower() != "false")
        self.page_timeout_ms = (page_timeout_ms if page_timeout_ms is not None
                                else PAGE_TIMEOUT_MS)
        self._stealth_locale = stealth_locale
        self._stealth_timezone = stealth_timezone
        self._stealth_enabled = stealth_enabled
        # Optional NopeCHA solver (captcha.py): env by default; the web
        # app passes one built from the dashboard config. No key -> inert.
        self._captcha_solver = (captcha_solver if captcha_solver is not None
                                else solver_from_env())
        self._mock = mock_snapshots if mock_snapshots is not None else load_sample_snapshots()
        self.log: list[str] = []

    def scan_live(self) -> bool:
        """Live scrape only when the scan asked for it AND live scans are
        enabled (dashboard setting first, else SCAN_LIVE env)."""
        if self._scan_live_override is not None:
            return bool(self.live and self._scan_live_override)
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
                    launch = {"headless": self.headless}
                    if self.proxy:
                        # Proxy is set at browser launch, so it keeps
                        # working with stealth on (stealth only
                        # configures the context).
                        launch["proxy"] = {"server": self.proxy}
                    browser = pw.chromium.launch(**launch)
                    try:
                        context = new_stealth_context(
                            browser, locale=self._stealth_locale,
                            timezone_id=self._stealth_timezone,
                            enabled=self._stealth_enabled)
                        page = context.new_page()
                        page.set_default_timeout(self.page_timeout_ms)
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
        snapshots, _ = self.scan_with_report(watchlist)
        return snapshots

    def scan_with_report(self, watchlist: list[dict]) -> tuple[list[dict], list[dict]]:
        """Scan every watched event and report live failures explicitly.

        Returns (snapshots, live_errors). live_errors has one entry per
        event whose LIVE check failed: {event_name, event_url, source,
        reason}. An empty list means every live check returned real
        page data. A live check that fails NEVER falls back to sample
        data — the snapshot keeps source "live-challenge" / "live-failed"
        with all prices None, and the caller must surface the error.
        """
        out: list[dict] = []
        errors: list[dict] = []
        for i, event in enumerate(watchlist):
            if i and self.scan_live():
                time.sleep(self.delay_s + random.uniform(0, 2.0))
            snap = self.collect(event)
            out.append(snap)
            if self.scan_live() and snap.get("source") in {"live-challenge", "live-failed"}:
                errors.append({
                    "event_name": event.get("event_name"),
                    "event_url": event.get("event_url"),
                    "source": snap["source"],
                    "reason": ("Viagogo showed a CAPTCHA / Cloudflare challenge — "
                               "the bot stopped instead of solving it"
                               if snap["source"] == "live-challenge" else
                               "The live page could not be loaded after 2 attempts — "
                               "see logs/app.log for the exact error"),
                })
        return out, errors
