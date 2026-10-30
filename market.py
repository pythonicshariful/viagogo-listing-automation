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
# Prices written with an ISO code AFTER the number, e.g. the structured
# lines search engines show for Viagogo events: "Tickets: 1,265.69 USD",
# "Tickets: 1283 USD". The old parser only saw a symbol BEFORE the
# number, so a whole page of these prices was invisible to it (proven
# 2026-10-28: the FC Barcelona artist page returns all-None). A bare
# year ("2026 USD") is NOT a price — see parse_suffix_prices().
_CURRENCY_CODES = {
    "USD", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD", "SEK", "NOK", "DKK",
    "PLN", "CZK", "HUF", "JPY", "INR", "AED", "SAR", "QAR", "KWD", "BHD",
    "OMR", "TRY", "BRL", "MXN", "ZAR",
}
_SUFFIX_PRICE_RE = re.compile(
    r"([\d,]+(?:\.\d{1,2})?)\s*(USD|EUR|GBP|AUD|CAD|CHF|NZD|SEK|NOK|DKK|"
    r"PLN|CZK|HUF|JPY|INR|AED|SAR|QAR|KWD|BHD|OMR|TRY|BRL|MXN|ZAR)\b")
_TICKETS_PRICE_RE = re.compile(
    r"tickets?\s*:\s*([\d,]+(?:\.\d{1,2})?)\s*(USD|EUR|GBP|AUD|CAD|CHF|NZD|"
    r"SEK|NOK|DKK|PLN|CZK|HUF|JPY|INR|AED|SAR|QAR|KWD|BHD|OMR|TRY|BRL|MXN|ZAR)\b", re.I)
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


def _safe_name(value: str) -> str:
    """A filesystem-safe slug for screenshot filenames."""
    return re.sub(r"[^A-Za-z0-9]+", "-", str(value or "event")).strip("-")[:40] or "event"


def _challenge_kind_from_message(message: str) -> str:
    """'Bot challenge detected (datadome) at ...' -> 'datadome'."""
    m = re.search(r"challenge detected \((\w+)\)", message or "", re.I)
    return m.group(1).lower() if m else "challenge"


def _plain_error_line(exc: Exception | None) -> str:
    """First line of an exception, capped — for diagnostics, never a traceback."""
    if exc is None:
        return "unknown load error"
    first = str(exc).strip().splitlines()
    return (first[0][:300] if first else type(exc).__name__)


def parse_prices(text: str) -> list[float]:
    """All currency amounts found in page text, as floats, in order."""
    out: list[float] = []
    for m in _PRICE_RE.finditer(text or ""):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    out.extend(value for value, _code in parse_suffix_prices(text or ""))
    return out


def parse_suffix_prices(text: str) -> list[tuple[float, str]]:
    """Prices written as an amount + ISO code, e.g. "Tickets: 1,265.69 USD".

    Only real-looking prices are returned: the number must have a
    decimal part or a thousands comma (1,265.69 / 172.51), OR be
    introduced by "Tickets:" (1283 USD). A bare year ("2026 USD") is
    never a price. Order is the order on the page.
    """
    out: list[tuple[float, str]] = []
    for m in _SUFFIX_PRICE_RE.finditer(text or ""):
        raw = m.group(1)
        code = m.group(2)
        # "Tickets:" in the ~20 chars before the number -> any amount counts.
        before = (text or "")[max(0, m.start() - 20):m.start()].lower()
        looks_like_price = ("." in raw or "," in raw or "ticket" in before)
        if not looks_like_price:
            continue
        try:
            out.append((float(raw.replace(",", "")), code))
        except ValueError:
            continue
    return out


def parse_tickets_price(text: str) -> tuple[float | None, str | None]:
    """The cheapest "Tickets: N USD" line on the page, if any."""
    tickets_lines = []
    for m in _TICKETS_PRICE_RE.finditer(text or ""):
        try:
            tickets_lines.append((float(m.group(1).replace(",", "")), m.group(2)))
        except ValueError:
            continue
    if tickets_lines:
        return min(tickets_lines, key=lambda pair: pair[0])
    return None, None


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


_EVENTS_COUNT_RE = re.compile(r"(\d[\d,]*)\s+events?\s+in\s+", re.I)


def detect_page_kind(text: str) -> dict:
    """What kind of Viagogo page is this text from?

    Artist pages list MANY events ("39 events in all locations",
    "38 events in USA") — their prices, if any, are per-event "From"
    prices across all of them, not one event's prices. A page with no
    such marker is "unknown" (it may be a single-event page, or a page
    that did not load properly — see is_empty_page()).

    Returns {"kind": "artist"|"unknown", "events_count": int|None}.
    """
    m = _EVENTS_COUNT_RE.search(text or "")
    if m:
        try:
            return {"kind": "artist", "events_count": int(m.group(1).replace(",", ""))}
        except ValueError:
            return {"kind": "artist", "events_count": None}
    return {"kind": "unknown", "events_count": None}


def is_empty_page(text: str, title: str = "") -> bool:
    """True when the browser clearly did not get a real Viagogo page:
    almost no readable text, or no mention of Viagogo at all. A
    challenge/blank/redirect page looks exactly like this — it must be
    reported as a failure, never parsed as a market page with no prices."""
    body = (text or "").strip()
    if len(body) < 200:
        return True
    return "viagogo" not in (title or "").lower() and "viagogo" not in body.lower()


def looks_like_artist_page_url(url: str) -> bool:
    """URL-shape hint only: the path ends with "-Tickets" (e.g.
    .../Metallica-Tickets, .../FC-Barcelona-Tickets). A performer page
    can also end in /E-<digits>, which this does NOT catch — the
    runtime check (detect_page_kind) is the real test. Used for a
    warning at paste time, never as a block on its own."""
    from urllib.parse import urlparse

    try:
        path = urlparse(str(url or "")).path.rstrip("/")
    except Exception:
        return False
    return path.lower().endswith("-tickets")


def parse_snapshot_text(text: str, event: dict) -> dict:
    """Turn raw page text into a snapshot dict. Missing values stay None.

    Real-page rules (see LIVE_VERIFICATION.md for the pages these were
    observed on):
    - lowest_price is the page's headline 'From $X' price when the page
      shows one (that IS Viagogo's cheapest listing); otherwise the
      lowest currency amount on the page — including amounts written
      as "Tickets: 1,265.69 USD" (amount + ISO code, no symbol).
    - currency comes from the page itself ($/£/€ or USD/EUR/GBP),
      falling back to the event's currency — never assume GBP.
    - demand signals are Viagogo's own words ('Only 1% of tickets
      left', 'Selling fast', 'Top seller'), kept verbatim as tags.
    - page_kind says whether the text came from an artist page (many
      events) — its prices are per-event "From" prices, not one
      event's prices. page_note explains that in plain words when the
      page has no prices at all.
    """
    prices = parse_prices(text or "")
    # Filter out absurd values (e.g. years, fees text) — ticket prices only.
    prices = [p for p in prices if 1 <= p <= 100000]
    from_price, from_currency = parse_from_price(text or "")
    tickets_price, tickets_currency = parse_tickets_price(text or "")
    # Lowest = cheapest amount actually on the page, from any of the
    # formats Viagogo uses ("From $463", "Tickets: 172.51 USD", "$860").
    # On an artist page that is the cheapest event listed; on a
    # single-event page it is that event's cheapest listing. The
    # headline "From" price is listed first so it wins ties.
    candidates: list[tuple[float, str | None]] = []
    if from_price is not None:
        candidates.append((from_price, from_currency))
    if tickets_price is not None:
        candidates.append((tickets_price, tickets_currency))
    for value, code in parse_suffix_prices(text or ""):
        candidates.append((value, code))
    for value in prices:
        candidates.append((value, from_currency or parse_currency(text or "")))
    candidates = [(v, c) for v, c in candidates if 1 <= v <= 100000]
    lowest, page_currency = (min(candidates, key=lambda pair: pair[0])
                             if candidates else (None, None))
    if page_currency is None:
        page_currency = parse_currency(text or "")
    kind = detect_page_kind(text or "")
    page_note = ""
    if kind["kind"] == "artist" and lowest is None:
        page_note = (
            f"This page lists {kind['events_count'] or 'many'} events — it is an "
            "artist page, not one event, and it shows no prices. Paste the single "
            "event page URL to get live prices for one event.")
    elif kind["kind"] == "artist":
        page_note = (
            f"This page lists {kind['events_count'] or 'many'} events — it is an "
            "artist page. These are per-event 'From' prices across all of them, "
            "not one event's prices.")
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
        "page_kind": kind["kind"],
        "events_count": kind["events_count"],
        "page_note": page_note,
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


class BrowserLaunchError(RuntimeError):
    """The live browser could not be started, with an actionable remedy."""


def launch_browser(playwright, launch: dict):
    """Launch Playwright Chromium with local-browser fallbacks."""
    errors = []
    try:
        return playwright.chromium.launch(**launch)
    except Exception as exc:
        errors.append(f"bundled Chromium: {type(exc).__name__}: {exc}")
    for channel in ("chrome", "msedge"):
        try:
            fallback = dict(launch)
            fallback["channel"] = channel
            return playwright.chromium.launch(**fallback)
        except Exception as exc:
            errors.append(f"{channel}: {type(exc).__name__}: {exc}")
    raise BrowserLaunchError(
        "No usable browser could be launched. Install Playwright Chromium with "
        "`python -m playwright install chromium` (or run `run.bat install-browser`), "
        f"then retry. Details: {errors[-1][:240]}")


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

    def _read_page(self, page, url: str, screenshot_path=None) -> tuple[str, dict]:
        """Load one URL in an already-open page and read its text.

        Waits for the React content to render (body text grows, then one
        scroll to trigger lazy-loaded lists), checks for a challenge
        AFTER the wait as well as before it (a DataDome interstitial can
        appear late), and reports what the browser actually saw.
        Returns (text, diag) — diag has title, final URL, HTTP status,
        text length, a 500-char excerpt, the challenge kind (if any),
        and the screenshot path. Never returns silently on a page that
        is empty or a challenge: those raise / are reported by the caller.
        """
        started = time.time()
        diag: dict = {"url": url, "final_url": url, "title": "",
                      "http_status": None, "text_chars": 0, "text_excerpt": "",
                      "challenge": None, "screenshot": None, "elapsed_s": 0.0}
        resp = page.goto(url, wait_until="domcontentloaded",
                         timeout=self.page_timeout_ms)
        diag["http_status"] = resp.status if resp else None
        check_challenge_or_solve(page, self._captcha_solver)
        # Let the React event list render: wait until the body has real
        # text, then scroll once (lazy-loaded lists) and wait again.
        try:
            page.wait_for_function(
                "() => document.body && document.body.innerText.length > 500",
                timeout=15000)
        except Exception:
            pass  # keep going — the excerpt below shows what loaded
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass
        time.sleep(random.uniform(1.0, 2.0))
        # A challenge can appear AFTER the first check — check again.
        check_challenge_or_solve(page, self._captcha_solver)
        try:
            diag["title"] = page.title()
        except Exception:
            diag["title"] = ""
        diag["final_url"] = page.url
        text = page.inner_text("body")
        diag["text_chars"] = len(text)
        diag["text_excerpt"] = text[:500]
        if screenshot_path:
            try:
                page.screenshot(path=str(screenshot_path))
                diag["screenshot"] = str(screenshot_path)
            except Exception as exc:
                logger.debug("live-check screenshot failed: %s", exc)
        diag["elapsed_s"] = round(time.time() - started, 1)
        return text, diag

    def collect_with_diagnostics(self, event: dict, screenshot_dir=None,
                                 headed: bool | None = None) -> tuple[dict, dict]:
        """One event -> (snapshot, diagnostics).

        The snapshot is exactly what collect() returns. Diagnostics say
        WHAT the browser saw — page title, final URL, HTTP status, text
        length, a 500-char excerpt, challenge kind, screenshot path, and
        a plain-English reason when nothing was found — so a failed live
        check can be debugged from the evidence instead of guessed at.
        headed=True shows the browser window on screen (the manual
        check); None keeps the monitor's own headless setting (the
        background collector stays headless).

        A page that loads but has almost no readable text is source
        "live-empty", NOT "live" with all-None: a challenge page, a
        blank page and a redirect all look like that, and silently
        parsing them as a market page was the 2026-10-28 failure.
        """
        from playwright.sync_api import sync_playwright

        url = event.get("event_url") or ""
        headless = self.headless if headed is None else (not headed)
        diag: dict = {"event_name": event.get("event_name"), "event_url": url,
                      "final_url": url, "title": "", "http_status": None,
                      "text_chars": 0, "text_excerpt": "", "challenge": None,
                      "screenshot": None, "reason": "", "phase": "browser-launch",
                      "elapsed_s": 0.0}
        shot = None
        if screenshot_dir:
            shot = (Path(screenshot_dir) /
                    f"live-{_safe_name(str(event.get('event_name') or 'event'))}"
                    f"-{int(time.time())}.png")
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with sync_playwright() as pw:
                    launch = {"headless": headless}
                    if self.proxy:
                        launch["proxy"] = {"server": self.proxy}
                    browser = launch_browser(pw, launch)
                    try:
                        context = new_stealth_context(
                            browser, locale=self._stealth_locale,
                            timezone_id=self._stealth_timezone,
                            enabled=self._stealth_enabled)
                        page = context.new_page()
                        page.set_default_timeout(self.page_timeout_ms)
                        text, page_diag = self._read_page(page, url, screenshot_path=shot)
                        diag.update(page_diag)
                        diag["phase"] = "parse"
                    finally:
                        browser.close()
                if is_empty_page(text, diag.get("title", "")):
                    diag["reason"] = (
                        "The page loaded but contained almost no readable text "
                        f"({diag['text_chars']} chars) — it may be a bot-check page, "
                        "a blank page, or a redirect. See the screenshot / excerpt.")
                    diag["phase"] = "parse"
                    if attempt < MAX_ATTEMPTS:
                        time.sleep(2 ** attempt)
                        continue
                    snap = parse_snapshot_text("", event)
                    snap["source"] = "live-empty"
                    return snap, diag
                snap = parse_snapshot_text(text, event)
                diag["phase"] = "ok" if snap.get("lowest_price") is not None else "parse"
                self.log.append(f"live snapshot: {snap['event_name']} lowest={snap.get('lowest_price')}")
                return snap, diag
            except ChallengeDetectedError as exc:
                kind = _challenge_kind_from_message(str(exc))
                diag["challenge"] = kind
                diag["phase"] = "challenge"
                diag["reason"] = (f"Viagogo showed a {kind} challenge page — the bot "
                                  "stopped instead of solving it.")
                logger.error("market collect STOPPED for %s: %s", url, exc)
                self.log.append(f"live snapshot BLOCKED by challenge: {event.get('event_name')} — stopped, not solved")
                empty = parse_snapshot_text("", event)
                empty["source"] = "live-challenge"
                return empty, diag
            except Exception as exc:  # noqa: BLE001 — live pages fail often; record and retry/empty
                last_exc = exc
                if isinstance(exc, BrowserLaunchError):
                    diag["phase"] = "browser-launch"
                logger.warning("market collect attempt %d/%d failed for %s: %s",
                               attempt, MAX_ATTEMPTS, url, exc)
                time.sleep(2 ** attempt)
        diag["reason"] = _plain_error_line(last_exc) if last_exc else "unknown load error"
        if diag.get("phase") != "browser-launch":
            diag["phase"] = "navigation"
        logger.error("market collect failed for %s: %s", url, last_exc)
        empty = parse_snapshot_text("", event)
        empty["source"] = "live-failed"
        return empty, diag

    def collect_event_via_artist(self, artist_event: dict, event_link_text: str,
                                 screenshot_dir=None,
                                 headed: bool | None = None) -> tuple[dict, dict]:
        """Open an ARTIST page, click one event, parse the SINGLE-EVENT page.

        Artist pages list many events and often show NO prices at all
        (Real Madrid / FC Barcelona artist pages, verified 2026-10-28),
        so a live check must land on one event's own page to get that
        event's prices. Returns (snapshot, diagnostics) — the snapshot's
        event_url is the single-event page the browser actually landed
        on. If no link for the event is found, the snapshot is
        "live-failed" with a plain reason (never a silent all-None).
        """
        from playwright.sync_api import sync_playwright

        artist_url = artist_event.get("event_url") or ""
        headless = self.headless if headed is None else (not headed)
        diag: dict = {"event_name": artist_event.get("event_name"),
                      "event_url": artist_url, "artist_url": artist_url,
                      "clicked_link": None, "final_url": artist_url, "title": "",
                      "http_status": None, "text_chars": 0, "text_excerpt": "",
                      "challenge": None, "screenshot": None, "reason": "",
                      "elapsed_s": 0.0}
        started = time.time()
        try:
            with sync_playwright() as pw:
                launch = {"headless": headless}
                if self.proxy:
                    launch["proxy"] = {"server": self.proxy}
                browser = launch_browser(pw, launch)
                try:
                    context = new_stealth_context(
                        browser, locale=self._stealth_locale,
                        timezone_id=self._stealth_timezone,
                        enabled=self._stealth_enabled)
                    page = context.new_page()
                    page.set_default_timeout(self.page_timeout_ms)
                    shot = None
                    if screenshot_dir:
                        shot = (Path(screenshot_dir) /
                                f"live-artist-{_safe_name(str(artist_event.get('event_name') or 'event'))}"
                                f"-{int(time.time())}.png")
                    text, page_diag = self._read_page(page, artist_url, screenshot_path=shot)
                    diag.update(page_diag)
                    if is_empty_page(text, diag.get("title", "")):
                        diag["reason"] = ("The artist page loaded but contained almost no "
                                          f"readable text ({diag['text_chars']} chars) — it may "
                                          "be a bot-check, a blank page, or a redirect.")
                        snap = parse_snapshot_text("", artist_event)
                        snap["source"] = "live-empty"
                        return snap, diag
                    link = self._find_event_link(page, event_link_text)
                    if link is None:
                        diag["reason"] = (f"Could not find a link for '{event_link_text}' on "
                                          "the artist page — the page may have changed, or the "
                                          "event list did not render. See the screenshot.")
                        snap = parse_snapshot_text(text, artist_event)
                        snap["source"] = "live-failed"
                        return snap, diag
                    diag["clicked_link"] = event_link_text
                    link.click()
                    page.wait_for_load_state("domcontentloaded")
                    shot2 = None
                    if screenshot_dir:
                        shot2 = (Path(screenshot_dir) /
                                 f"live-event-{_safe_name(event_link_text)}-{int(time.time())}.png")
                    event = dict(artist_event)
                    event["event_name"] = f"{artist_event.get('event_name')} — {event_link_text}"
                    text2, page_diag2 = self._read_page(page, page.url, screenshot_path=shot2)
                    diag.update(page_diag2)
                    diag["artist_url"] = artist_url
                    diag["clicked_link"] = event_link_text
                    if is_empty_page(text2, diag.get("title", "")):
                        diag["reason"] = ("The single-event page loaded but contained almost "
                                          f"no readable text ({diag['text_chars']} chars).")
                        snap = parse_snapshot_text("", event)
                        snap["source"] = "live-empty"
                        return snap, diag
                    event["event_url"] = page.url
                    snap = parse_snapshot_text(text2, event)
                    self.log.append(f"live snapshot (via artist page): {snap['event_name']} lowest={snap.get('lowest_price')}")
                    return snap, diag
                finally:
                    browser.close()
        except ChallengeDetectedError as exc:
            diag["challenge"] = _challenge_kind_from_message(str(exc))
            diag["phase"] = "challenge"
            diag["reason"] = (f"Viagogo showed a {diag['challenge']} challenge page — "
                              "the bot stopped instead of solving it.")
            empty = parse_snapshot_text("", artist_event)
            empty["source"] = "live-challenge"
            return empty, diag
        except Exception as exc:  # noqa: BLE001 — report, never crash the caller
            diag["reason"] = _plain_error_line(exc)
            diag["phase"] = "browser-launch" if isinstance(exc, BrowserLaunchError) else "navigation"
            diag["elapsed_s"] = round(time.time() - started, 1)
            empty = parse_snapshot_text("", artist_event)
            empty["source"] = "live-failed"
            return empty, diag

    @staticmethod
    def _find_event_link(page, event_link_text: str):
        """First link whose accessible name contains the event text.
        Tries role-based lookup, then any anchor containing the text.
        Returns a locator or None."""
        import re as _re

        pattern = _re.compile(_re.escape(event_link_text), _re.I)
        try:
            loc = page.get_by_role("link", name=pattern)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
        try:
            loc = page.locator("a", has_text=pattern)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
        return None

    def _collect_live(self, event: dict) -> dict:
        """Live public-page scrape. One page, retries, then give up with
        an empty snapshot rather than raising into the scan.

        A CAPTCHA / Cloudflare / DataDome challenge is NOT retried: with
        no NopeCHA key the run stops for that event with source
        "live-challenge". With NopeCHA enabled + configured, ONE solve
        is attempted for that page (see captcha.py); if it fails, the
        event is still recorded as "live-challenge". A page that loads
        but has almost no readable text is source "live-empty" — it is
        reported as a failure, never parsed as a market page.
        Diagnostics live in collect_with_diagnostics(); this keeps the
        old no-diagnostics return shape for the collector / scan path."""
        snap, _diag = self.collect_with_diagnostics(event)
        return snap

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
            if self.scan_live() and snap.get("source") in {"live-challenge", "live-failed", "live-empty"}:
                if snap["source"] == "live-challenge":
                    reason = ("Viagogo showed a CAPTCHA / Cloudflare / DataDome challenge — "
                              "the bot stopped instead of solving it")
                elif snap["source"] == "live-empty":
                    reason = ("The page loaded but had almost no readable text — it may be a "
                              "bot-check page, a blank page, or a redirect. Run the dashboard "
                              "live check to see the screenshot and the exact page text.")
                else:
                    reason = ("The live page could not be loaded after 2 attempts — "
                              "see logs/app.log for the exact error")
                errors.append({
                    "event_name": event.get("event_name"),
                    "event_url": event.get("event_url"),
                    "source": snap["source"],
                    "reason": reason,
                    "page_note": snap.get("page_note", ""),
                })
        return out, errors
