"""Dashboard settings (v1.3.0) — everything controllable from the UI.

The end user is non-technical, so NO .env file is needed: the app runs
with sensible defaults and every setting below lives in the SQLite
config (one JSON object under the config key "settings"). Environment
variables still exist ONLY as an optional override for advanced users —
the app must never *require* one.

Validation lives here (pure functions, no Flask, no DB) so it is
unit-testable. The web app (app.py) reads/writes the stored object and
passes the effective values into the bot / scanner / stealth helpers.

Never store or return secrets in full here: the proxy URL is only ever
shown back masked, and the session file is never read into a response.
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Allowed values — dropdowns in the UI, not free text, where avoidable.
# ---------------------------------------------------------------------------
LOCALES = ["en-US", "en-GB", "de-DE", "fr-FR", "es-ES", "it-IT", "nl-NL"]
TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Los_Angeles",
    "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Amsterdam",
    "Asia/Dhaka", "Asia/Kolkata", "Australia/Sydney", "UTC",
]
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

# Defaults for every setting. The app starts with exactly these when
# the database has no saved settings yet — zero config files needed.
SETTINGS_DEFAULTS: dict = {
    # 1. Mode — "dry" is the safe default; "live" posts real listings.
    "mode": "dry",
    # 2. Seller session file name (relative to the app folder).
    "session_file": "auth_state.json",
    # 3. Scanner.
    "scan_live": False,
    "scan_delay_s": 5.0,
    "page_timeout_ms": 60000,
    "headless": True,
    # 4. Proxy ("" = none).
    "proxy_url": "",
    # 5. Stealth.
    "stealth_enabled": True,
    "stealth_locale": "en-US",
    "stealth_timezone": "America/New_York",
    # 6. Seller fee % used by the Opportunity Scanner profit math.
    "fee_pct": 10.0,
    # 7. Server — applied on next restart (see docs).
    "host": "127.0.0.1",
    "port": 5002,
    "log_level": "INFO",
}

# Which settings keys live in the DB object (anything else is rejected).
KNOWN_KEYS = set(SETTINGS_DEFAULTS)
# Keys whose change needs an app restart to take effect.
RESTART_KEYS = {"host", "port", "log_level"}


def defaults() -> dict:
    """A fresh copy of the defaults."""
    return dict(SETTINGS_DEFAULTS)


def merge_settings(saved: dict | None) -> dict:
    """Saved DB object + defaults for any missing key (never mutates input)."""
    merged = defaults()
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in KNOWN_KEYS:
                merged[key] = value
    return merged


def validate_settings(data: dict) -> tuple[dict, list[str]]:
    """Validate a partial settings update.

    Returns (cleaned_values, errors). `cleaned` contains only the keys
    that were present in `data` and passed validation, already coerced
    to the right types. Unknown keys are errors (typos fail loudly).
    """
    cleaned: dict = {}
    errors: list[str] = []
    if not isinstance(data, dict):
        return {}, ["settings must be a JSON object"]

    for key in data:
        if key not in KNOWN_KEYS:
            errors.append(f"unknown setting: {key}")

    if "mode" in data:
        mode = data["mode"]
        if mode not in {"dry", "live"}:
            errors.append("mode must be 'dry' or 'live'")
        else:
            cleaned["mode"] = mode

    if "session_file" in data:
        name = data["session_file"]
        if not isinstance(name, str) or not name.strip():
            errors.append("session_file must be a non-empty file name")
        elif "/" in name.replace("\\", "/") or ".." in name:
            errors.append("session_file must be a plain file name, not a path")
        elif not name.strip().endswith(".json"):
            errors.append("session_file must end in .json")
        else:
            cleaned["session_file"] = name.strip()

    if "scan_live" in data:
        if not isinstance(data["scan_live"], bool):
            errors.append("scan_live must be true or false")
        else:
            cleaned["scan_live"] = data["scan_live"]

    if "scan_delay_s" in data:
        try:
            delay = float(data["scan_delay_s"])
            if not 0 <= delay <= 30:
                errors.append("scan_delay_s must be between 0 and 30 seconds")
            else:
                cleaned["scan_delay_s"] = delay
        except (TypeError, ValueError):
            errors.append("scan_delay_s must be a number")

    if "page_timeout_ms" in data:
        try:
            timeout = int(data["page_timeout_ms"])
            if not 5000 <= timeout <= 300000:
                errors.append("page_timeout_ms must be between 5000 and 300000")
            else:
                cleaned["page_timeout_ms"] = timeout
        except (TypeError, ValueError):
            errors.append("page_timeout_ms must be an integer")

    if "headless" in data:
        if not isinstance(data["headless"], bool):
            errors.append("headless must be true or false")
        else:
            cleaned["headless"] = data["headless"]

    if "proxy_url" in data:
        proxy = data["proxy_url"]
        if proxy in (None, ""):
            cleaned["proxy_url"] = ""
        elif not isinstance(proxy, str):
            errors.append("proxy_url must be a string")
        else:
            parsed = urllib.parse.urlparse(proxy.strip())
            if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
                errors.append("proxy_url must look like http://host:port or http://user:pass@host:port")
            else:
                cleaned["proxy_url"] = proxy.strip()

    if "stealth_enabled" in data:
        if not isinstance(data["stealth_enabled"], bool):
            errors.append("stealth_enabled must be true or false")
        else:
            cleaned["stealth_enabled"] = data["stealth_enabled"]

    if "stealth_locale" in data:
        if data["stealth_locale"] not in LOCALES:
            errors.append(f"stealth_locale must be one of: {', '.join(LOCALES)}")
        else:
            cleaned["stealth_locale"] = data["stealth_locale"]

    if "stealth_timezone" in data:
        if data["stealth_timezone"] not in TIMEZONES:
            errors.append(f"stealth_timezone must be one of: {', '.join(TIMEZONES)}")
        else:
            cleaned["stealth_timezone"] = data["stealth_timezone"]

    if "fee_pct" in data:
        try:
            fee = float(data["fee_pct"])
            if not 0 <= fee <= 100:
                errors.append("fee_pct must be between 0 and 100")
            else:
                cleaned["fee_pct"] = fee
        except (TypeError, ValueError):
            errors.append("fee_pct must be a number")

    if "host" in data:
        host = data["host"]
        if not isinstance(host, str) or not host.strip():
            errors.append("host must be a non-empty string")
        elif not re.match(r"^(0\.0\.0\.0|127\.0\.0\.1|localhost|[a-zA-Z0-9.-]+)$", host.strip()):
            errors.append("host must be a hostname or IP address")
        else:
            cleaned["host"] = host.strip()

    if "port" in data:
        try:
            port = int(data["port"])
            if not 1 <= port <= 65535:
                errors.append("port must be between 1 and 65535")
            else:
                cleaned["port"] = port
        except (TypeError, ValueError):
            errors.append("port must be an integer")

    if "log_level" in data:
        if data["log_level"] not in LOG_LEVELS:
            errors.append(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
        else:
            cleaned["log_level"] = data["log_level"]

    return cleaned, errors


# ---------------------------------------------------------------------------
# Session file validation — a Playwright storage_state JSON object.
# The contents are NEVER returned or logged; only presence/shape is checked.
# ---------------------------------------------------------------------------
MAX_SESSION_BYTES = 5 * 1024 * 1024  # 5 MB is far more than a real session


def validate_storage_state(raw: bytes) -> tuple[dict | None, str | None]:
    """Parse + validate uploaded session bytes.

    Returns (parsed_dict, None) on success or (None, error_message).
    A real Playwright storage_state has "cookies" (list) and/or
    "origins" (list). Anything else is rejected — it is not a session.
    """
    if len(raw) > MAX_SESSION_BYTES:
        return None, f"session file is too large (max {MAX_SESSION_BYTES // 1024 // 1024} MB)"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None, "session file is not valid JSON"
    if not isinstance(data, dict):
        return None, "session file must be a JSON object (Playwright storage_state)"
    cookies = data.get("cookies")
    origins = data.get("origins")
    if not isinstance(cookies, list) and not isinstance(origins, list):
        return None, ("session file does not look like a Playwright storage_state — "
                      "it needs a 'cookies' or 'origins' list")
    if isinstance(cookies, list) and cookies and not isinstance(cookies[0], dict):
        return None, "session file 'cookies' must be a list of objects"
    return data, None


# ---------------------------------------------------------------------------
# Proxy helpers — credentials are never logged; only a masked form is shown.
# ---------------------------------------------------------------------------
def mask_proxy(url: str) -> str:
    """http://user:pass@host:port -> http://user:***@host:port. No password ever."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@")
            return urllib.parse.urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        return "***"
    return url


def probe_proxy(proxy_url: str, target: str = "https://example.com",
                timeout: int = 10) -> dict:
    """Quick check: can we reach a public page through this proxy?

    Returns {"ok": bool, "status": int|None, "seconds": float, "error": str|None}.
    The proxy URL (with any credentials) is never logged by this function.
    """
    import time

    parsed = urllib.parse.urlparse(proxy_url)
    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(target, headers={"User-Agent": "ViagogoBot-proxy-test/1.0"},
                                     method="HEAD")
    started = time.time()
    try:
        with opener.open(request, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status,
                    "seconds": round(time.time() - started, 2), "error": None}
    except Exception as exc:  # noqa: BLE001 — report, never raise, never log the URL
        return {"ok": False, "status": None,
                "seconds": round(time.time() - started, 2),
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
