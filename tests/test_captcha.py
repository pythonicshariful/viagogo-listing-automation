"""NopeCHA CAPTCHA solver tests — all mock/offline.

No real NopeCHA API key, no network, no Viagogo. A fake client stands
in for the official `nopecha` package, and a fake page stands in for
a Playwright page. Covers: no-key / disabled behaviour, masked
logging, Token + Recognition solves with a fake client, quota-error
handling, package-not-installed, page-solve flow (one attempt per
page, no-sitekey challenge), mock solve, and the dashboard config
endpoints (key saved, returned only masked).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import captcha
from captcha import NopechaSolver, get_api_key, mask_key
from stealth import ChallengeDetectedError, check_challenge_or_solve


class FakeClient:
    """Duck-typed stand-in for nopecha.api.requests.RequestsAPIClient."""

    def __init__(self, fail_with: Exception | None = None):
        self.calls: list[tuple] = []
        self.fail_with = fail_with

    def _maybe_fail(self, name, *args):
        self.calls.append((name,) + args)
        if self.fail_with is not None:
            raise self.fail_with
        return {"data": "TOKEN-ABC-123"}

    def solve_recaptcha_v2(self, sitekey, url, **kw):
        return self._maybe_fail("recaptcha_v2", sitekey, url)

    def solve_recaptcha_v3(self, sitekey, url, **kw):
        return self._maybe_fail("recaptcha_v3", sitekey, url)

    def solve_cloudflare_turnstile(self, sitekey, url, **kw):
        return self._maybe_fail("turnstile", sitekey, url)

    def solve_hcaptcha(self, sitekey, url, **kw):
        return self._maybe_fail("hcaptcha", sitekey, url)

    def recognize_recaptcha(self, task, images):
        self.calls.append(("recognize_recaptcha", task, tuple(images)))
        if self.fail_with is not None:
            raise self.fail_with
        return [True, False, True]

    def recognize_hcaptcha(self, task, images):
        self.calls.append(("recognize_hcaptcha", task, tuple(images)))
        if self.fail_with is not None:
            raise self.fail_with
        return [False, True]

    def status(self):
        return {"plan": "free", "credit": 42, "quota": 100}


class FakePage:
    """Minimal Playwright page stand-in for attempt_page_solve()."""

    def __init__(self, title="Viagogo", body="Sell your tickets", widgets=None,
                 url="https://sell.viagogo.com/selltickets"):
        self._title = title
        self._body = body
        self.widgets = widgets or []
        self.url = url
        self.evaluate_calls: list[tuple] = []
        self.injected: tuple | None = None

    def title(self):
        return self._title

    def inner_text(self, selector):
        return self._body

    def evaluate(self, js, *args):
        self.evaluate_calls.append((js, args))
        if "data-sitekey" in js:
            return [dict(w) for w in self.widgets]
        if "g-recaptcha-response" in js:
            self.injected = args  # (token, kind)
            return True
        return None


# -- masking / config -------------------------------------------------------

def test_mask_key():
    assert mask_key("abcd12345678") == "abcd***"
    assert mask_key("") == ""
    assert mask_key(None) == ""
    assert mask_key("ab") == "****"


def test_get_api_key_env_first(monkeypatch):
    monkeypatch.setenv("NOPECHA_API_KEY", "env-key-123")
    assert get_api_key("db-key-456") == "env-key-123"
    monkeypatch.delenv("NOPECHA_API_KEY")
    assert get_api_key("db-key-456") == "db-key-456"
    assert get_api_key(None) == ""
    assert get_api_key("  ") == ""


def test_captcha_enabled_env_override(monkeypatch):
    monkeypatch.setenv("NOPECHA_ENABLED", "true")
    assert captcha.captcha_enabled(False) is True
    monkeypatch.setenv("NOPECHA_ENABLED", "false")
    assert captcha.captcha_enabled(True) is False
    monkeypatch.delenv("NOPECHA_ENABLED")
    assert captcha.captcha_enabled(True) is True
    assert captcha.captcha_enabled(None) is False
    assert captcha.captcha_enabled(False) is False


# -- not configured / disabled ----------------------------------------------

def test_solve_token_no_key_never_calls_client():
    client = FakeClient()
    solver = NopechaSolver(api_key="", enabled=True, client=client)
    assert solver.configured is False
    result = solver.solve_token("recaptcha_v2", "sitekey-1", "https://example.com/")
    assert result["ok"] is False
    assert "not configured" in result["error"]
    assert client.calls == []


def test_solve_token_disabled_with_key_never_calls_client():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=False, client=client)
    result = solver.solve_token("recaptcha_v2", "sitekey-1", "https://example.com/")
    assert result["ok"] is False
    assert "disabled" in result["error"]
    assert client.calls == []


def test_solve_token_unsupported_type():
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=FakeClient())
    result = solver.solve_token("geetest", "sk", "https://example.com/")
    assert result["ok"] is False
    assert "unsupported" in result["error"]


# -- Token + Recognition with a fake client ---------------------------------

def test_solve_token_recaptcha_v2_fake_client():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    result = solver.solve_token("recaptcha_v2", "sitekey-1", "https://example.com/login")
    assert result == {"ok": True, "method": "token", "type": "recaptcha_v2",
                      "token": "TOKEN-ABC-123"}
    assert client.calls == [("recaptcha_v2", "sitekey-1", "https://example.com/login")]
    assert "TOKEN-ABC-123" not in str(solver.__dict__)  # token never stored


def test_solve_token_turnstile_uses_turnstile_method():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    result = solver.solve_token("turnstile", "sitekey-2", "https://example.com/")
    assert result["ok"] is True and result["type"] == "turnstile"
    assert client.calls[0][0] == "turnstile"


def test_solve_recognition_fake_client():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    result = solver.solve_recognition("recaptcha", "click each image with a cat",
                                      ["https://example.com/1.png"])
    assert result["ok"] is True
    assert result["method"] == "recognition"
    assert result["result"] == [True, False, True]


def test_solve_recognition_unsupported_type():
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=FakeClient())
    result = solver.solve_recognition("turnstile", "task", ["https://example.com/1.png"])
    assert result["ok"] is False


# -- failure handling ---------------------------------------------------------

def test_solve_token_quota_error_retries_twice_then_reports_quota():
    client = FakeClient(fail_with=Exception("quota exceeded for today"))
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    result = solver.solve_token("recaptcha_v2", "sitekey-1", "https://example.com/")
    assert result["ok"] is False
    assert "quota" in result["error"].lower()
    assert len(client.calls) == 2  # MAX_ATTEMPTS = 2, then it stops


def test_solve_token_package_not_installed(monkeypatch):
    monkeypatch.setattr(captcha, "_load_official_client", lambda key: None)
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=None)
    result = solver.solve_token("recaptcha_v2", "sitekey-1", "https://example.com/")
    assert result["ok"] is False
    assert "not installed" in result["error"]


def test_status_no_key_makes_no_http_call(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("no HTTP call should happen without a key")

    monkeypatch.setattr(captcha.requests, "get", _boom)
    solver = NopechaSolver(api_key="", enabled=True)
    result = solver.status()
    assert result == {"ok": False, "configured": False,
                      "error": "NopeCHA API key not configured"}


def test_status_returns_whitelisted_fields_only(monkeypatch):
    class Resp:
        content = b'{"plan": "starter", "credit": 7, "quota": 2000}'
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"plan": "starter", "credit": 7, "quota": 2000,
                    "duration": 30, "ttl": 5, "subscribed": True,
                    "secret": "should-not-leak"}

    monkeypatch.setattr(captcha.requests, "get", lambda *a, **k: Resp())
    solver = NopechaSolver(api_key="key-12345678", enabled=True)
    result = solver.status()
    assert result["ok"] is True
    assert result["plan"] == "starter" and result["credit"] == 7
    assert "secret" not in result and "key-12345678" not in str(result)


# -- one attempt per challenge page -------------------------------------------

def _challenge_page():
    return FakePage(
        title="Just a moment...",
        body="Cloudflare — Verify you are human. Please complete the security check.",
        widgets=[{"type": "turnstile", "sitekey": "turnstile-key-1"}],
        url="https://sell.viagogo.com/selltickets")


def test_attempt_page_solve_clean_page_does_nothing():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    page = FakePage(title="Viagogo", body="Sell your tickets")
    result = solver.attempt_page_solve(page)
    assert result == {"ok": True, "solved": False, "reason": "no challenge on this page"}
    assert client.calls == []


def test_attempt_page_solve_turnstile_injects_token():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    page = _challenge_page()
    result = solver.attempt_page_solve(page)
    assert result["ok"] is True and result["solved"] is True
    assert result["method"] == "token" and result["type"] == "turnstile"
    assert client.calls[0][0] == "turnstile"
    assert page.injected == ("TOKEN-ABC-123", "turnstile")


def test_attempt_page_solve_second_attempt_on_same_page_refused():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    page = _challenge_page()
    assert solver.attempt_page_solve(page)["solved"] is True
    calls_after_first = len(client.calls)
    result = solver.attempt_page_solve(page)
    assert result["ok"] is False
    assert "already attempted" in result["error"]
    assert len(client.calls) == calls_after_first  # no second solve call


def test_attempt_page_solve_no_sitekey_cannot_solve():
    client = FakeClient()
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=client)
    page = FakePage(title="Just a moment...",
                    body="Cloudflare — checking your browser before accessing the site.",
                    widgets=[])  # interstitial: no widget, no sitekey
    result = solver.attempt_page_solve(page)
    assert result["ok"] is False
    assert "no sitekey" in result["error"]
    assert client.calls == []


def test_attempt_page_solve_not_configured_falls_back_to_stop():
    solver = NopechaSolver(api_key="", enabled=True, client=FakeClient())
    result = solver.attempt_page_solve(_challenge_page())
    assert result["ok"] is False and result["solved"] is False
    assert "not configured" in result["error"]


def test_mock_solve_no_key_and_with_key():
    assert NopechaSolver(api_key="", enabled=True).mock_solve()["ok"] is False
    result = NopechaSolver(api_key="key-12345678", enabled=True).mock_solve()
    assert result["ok"] is True and result["mock"] is True
    assert result["masked_key"] == "key-***"
    assert "key-12345678" not in str(result)


def test_check_challenge_or_solve_solves_and_raises():
    # Solved via NopeCHA -> returns True (no raise).
    solver = NopechaSolver(api_key="key-12345678", enabled=True, client=FakeClient())
    assert check_challenge_or_solve(_challenge_page(), solver) is True
    # No solver -> raises, exactly like the old stop-on-challenge path.
    with pytest.raises(ChallengeDetectedError):
        check_challenge_or_solve(_challenge_page(), solver=None)
    # Clean page -> False, nothing happens.
    assert check_challenge_or_solve(FakePage(), solver=None) is False


# -- dashboard config endpoints (Flask test client, temp DB) ------------------

@pytest.fixture()
def flask_client(tmp_path, monkeypatch):
    monkeypatch.delenv("NOPECHA_API_KEY", raising=False)
    monkeypatch.delenv("NOPECHA_ENABLED", raising=False)
    import app as app_module

    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "captcha-test.db"))
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def test_dashboard_config_get_empty(flask_client):
    resp = flask_client.get("/api/captcha/config")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["configured"] is False
    assert data["api_key_masked"] == ""
    assert data["enabled"] is False


def test_dashboard_config_save_returns_masked_only(flask_client):
    resp = flask_client.post("/api/captcha/config",
                             json={"enabled": True, "api_key": "testkey-12345678"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["configured"] is True
    assert data["api_key_masked"] == "test***"
    assert "testkey-12345678" not in resp.get_data(as_text=True)
    # And a later GET still never shows the full key.
    again = flask_client.get("/api/captcha/config").get_json()
    assert again["configured"] is True and again["enabled"] is True
    assert again["api_key_masked"] == "test***"


def test_dashboard_config_clear_key(flask_client):
    flask_client.post("/api/captcha/config",
                      json={"enabled": True, "api_key": "testkey-12345678"})
    flask_client.post("/api/captcha/config", json={"api_key": ""})
    assert flask_client.get("/api/captcha/config").get_json()["configured"] is False


def test_dashboard_test_endpoint_mock_no_key(flask_client):
    resp = flask_client.post("/api/captcha/test", json={})
    data = resp.get_json()
    assert data["ok"] is False
    assert "not configured" in data["error"]


def test_dashboard_test_endpoint_mock_with_key(flask_client):
    flask_client.post("/api/captcha/config",
                      json={"enabled": True, "api_key": "testkey-12345678"})
    data = flask_client.post("/api/captcha/test", json={}).get_json()
    assert data["ok"] is True and data["mock"] is True
    assert "testkey-12345678" not in str(data)


def test_dashboard_status_endpoint_no_key(flask_client):
    data = flask_client.post("/api/captcha/status", json={}).get_json()
    assert data["ok"] is False
    assert "not configured" in data["error"]
