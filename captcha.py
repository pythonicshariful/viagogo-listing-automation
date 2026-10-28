"""NopeCHA CAPTCHA-solving support (optional, v1.2.2).

The bot works WITHOUT this: when no NopeCHA key is configured, every
solve call returns a clear "not configured" result and the bot falls
back to its existing behaviour — it STOPS on a challenge and logs it
(see stealth.check_challenge_or_raise). Nothing here is required to
run the listing bot or the Opportunity Scanner.

When the operator DOES configure a key (paste it in the dashboard
Settings, or set NOPECHA_API_KEY in .env), the bot may attempt ONE
solve per challenge page, and only then: Token API first for
reCAPTCHA v2/v3 and Cloudflare Turnstile (sitekey + page URL -> token),
Recognition API as a fallback for image/audio challenges (returns
click positions / text for the browser to apply). The official
`nopecha` Python package is used when installed; the code works with
it NOT installed and reports that clearly instead of crashing.

HONEST LIMITS — read before enabling this:
- Solving a CAPTCHA to bypass anti-bot controls may violate Viagogo's
  terms of service and INCREASES the risk of the seller account being
  flagged, rate-limited or suspended. NopeCHA does not guarantee a
  solve: challenges can fail, time out, or return a token Viagogo
  rejects. The operator (not the bot) decides whether to enable this,
  and the key + subscription are theirs to pay for (free tier: 100
  recognitions/day; Starter $4.99/month — see README § NopeCHA).
- A Cloudflare "Just a moment…" interstitial has NO sitekey, so the
  Token API cannot solve it — the bot still stops on those pages.
- The key is NEVER logged (only the first 4 characters + "***"), and a
  returned token is NEVER logged either. The key lives in .env
  (NOPECHA_API_KEY, checked first) or in the SQLite config
  (`nopecha_api_key`, set from the dashboard); it is never written to
  any other file and never appears in an API response in full.
- Max 2 attempts per solve call, max 1 solve attempt per challenge
  page (enforced: a second attempt on the same page is refused).
  No auto-retry loops, no CAPTCHA farming.
"""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger("viagogo-listing-automation.captcha")

STATUS_URL = "https://api.nopecha.com/v1/status"
STATUS_TIMEOUT = 10
SOLVE_TIMEOUT = 120  # a NopeCHA solve can take a while; the API polls internally
MAX_ATTEMPTS = 2

# Challenge types the Token API supports, in the order we prefer them
# when a page somehow shows more than one widget.
TOKEN_TYPES = ("turnstile", "recaptcha_v2", "recaptcha_v3", "hcaptcha")


def mask_key(key: str | None) -> str:
    """First 4 chars + '***' — the only form a key ever takes in a log
    or an API response. Empty/None -> ''."""
    if not key:
        return ""
    key = str(key)
    return (key[:4] + "***") if len(key) > 4 else "****"


def get_api_key(db_key: str | None = None) -> str:
    """Effective key: NOPECHA_API_KEY from the environment first, then
    the key saved in the dashboard (SQLite config). '' = none configured."""
    env_key = (os.environ.get("NOPECHA_API_KEY") or "").strip()
    if env_key:
        return env_key
    return (db_key or "").strip()


def captcha_enabled(db_enabled: bool | None = None) -> bool:
    """Effective toggle: NOPECHA_ENABLED in the environment wins if set,
    otherwise the dashboard toggle, otherwise False (off by default —
    solving must be an explicit operator choice, never a silent default)."""
    env = os.environ.get("NOPECHA_ENABLED")
    if env is not None:
        return env.strip().lower() in {"true", "1", "yes", "on"}
    return bool(db_enabled)


def _load_official_client(api_key: str):
    """Build the official `nopecha` package client, or return None with
    a clear log line when the package is not installed. Lazy import so
    the whole app works without the optional dependency."""
    try:
        from nopecha.api.requests import RequestsAPIClient
    except ImportError:
        logger.warning("NopeCHA requested but the 'nopecha' package is not "
                       "installed — run: pip install nopecha (see README § NopeCHA)")
        return None
    return RequestsAPIClient(api_key)


def _extract_token(result) -> str | None:
    """A Token API result may be a dict {'data': token}, an object with
    a .data attribute, or a bare string. Anything else -> None."""
    if isinstance(result, str):
        return result or None
    if isinstance(result, dict):
        token = result.get("data")
        return str(token) if token else None
    token = getattr(result, "data", None)
    return str(token) if token else None


# JavaScript run in the page: find every widget with a sitekey, and say
# what type it is. Turnstile first — it is the one Viagogo-adjacent
# pages actually show; hCaptcha last (NopeCHA discontinued its hCaptcha
# token endpoint in Oct 2026, so it may answer 410 — handled as a
# normal solve failure, never retried more than once).
SITEKEY_JS = """() => {
  const out = [];
  document.querySelectorAll('[data-sitekey]').forEach(el => {
    let type = 'recaptcha_v2';
    const cls = (el.className || '').toString();
    if (cls.includes('cf-turnstile') || (el.id || '').includes('turnstile')) type = 'turnstile';
    else if (cls.includes('h-captcha')) type = 'hcaptcha';
    else if (cls.includes('g-recaptcha')) type = 'recaptcha_v2';
    out.push({type: type, sitekey: el.getAttribute('data-sitekey')});
  });
  return out;
}"""

# JavaScript run in the page: put a solved token into the hidden
# response field the site's own form reads, and fire input/change so
# React-style handlers notice. Returns true when a field was found.
INJECT_TOKEN_JS = """(token, kind) => {
  let sel = 'textarea[name="g-recaptcha-response"]';
  if (kind === 'turnstile') sel = 'input[name="cf-turnstile-response"]';
  else if (kind === 'hcaptcha') sel = 'textarea[name="h-captcha-response"]';
  let el = document.querySelector(sel);
  if (!el) el = document.querySelector('textarea[name="g-recaptcha-response"]');
  if (!el) return false;
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, token);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}"""


class NopechaSolver:
    """Optional NopeCHA client. Safe to construct with no key: every
    method then returns a clear 'not configured' result instead of
    raising, so callers can fall back to stop-on-challenge behaviour.

    `client` is an injectable duck-typed client (used by the tests) with
    the same methods as the official RequestsAPIClient
    (solve_recaptcha_v2/v3, solve_cloudflare_turnstile, solve_hcaptcha,
    recognize_recaptcha, recognize_hcaptcha). When it is None, the
    official package is loaded lazily on first use.
    """

    def __init__(self, api_key: str | None = None, enabled: bool = False,
                 client=None, timeout: int = SOLVE_TIMEOUT):
        self.api_key = (api_key or "").strip()
        self.enabled = bool(enabled)
        self._client = client  # injected (tests) or None (lazy official)
        self._client_tried = client is not None
        self.timeout = timeout
        self._attempted_pages: set[int] = set()
        if self.api_key:
            logger.info("NopeCHA solver initialised (key %s, enabled=%s)",
                        mask_key(self.api_key), self.enabled)

    # -- state --------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def ready(self) -> bool:
        """Usable for a solve: explicitly enabled AND a key configured."""
        return self.enabled and self.configured

    @property
    def masked_key(self) -> str:
        return mask_key(self.api_key)

    def _require_ready(self) -> dict | None:
        """None when ready; otherwise the 'not usable' result dict."""
        if not self.enabled:
            return {"ok": False, "error": "NopeCHA is disabled — enable it in "
                    "Settings (CAPTCHA Solver) or set NOPECHA_ENABLED=true"}
        if not self.configured:
            return {"ok": False, "configured": False, "error": "NopeCHA API key "
                    "not configured — paste it in Settings (CAPTCHA Solver) or "
                    "set NOPECHA_API_KEY in .env"}
        return None

    def _client_or_none(self):
        if not self._client_tried:
            self._client_tried = True
            self._client = _load_official_client(self.api_key)
        return self._client

    # -- status ---------------------------------------------------------------
    def status(self) -> dict:
        """GET https://api.nopecha.com/v1/status with the key. Returns only
        whitelisted fields (plan / credit / quota / …) — never the key.
        No key -> 'not configured' (no HTTP call at all)."""
        if not self.configured:
            return {"ok": False, "configured": False,
                    "error": "NopeCHA API key not configured"}
        try:
            resp = requests.get(STATUS_URL, params={"key": self.api_key},
                                timeout=STATUS_TIMEOUT)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
        except Exception as exc:  # noqa: BLE001 — network/API failure is data
            logger.warning("NopeCHA status check failed: %s", exc)
            return {"ok": False, "configured": True,
                    "error": f"NopeCHA status check failed: {exc}"}
        if not isinstance(data, dict):
            return {"ok": False, "configured": True,
                    "error": "NopeCHA status returned an unexpected response"}
        out = {"ok": True, "configured": True}
        for field in ("plan", "status", "credit", "quota", "duration",
                      "ttl", "subscribed"):
            if field in data:
                out[field] = data[field]
        logger.info("NopeCHA status ok (key %s): %s",
                    mask_key(self.api_key), {k: v for k, v in out.items() if k != "ok"})
        return out

    # -- Token API ------------------------------------------------------------
    def solve_token(self, challenge_type: str, sitekey: str, url: str,
                    action: str | None = None) -> dict:
        """Solve one challenge via the Token API: sitekey + page URL ->
        token string. Max 2 attempts, then a clear error. Returns
        {"ok", "method": "token", "type", "token"} on success — the
        token itself is returned to the caller (to inject into the page)
        and is NEVER logged."""
        blocked = self._require_ready()
        if blocked:
            return {**blocked, "method": "token", "type": challenge_type}
        if challenge_type not in TOKEN_TYPES:
            return {"ok": False, "method": "token", "type": challenge_type,
                    "error": f"unsupported challenge type {challenge_type!r} — "
                             f"supported: {', '.join(TOKEN_TYPES)}"}
        if not sitekey or not url:
            return {"ok": False, "method": "token", "type": challenge_type,
                    "error": "sitekey and page URL are required for a Token solve"}
        client = self._client_or_none()
        if client is None:
            return {"ok": False, "method": "token", "type": challenge_type,
                    "error": "NopeCHA package not installed — run: pip install nopecha"}
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if challenge_type == "recaptcha_v2":
                    result = client.solve_recaptcha_v2(sitekey, url)
                elif challenge_type == "recaptcha_v3":
                    result = client.solve_recaptcha_v3(sitekey, url, action=action)
                elif challenge_type == "turnstile":
                    result = client.solve_cloudflare_turnstile(sitekey, url)
                else:  # hcaptcha
                    result = client.solve_hcaptcha(sitekey, url)
                token = _extract_token(result)
                if not token:
                    raise RuntimeError("NopeCHA returned an empty token")
                logger.info("NopeCHA Token solve succeeded (%s, attempt %d/%d)",
                            challenge_type, attempt, MAX_ATTEMPTS)
                return {"ok": True, "method": "token", "type": challenge_type,
                        "token": token}
            except Exception as exc:  # noqa: BLE001 — API/quota failure is data
                last_exc = exc
                logger.warning("NopeCHA Token solve failed (%s, attempt %d/%d): %s",
                               challenge_type, attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(2 ** attempt)
        msg = str(last_exc) if last_exc else "unknown error"
        if any(word in msg.lower() for word in ("quota", "balance", "credit", "insufficient", "410", "discontinued")):
            msg = f"quota/balance problem — {msg} (check the NopeCHA plan / balance in Settings)"
        return {"ok": False, "method": "token", "type": challenge_type,
                "error": f"NopeCHA Token solve failed after {MAX_ATTEMPTS} attempts: {msg}"}

    # -- Recognition API ------------------------------------------------------
    def solve_recognition(self, challenge_type: str, task: str,
                          images: list | None = None) -> dict:
        """Solve an image/audio challenge: task text + image URLs/data ->
        click positions / text for the browser to apply. Max 2 attempts."""
        blocked = self._require_ready()
        if blocked:
            return {**blocked, "method": "recognition", "type": challenge_type}
        if challenge_type not in ("recaptcha", "hcaptcha"):
            return {"ok": False, "method": "recognition", "type": challenge_type,
                    "error": "Recognition supports 'recaptcha' and 'hcaptcha' only"}
        if not task or not images:
            return {"ok": False, "method": "recognition", "type": challenge_type,
                    "error": "task text and images are required for a Recognition solve"}
        client = self._client_or_none()
        if client is None:
            return {"ok": False, "method": "recognition", "type": challenge_type,
                    "error": "NopeCHA package not installed — run: pip install nopecha"}
        last_exc: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if challenge_type == "recaptcha":
                    result = client.recognize_recaptcha(task, images)
                else:
                    result = client.recognize_hcaptcha(task, images)
                logger.info("NopeCHA Recognition solve succeeded (%s, attempt %d/%d)",
                            challenge_type, attempt, MAX_ATTEMPTS)
                return {"ok": True, "method": "recognition", "type": challenge_type,
                        "result": result}
            except Exception as exc:  # noqa: BLE001 — API/quota failure is data
                last_exc = exc
                logger.warning("NopeCHA Recognition solve failed (%s, attempt %d/%d): %s",
                               challenge_type, attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(2 ** attempt)
        return {"ok": False, "method": "recognition", "type": challenge_type,
                "error": f"NopeCHA Recognition solve failed after {MAX_ATTEMPTS} attempts: {last_exc}"}

    # -- one attempt per challenge page ---------------------------------------
    def attempt_page_solve(self, page, kind: str | None = None) -> dict:
        """Try ONCE to solve the challenge on a Playwright page.

        Returns {"ok": True, "solved": True, "method", "type"} when a
        token was obtained AND injected into the page, {"ok": True,
        "solved": False, "reason": "no challenge"} when the page is
        clean, and {"ok": False, "solved": False, "error": ...} when it
        could not be solved. A second call for the SAME page object is
        refused ("already attempted once") — never auto-retry a page.

        A challenge with no sitekey (e.g. a Cloudflare "Just a moment…"
        interstitial) cannot be solved by the Token API and returns an
        error instead of guessing.
        """
        if id(page) in self._attempted_pages:
            return {"ok": False, "solved": False,
                    "error": "already attempted once for this page — not retrying"}
        self._attempted_pages.add(id(page))
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            text = page.inner_text("body")
        except Exception:
            text = ""
        from stealth import detect_challenge_text
        found = kind or detect_challenge_text(title, text)
        if not found:
            return {"ok": True, "solved": False, "reason": "no challenge on this page"}
        blocked = self._require_ready()
        if blocked:
            return {**blocked, "solved": False}
        try:
            widgets = page.evaluate(SITEKEY_JS)
        except Exception as exc:  # noqa: BLE001 — page may be gone; treat as failure
            return {"ok": False, "solved": False,
                    "error": f"could not read the challenge widget from the page: {exc}"}
        widget = None
        for preferred in TOKEN_TYPES:
            widget = next((w for w in (widgets or []) if w.get("type") == preferred), None)
            if widget:
                break
        if not widget or not widget.get("sitekey"):
            return {"ok": False, "solved": False,
                    "error": "challenge has no sitekey (e.g. Cloudflare interstitial) — "
                             "the Token API cannot solve it; stop and retry by hand later"}
        url = getattr(page, "url", "") or ""
        solved = self.solve_token(widget["type"], widget["sitekey"], url)
        if not solved.get("ok"):
            return {**solved, "solved": False}
        try:
            injected = page.evaluate(INJECT_TOKEN_JS, solved["token"], widget["type"])
        except Exception as exc:  # noqa: BLE001 — injection failure is a solve failure
            return {"ok": False, "solved": False,
                    "error": f"token obtained but could not be injected into the page: {exc}"}
        if not injected:
            return {"ok": False, "solved": False,
                    "error": "token obtained but the page has no response field to put it in"}
        logger.info("NopeCHA solved a %s challenge on %s (token injected, not logged)",
                    widget["type"], url)
        return {"ok": True, "solved": True, "method": "token", "type": widget["type"]}

    def mock_solve(self) -> dict:
        """Test button: a MOCK solve that makes NO real API call. Used by
        the dashboard test button to prove the wiring without spending
        credits. Returns 'not configured' when no key is set."""
        if not self.configured:
            return {"ok": False, "configured": False, "mock": True,
                    "error": "NopeCHA API key not configured — paste it in "
                             "Settings (CAPTCHA Solver) first"}
        return {"ok": True, "mock": True, "configured": True, "method": "token",
                "type": "recaptcha_v2", "masked_key": self.masked_key,
                "note": "Mock solve only — no real NopeCHA API call was made. "
                        "Use 'Check status' to verify a real key."}


def solver_from_env(client=None) -> NopechaSolver:
    """Solver from the environment only (bot / scanner processes)."""
    return NopechaSolver(api_key=os.environ.get("NOPECHA_API_KEY", ""),
                         enabled=captcha_enabled(False), client=client)


def solver_from_config(db_enabled: bool | None, db_key: str | None,
                       client=None) -> NopechaSolver:
    """Solver for the web app: key from env first, then the dashboard
    (SQLite config); toggle from env override, else the dashboard."""
    return NopechaSolver(api_key=get_api_key(db_key),
                         enabled=captcha_enabled(db_enabled), client=client)
