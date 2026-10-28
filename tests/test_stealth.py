"""Stealth helper tests — no live site, no Viagogo, no credentials.

Covers: UA / viewport pools (+ env override), init-script contents,
challenge detection on sample HTML (including the real mock portal,
which must NOT trip it), jitter bounds, the STEALTH_ENABLED switch,
and — when Chromium is installed — that a real stealth context actually
hides navigator.webdriver in the browser.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stealth
from stealth import (
    STEALTH_INIT_SCRIPT,
    ChallengeDetectedError,
    check_challenge_or_raise,
    detect_challenge_text,
    jitter_seconds,
    pick_user_agent,
    pick_viewport,
    stealth_context_kwargs,
    stealth_enabled,
    user_agent_pool,
    viewport_pool,
)

BASE = Path(__file__).resolve().parents[1]


# -- pools ---------------------------------------------------------------

def test_ua_pool_is_desktop_chrome_only():
    pool = user_agent_pool()
    assert len(pool) >= 3, pool
    assert len(set(pool)) == len(pool)  # no duplicates
    for ua in pool:
        assert ua.startswith("Mozilla/5.0"), ua
        assert "Chrome/" in ua, ua
        assert "Mobile" not in ua and "Android" not in ua, ua  # desktop only


def test_ua_pool_env_override(monkeypatch):
    monkeypatch.setenv("STEALTH_USER_AGENTS",
                       "Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0.0.0, CustomUA/1.0")
    pool = user_agent_pool()
    assert pool == ["Mozilla/5.0 (X11; Linux x86_64) Chrome/141.0.0.0", "CustomUA/1.0"]
    assert pick_user_agent() in pool


def test_viewport_pool_is_desktop_sized():
    pool = viewport_pool()
    assert len(pool) >= 3, pool
    for vp in pool:
        assert 1024 <= vp["width"] <= 2560, vp
        assert 600 <= vp["height"] <= 1440, vp


def test_picks_stay_inside_pools():
    # Seeded RNG: picks must always come from the pools, never invented.
    import random
    rng = random.Random(42)
    for _ in range(50):
        assert pick_user_agent(rng) in user_agent_pool()
        assert pick_viewport(rng) in viewport_pool()


# -- init script ----------------------------------------------------------

def test_init_script_hides_automation_tells():
    for tell in ("webdriver", "chrome", "permissions", "plugins", "languages"):
        assert tell in STEALTH_INIT_SCRIPT, tell
    # It must NOT claim to defeat Cloudflare, and must not touch network.
    assert "Cloudflare" not in STEALTH_INIT_SCRIPT
    assert "fetch" not in STEALTH_INIT_SCRIPT
    assert "XMLHttpRequest" not in STEALTH_INIT_SCRIPT


# -- stealth switch / context kwargs --------------------------------------

def test_stealth_enabled_by_default(monkeypatch):
    monkeypatch.delenv("STEALTH_ENABLED", raising=False)
    assert stealth_enabled() is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_stealth_can_be_disabled(monkeypatch, value):
    monkeypatch.setenv("STEALTH_ENABLED", value)
    assert stealth_enabled() is False
    assert stealth_context_kwargs() == {}


def test_context_kwargs_are_consistent(monkeypatch):
    monkeypatch.delenv("STEALTH_ENABLED", raising=False)
    monkeypatch.setenv("STEALTH_LOCALE", "en-GB")
    monkeypatch.setenv("STEALTH_TIMEZONE", "Europe/London")
    kwargs = stealth_context_kwargs()
    assert kwargs["user_agent"] in user_agent_pool()
    assert kwargs["viewport"] in viewport_pool()
    assert kwargs["locale"] == "en-GB"
    assert kwargs["timezone_id"] == "Europe/London"


def test_context_kwargs_defaults_match_seller_store(monkeypatch):
    monkeypatch.delenv("STEALTH_ENABLED", raising=False)
    monkeypatch.delenv("STEALTH_LOCALE", raising=False)
    monkeypatch.delenv("STEALTH_TIMEZONE", raising=False)
    kwargs = stealth_context_kwargs()
    assert kwargs["locale"] == "en-US"
    assert kwargs["timezone_id"] == "America/New_York"


# -- challenge detection ---------------------------------------------------

CLOUDFLARE_HTML = ("Just a moment...", "<html><body><h1>Just a moment...</h1>"
                    "<p>Checking your browser before accessing viagogo.com. "
                    "This process is automatic. Cloudflare Ray ID: abc.</p></body></html>")

CAPTCHA_HTML = ("Verify you are human", "<html><body><p>Please verify you are "
                "human by completing the captcha below.</p></body></html>")

NORMAL_HTML = ("Metallica - 2 Day Pass | viagogo", "<html><body><h1>Metallica</h1>"
               "<p>Tickets from $860. 152 people are currently searching.</p></body></html>")


def test_detect_challenge_cloudflare():
    assert detect_challenge_text(*CLOUDFLARE_HTML) == "cloudflare"


def test_detect_challenge_captcha():
    assert detect_challenge_text(*CAPTCHA_HTML) == "captcha"


def test_detect_challenge_attention_required_title():
    assert detect_challenge_text("Attention Required! | Cloudflare",
                                 "One more step to continue") == "cloudflare"


def test_detect_challenge_normal_page_is_clean():
    assert detect_challenge_text(*NORMAL_HTML) is None
    assert detect_challenge_text("", "") is None


def test_detect_challenge_mock_portal_is_clean():
    # The fake seller portal must never trip the challenge detector —
    # otherwise the mock-portal browser test would break.
    html = (BASE / "mock" / "mock_seller_portal.html").read_text(encoding="utf-8")
    assert detect_challenge_text("Mock Seller Portal", html) is None


def test_check_challenge_raises_on_challenge_page():
    class FakePage:
        url = "https://sell.viagogo.com/selltickets"

        def title(self):
            return CLOUDFLARE_HTML[0]

        def inner_text(self, _selector):
            return CLOUDFLARE_HTML[1]

    with pytest.raises(ChallengeDetectedError, match="challenge"):
        check_challenge_or_raise(FakePage())


def test_check_challenge_passes_on_normal_page():
    class FakePage:
        url = "https://sell.viagogo.com/selltickets"

        def title(self):
            return NORMAL_HTML[0]

        def inner_text(self, _selector):
            return NORMAL_HTML[1]

    check_challenge_or_raise(FakePage())  # must not raise


def test_bot_never_retries_a_challenge():
    # _retry must re-raise ChallengeDetectedError immediately (no 3x retry).
    from viagogo_bot import _retry

    calls = []

    def _boom():
        calls.append(1)
        raise ChallengeDetectedError("challenge")

    with pytest.raises(ChallengeDetectedError):
        _retry(_boom, "challenge test")
    assert len(calls) == 1  # tried once, not 3 times


# -- jitter -----------------------------------------------------------------

def test_jitter_seconds_stays_in_bounds():
    for _ in range(200):
        v = jitter_seconds(0.1, 0.5)
        assert 0.1 <= v <= 0.5
    for _ in range(50):
        v = jitter_seconds(0.03, 0.12)
        assert 0.03 <= v <= 0.12


def test_type_char_delay_range_is_small():
    lo, hi = stealth.TYPE_CHAR_DELAY
    assert 0 < lo <= hi <= 0.5  # per-character: quick, not a full pause


# -- real browser: init script actually hides webdriver ---------------------

def test_stealth_context_hides_webdriver_in_real_chromium():
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = stealth.new_stealth_context(browser)
                page = context.new_page()
                page.goto("about:blank")
                assert page.evaluate("navigator.webdriver") is None
                assert page.evaluate("typeof window.chrome") == "object"
                assert page.evaluate("navigator.plugins.length") == 3
                assert page.evaluate("navigator.languages[0]") == "en-US"
                # The context really got the randomised UA + viewport.
                assert "Chrome/" in page.evaluate("navigator.userAgent")
                assert page.evaluate("window.innerWidth") in {v["width"] for v in viewport_pool()}
            finally:
                browser.close()
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
            pytest.skip("Chromium is not installed — run: python -m playwright install chromium")
        raise


# -- secret hygiene: typed values must never reach the logs -----------------

class _FailingTyper:
    """Fake locator: per-character typing raises, .fill() works."""

    def __init__(self):
        self.filled = None

    def click(self, timeout=None):
        return None

    def fill(self, value, timeout=None):
        self.filled = value
        return None

    def press_sequentially(self, ch, delay=None, timeout=None):
        raise RuntimeError("typing failed (test)")


def test_type_like_human_fallback_never_logs_the_typed_value(caplog):
    import logging

    import stealth

    loc = _FailingTyper()
    secret = "seller-secret-paypal@example.com"
    with caplog.at_level(logging.WARNING, logger="viagogo-listing-automation.stealth"):
        stealth.type_like_human(loc, secret)
    assert loc.filled == secret  # fallback still types the value
    assert secret not in caplog.text
    assert "seller" not in caplog.text
    assert "example.com" not in caplog.text
