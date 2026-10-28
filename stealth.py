"""Stealth / anti-detection hardening for the Viagogo browser flows.

Shared by viagogo_bot.py (seller portal) and market.py (public market
monitor). Everything here is *reduction of obvious automation tells* —
randomised desktop user-agent / viewport, a locale + timezone matching
the seller store, an init script that hides the usual Playwright
fingerprints, and human-like per-action jitter (character-by-character
typing, small mouse moves before clicks).

HONEST LIMITS — read before relying on this:
- This does NOT defeat Cloudflare or any serious bot-detection system.
  It only removes the most obvious tells. Viagogo can still detect,
  rate-limit or block automated access at any time, and a determined
  challenge (Cloudflare "Just a moment", CAPTCHA, "Verify you are human")
  will still appear.
- By default this module NEVER bypasses, solves, clicks through, or
  waits out a CAPTCHA or Cloudflare challenge. If one is detected, the
  bot STOPS: detect_challenge() / check_challenge_or_raise() raise
  ChallengeDetectedError and the caller must abort the run and log it.
- OPTIONAL NopeCHA path (v1.2.2, captcha.py): only when the operator
  explicitly enables it AND configures their own NopeCHA API key does
  check_challenge_or_solve() attempt ONE solve per challenge page
  (Token API for reCAPTCHA/Turnstile, Recognition as a fallback).
  Solving a CAPTCHA to bypass anti-bot controls may violate Viagogo's
  terms and increases account-ban risk; NopeCHA does not guarantee a
  solve, and a Cloudflare interstitial (no sitekey) cannot be solved
  by the Token API at all. With no key configured, behaviour is
  exactly the old stop-on-challenge behaviour.
- No stealth plugin (e.g. playwright-stealth) is used: the init script
  below is plain Playwright add_init_script, so there is no extra
  dependency and nothing to keep in sync with Playwright versions.
- Randomisation is per browser launch (one UA + one viewport per
  session), not per page — rotating the fingerprint mid-session would
  look *more* suspicious, not less.

Configuration (all env, all optional):
  STEALTH_ENABLED        "true" (default) / "false" — disable all of it.
  STEALTH_USER_AGENTS    comma-separated UA strings overriding the pool.
  STEALTH_LOCALE         default "en-US" (seller store locale).
  STEALTH_TIMEZONE       default "America/New_York" (seller store tz).
"""
from __future__ import annotations

import logging
import os
import random
import time

logger = logging.getLogger("viagogo-listing-automation.stealth")

# ---------------------------------------------------------------------------
# Pools — small, current, desktop-only. Mobile UAs are NOT in the pool:
# the seller portal is used from a desktop browser, and a mobile UA on a
# desktop viewport would be an obvious mismatch.
# ---------------------------------------------------------------------------
USER_AGENTS = [
    # Chrome on Windows 10/11 (current as of Oct 2026).
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    # Chrome on macOS.
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1280, "height": 720},
]

DEFAULT_LOCALE = "en-US"
DEFAULT_TIMEZONE = "America/New_York"

# Per-character typing delay (seconds) for type_like_human().
TYPE_CHAR_DELAY = (0.03, 0.12)


def stealth_enabled() -> bool:
    """STEALTH_ENABLED=True by default; set to "false"/"0"/"no" to disable."""
    return os.environ.get("STEALTH_ENABLED", "True").strip().lower() not in {
        "false", "0", "no", "off",
    }


def user_agent_pool() -> list[str]:
    """The UA pool, or STEALTH_USER_AGENTS (comma-separated) if set."""
    override = os.environ.get("STEALTH_USER_AGENTS", "").strip()
    if override:
        pool = [ua.strip() for ua in override.split(",") if ua.strip()]
        if pool:
            return pool
    return list(USER_AGENTS)


def viewport_pool() -> list[dict]:
    return [dict(v) for v in VIEWPORTS]


def pick_user_agent(rng: random.Random | None = None) -> str:
    return (rng or random).choice(user_agent_pool())


def pick_viewport(rng: random.Random | None = None) -> dict:
    return (rng or random).choice(viewport_pool())


def stealth_locale() -> str:
    return os.environ.get("STEALTH_LOCALE", DEFAULT_LOCALE).strip() or DEFAULT_LOCALE


def stealth_timezone() -> str:
    return os.environ.get("STEALTH_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE


# ---------------------------------------------------------------------------
# Init script — hides the usual automation tells. Runs via Playwright's
# add_init_script, i.e. before any page script runs. It does NOT touch
# network traffic, does NOT solve challenges, and does NOT hide the fact
# that the browser is automated from a serious detector — it only removes
# the low-hanging tells (navigator.webdriver, missing window.chrome,
# headless permissions behaviour, empty plugins, headless languages).
# ---------------------------------------------------------------------------
STEALTH_INIT_SCRIPT = """
(() => {
  // 1. navigator.webdriver — the single most-checked automation tell.
  try {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  } catch (e) {}

  // 2. window.chrome — present in real Chrome, missing in headless.
  try {
    if (!window.chrome) {
      window.chrome = { runtime: {} };
    } else if (!window.chrome.runtime) {
      window.chrome.runtime = {};
    }
  } catch (e) {}

  // 3. Permissions — headless Chromium answers 'prompt' for everything;
  //    a real desktop browser usually has notifications denied/granted.
  try {
    const origQuery = window.navigator.permissions.query.bind(window.navigator.permissions);
    window.navigator.permissions.query = (parameters) => {
      if (parameters && parameters.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission });
      }
      return origQuery(parameters);
    };
  } catch (e) {}

  // 4. Plugins — headless Chromium reports an empty list; real desktop
  //    Chrome ships a few built-in plugins (e.g. PDF viewer).
  try {
    const fakePlugins = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ];
    Object.defineProperty(navigator, 'plugins', { get: () => fakePlugins });
  } catch (e) {}

  // 5. Languages — headless defaults to a single entry; match the locale.
  try {
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  } catch (e) {}
})();
"""


def stealth_context_kwargs(rng: random.Random | None = None) -> dict:
    """kwargs for browser.new_context() when stealth is on, else {}.

    One UA + one viewport per context (per launch). The locale/timezone
    match the seller store (en-US / America/New_York by default) so the
    fingerprint is internally consistent.
    """
    if not stealth_enabled():
        return {}
    return {
        "user_agent": pick_user_agent(rng),
        "viewport": pick_viewport(rng),
        "locale": stealth_locale(),
        "timezone_id": stealth_timezone(),
    }


def new_stealth_context(browser, storage_state: str | None = None, rng: random.Random | None = None):
    """Create a browser context with stealth settings + init script.

    Proxy is configured at browser launch (not here), so it keeps working
    with stealth on. storage_state is the saved login session, if any.
    """
    kwargs = stealth_context_kwargs(rng)
    if storage_state:
        kwargs["storage_state"] = storage_state
    context = browser.new_context(**kwargs)
    if stealth_enabled():
        context.add_init_script(STEALTH_INIT_SCRIPT)
        logger.info("stealth: context UA=%s viewport=%s locale=%s tz=%s",
                    kwargs.get("user_agent"), kwargs.get("viewport"),
                    kwargs.get("locale"), kwargs.get("timezone_id"))
    return context


# ---------------------------------------------------------------------------
# Challenge detection — the bot NEVER bypasses a challenge. If one of
# these markers is on the page, the run stops immediately.
# ---------------------------------------------------------------------------
CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "attention required",
    "verify you are human",
    "checking your browser",
    "please verify",
    "are you a robot",
)

CHALLENGE_TEXT_MARKERS = (
    "cloudflare",
    "verify you are human",
    "checking your browser",
    "are you a robot",
    "please complete the security check",
    "unusual traffic",
    "captcha",
    "hcaptcha",
    "recaptcha",
)


class ChallengeDetectedError(RuntimeError):
    """Raised when a CAPTCHA / Cloudflare challenge page is detected.

    The bot must stop, log this clearly, and return the error — never
    attempt to solve, click through, or wait out the challenge.
    """


def detect_challenge_text(title: str, text: str) -> str | None:
    """Pure check over a page title + body text.

    Returns a short label ("cloudflare" / "captcha" / "challenge") when a
    challenge marker is found, else None. Kept pure (no browser) so it
    is unit-testable on sample HTML.
    """
    title_l = (title or "").lower()
    text_l = (text or "").lower()
    # Body text first: it names the challenge type (Cloudflare / CAPTCHA).
    for marker in CHALLENGE_TEXT_MARKERS:
        if marker in text_l:
            if "cloudflare" in text_l or marker == "cloudflare":
                return "cloudflare"
            if "captcha" in marker or "captcha" in text_l:
                return "captcha"
            return "challenge"
    for marker in CHALLENGE_TITLE_MARKERS:
        if marker in title_l:
            if "cloudflare" in title_l or "cloudflare" in text_l or "just a moment" in title_l:
                return "cloudflare"
            return "challenge"
    return None


def detect_challenge(page) -> str | None:
    """detect_challenge_text() over a live Playwright page. None = clean."""
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        text = page.inner_text("body")
    except Exception:
        text = ""
    return detect_challenge_text(title, text)


def check_challenge_or_raise(page) -> None:
    """Raise ChallengeDetectedError if the page is a challenge page."""
    kind = detect_challenge(page)
    if kind:
        logger.error("CHALLENGE DETECTED (%s) at %s — stopping, never solving it",
                     kind, getattr(page, "url", "?"))
        raise ChallengeDetectedError(
            f"Bot challenge detected ({kind}) at {getattr(page, 'url', '?')} — "
            "the bot stopped instead of solving it. If this was a one-off, "
            "wait and retry later by hand; do not automate around it.")


def check_challenge_or_solve(page, solver=None) -> bool:
    """Challenge gate used by the bot and the scanner.

    Returns False when the page is clean. When a challenge IS detected:
    if `solver` is a configured + enabled NopeCHA solver (captcha.py),
    attempt ONE solve for this page; return True only when it reports
    solved. Otherwise — no solver, solver disabled, no key, solve
    failed, or a challenge with no sitekey — raise
    ChallengeDetectedError exactly as check_challenge_or_raise() does.
    Never retries a page: the solver itself refuses a second attempt
    on the same page object.
    """
    kind = detect_challenge(page)
    if not kind:
        return False
    if solver is not None:
        result = solver.attempt_page_solve(page, kind=kind)
        if result.get("solved"):
            logger.info("CHALLENGE (%s) solved via NopeCHA (%s) at %s — continuing",
                        kind, result.get("type"), getattr(page, "url", "?"))
            return True
        logger.warning("CHALLENGE (%s) at %s could not be solved via NopeCHA: %s — stopping",
                       kind, getattr(page, "url", "?"),
                       result.get("error") or result.get("reason") or "unknown")
    raise ChallengeDetectedError(
        f"Bot challenge detected ({kind}) at {getattr(page, 'url', '?')} — "
        "the bot stopped instead of solving it. If this was a one-off, "
        "wait and retry later by hand; do not automate around it.")


# ---------------------------------------------------------------------------
# Per-action jitter — small human-like irregularity on top of the existing
# human_delay() pauses. These helpers never change WHAT is clicked or
# typed, only HOW: typing is character-by-character, clicks are preceded
# by a small random mouse move. Both fall back to the plain Playwright
# action if anything about the jitter fails.
# ---------------------------------------------------------------------------
def jitter_seconds(a: float = 0.1, b: float = 0.5) -> float:
    """One random jitter value in [a, b] seconds (pure, testable)."""
    return random.uniform(a, b)


def jitter_delay(a: float = 0.1, b: float = 0.5) -> None:
    time.sleep(jitter_seconds(a, b))


def type_like_human(locator, text: str, timeout: int = 15000) -> None:
    """Type text character-by-character with small random delays.

    Only for plain text fields where that is safe (search box, price
    fields). The field is clicked, cleared, then typed one character at
    a time — the same end value as .fill(), just less machine-regular.
    Falls back to .fill() if per-character typing fails.
    """
    text = str(text)
    try:
        locator.click(timeout=timeout)
        locator.fill("", timeout=timeout)  # clear any prefilled value
        for ch in text:
            locator.press_sequentially(ch, delay=int(random.uniform(*TYPE_CHAR_DELAY) * 1000),
                                       timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — fall back, never lose the action
        logger.warning("type_like_human fell back to fill() for %r: %s", text[:20], exc)
        locator.fill(text, timeout=timeout)


def click_like_human(page, locator, timeout: int = 15000) -> None:
    """Move the mouse a little before clicking, like a human would.

    Moves to a random point inside the element's bounding box (a few
    steps, with a short pause), then clicks the locator normally. Falls
    back to a plain click if the box cannot be read or the move fails.
    """
    try:
        box = locator.first.bounding_box(timeout=timeout)
        if box:
            x = box["x"] + random.uniform(0.15, 0.85) * box["width"]
            y = box["y"] + random.uniform(0.15, 0.85) * box["height"]
            page.mouse.move(x, y, steps=random.randint(2, 6))
            jitter_delay(0.05, 0.25)
    except Exception as exc:  # noqa: BLE001 — mouse move is cosmetic only
        logger.debug("click_like_human mouse move skipped: %s", exc)
    locator.first.click(timeout=timeout)
