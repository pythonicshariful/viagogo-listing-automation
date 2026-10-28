"""Dashboard settings tests (v1.3.0) — all mock/offline.

No .env file, no network, no Viagogo. A temp SQLite DB + temp app
folder stand in for the real install. Covers: settings get/set
round-trip, validation errors, the live-mode two-step confirmation,
live actions refused without a session, session upload/clear,
fee % wired into scoring, proxy test with a fake prober, server
restart flag, and /api/config back-compat.
"""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import settings as settings_mod

# Env vars that would override dashboard values — the tests must see the
# dashboard, not the developer's shell.
ENV_VARS = ["DRY_RUN", "LIVE_MODE", "LIVE_CONFIRM", "SCAN_LIVE", "SCAN_DELAY_S",
            "VIAGOGO_TIMEOUT_MS", "PLAYWRIGHT_HEADLESS", "VIAGOGO_PROXY",
            "STEALTH_ENABLED", "STEALTH_LOCALE", "STEALTH_TIMEZONE",
            "FLASK_HOST", "FLASK_PORT", "LOG_LEVEL", "VIAGOGO_SESSION_FILE",
            "NOPECHA_API_KEY", "NOPECHA_ENABLED", "DISCORD_WEBHOOK_URL"]


@pytest.fixture()
def flask_client(tmp_path, monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    import app as app_module

    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "settings-test.db"))
    monkeypatch.setattr(app_module, "BASE", tmp_path)  # session file lands in tmp
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def _get_settings(client):
    data = client.get("/api/settings").get_json()
    assert data["ok"] is True
    return data


def _make_listing(client):
    resp = client.post("/api/listings", json={
        "event_name": "Test Event", "event_url": "https://www.viagogo.com/e/1",
        "category": "football", "section": "General Admission",
        "face_price": 100, "quantity": 2})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["listing"]["id"]


def test_settings_get_defaults(flask_client):
    data = _get_settings(flask_client)
    s = data["settings"]
    assert s["mode"] == "dry"
    assert s["fee_pct"] == 10.0
    assert s["scan_live"] is False
    assert s["scan_delay_s"] == 5.0
    assert s["page_timeout_ms"] == 60000
    assert s["headless"] is True
    assert s["proxy_url"] == ""
    assert s["stealth_enabled"] is True
    assert s["stealth_locale"] == "en-US"
    assert s["stealth_timezone"] == "America/New_York"
    assert s["host"] == "127.0.0.1" and s["port"] == 5002
    assert data["session"]["present"] is False
    assert data["live_blockers"] == []
    assert data["env_overrides"] == []


def test_settings_round_trip(flask_client):
    resp = flask_client.post("/api/settings", json={
        "fee_pct": 15.5, "scan_delay_s": 2.5, "headless": False,
        "stealth_locale": "de-DE", "stealth_timezone": "Europe/Berlin",
        "scan_live": True, "port": 5999})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["ok"] is True
    assert data["restart_required"] is True  # port changed
    s = _get_settings(flask_client)["settings"]
    assert s["fee_pct"] == 15.5 and s["scan_delay_s"] == 2.5
    assert s["headless"] is False
    assert s["stealth_locale"] == "de-DE" and s["stealth_timezone"] == "Europe/Berlin"
    assert s["scan_live"] is True and s["port"] == 5999


def test_settings_validation_errors(flask_client):
    cases = [
        {"fee_pct": 150}, {"fee_pct": -1}, {"fee_pct": "lots"},
        {"port": 99999}, {"port": "abc"}, {"scan_delay_s": 99},
        {"page_timeout_ms": 100}, {"stealth_locale": "xx-YY"},
        {"stealth_timezone": "Mars/Olympus"}, {"log_level": "LOUD"},
        {"mode": "turbo"}, {"host": ""}, {"proxy_url": "not-a-url"},
        {"headless": "yes"}, {"unknown_key": 1},
    ]
    for body in cases:
        resp = flask_client.post("/api/settings", json=body)
        assert resp.status_code == 400, (body, resp.get_json())
        assert resp.get_json()["ok"] is False


def test_validate_settings_pure():
    cleaned, errors = settings_mod.validate_settings({"fee_pct": 12, "bogus": 1})
    assert cleaned == {"fee_pct": 12.0}
    assert any("bogus" in e for e in errors)
    cleaned, errors = settings_mod.validate_settings({"session_file": "../evil.json"})
    assert errors and "session_file" not in cleaned


def test_live_toggle_requires_confirmation(flask_client):
    # No confirmation at all.
    resp = flask_client.post("/api/settings", json={"mode": "live"})
    assert resp.status_code == 400
    # Checkbox only, no typed text.
    resp = flask_client.post("/api/settings", json={"mode": "live", "confirm_live": True})
    assert resp.status_code == 400
    # Typed text only, no checkbox.
    resp = flask_client.post("/api/settings", json={"mode": "live", "confirm_text": "LIVE"})
    assert resp.status_code == 400
    # Wrong typed text.
    resp = flask_client.post("/api/settings",
                             json={"mode": "live", "confirm_live": True, "confirm_text": "live"})
    assert resp.status_code == 400
    assert _get_settings(flask_client)["settings"]["mode"] == "dry"


def test_live_toggle_with_confirmation(flask_client):
    resp = flask_client.post("/api/settings",
                             json={"mode": "live", "confirm_live": True, "confirm_text": "LIVE"})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["settings"]["mode"] == "live"
    assert data["live_blockers"], "live without a session must list a blocker"
    assert any("session" in b for b in data["live_blockers"])
    health = flask_client.get("/api/health").get_json()
    assert health["live_mode"] is True and health["dry_run"] is False
    assert health["session_present"] is False


def test_live_post_refused_without_session(flask_client):
    flask_client.post("/api/settings",
                      json={"mode": "live", "confirm_live": True, "confirm_text": "LIVE"})
    listing_id = _make_listing(flask_client)
    resp = flask_client.post(f"/api/listings/{listing_id}/post", json={})
    assert resp.status_code == 502, resp.get_json()
    assert "session" in resp.get_json()["error"].lower()


def test_mode_back_to_dry_clears_confirmation(flask_client):
    flask_client.post("/api/settings",
                      json={"mode": "live", "confirm_live": True, "confirm_text": "LIVE"})
    resp = flask_client.post("/api/settings", json={"mode": "dry"})
    assert resp.status_code == 200
    assert resp.get_json()["settings"]["mode"] == "dry"
    assert flask_client.get("/api/health").get_json()["live_mode"] is False


def _session_bytes():
    return json.dumps({"cookies": [{"name": "session", "value": "abc",
                                    "domain": ".viagogo.com", "path": "/"}],
                       "origins": []}).encode()


def test_session_upload_valid(flask_client):
    resp = flask_client.post("/api/session/upload",
                             data={"file": (io.BytesIO(_session_bytes()), "auth_state.json")},
                             content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["session"]["present"] is True
    assert data["session"]["file"] == "auth_state.json"
    assert data["session"]["size_bytes"] == len(_session_bytes())
    # Contents are never in any response.
    assert "abc" not in resp.get_data(as_text=True)
    status = _get_settings(flask_client)["session"]
    assert status["present"] is True and status["modified"]


def test_session_upload_invalid(flask_client):
    # Not JSON.
    resp = flask_client.post("/api/session/upload",
                             data={"file": (io.BytesIO(b"not json"), "auth_state.json")},
                             content_type="multipart/form-data")
    assert resp.status_code == 400
    # JSON but not a storage_state.
    resp = flask_client.post("/api/session/upload",
                             data={"file": (io.BytesIO(b'{"hello": "world"}'), "auth_state.json")},
                             content_type="multipart/form-data")
    assert resp.status_code == 400
    # No file at all.
    resp = flask_client.post("/api/session/upload", data={},
                             content_type="multipart/form-data")
    assert resp.status_code == 400
    assert _get_settings(flask_client)["session"]["present"] is False


def test_session_clear(flask_client):
    flask_client.post("/api/session/upload",
                      data={"file": (io.BytesIO(_session_bytes()), "auth_state.json")},
                      content_type="multipart/form-data")
    resp = flask_client.post("/api/session/clear", json={})
    assert resp.status_code == 200
    assert resp.get_json()["removed"] is True
    assert _get_settings(flask_client)["session"]["present"] is False
    # Clearing again is fine (nothing to remove).
    assert flask_client.post("/api/session/clear", json={}).get_json()["removed"] is False


def test_fee_pct_used_in_scoring(flask_client, tmp_path, monkeypatch):
    import app as app_module
    import db as store

    flask_client.post("/api/settings", json={"fee_pct": 20})
    flask_client.post("/api/watchlist", json={
        "event_name": "Fee Test", "event_url": "https://www.viagogo.com/e/fee",
        "category": "football", "section": "General", "face_price": 100, "quantity": 2})
    with store.connect(app_module.DB_PATH) as conn:
        store.save_snapshot(conn, {
            "event_name": "Fee Test", "event_url": "https://www.viagogo.com/e/fee",
            "category": "football", "section": "General", "currency": "GBP",
            "lowest_price": 200, "avg_price": 200, "listings_count": 10,
            "people_searching": 200, "recent_sold_prices": [190, 210],
            "days_to_event": 30, "source": "mock-sample"})
    opps = flask_client.get("/api/opportunities").get_json()
    assert len(opps) == 1
    opp = opps[0]
    assert opp["fee_pct"] == 20
    # High demand (+10%): recommended 220 rounded to .99 -> 219.99;
    # profit = 219.99 * 0.80 - 100 = 75.99.
    assert opp["recommended_price"] == 219.99
    assert opp["estimated_profit_per_ticket"] == 75.99


def test_proxy_test_with_fake_probe(flask_client, monkeypatch):
    import app as app_module

    seen = {}

    def fake_probe(url, target="https://example.com", timeout=10):
        seen["url"] = url
        return {"ok": True, "status": 200, "seconds": 0.42, "error": None}

    monkeypatch.setattr(app_module.app_settings, "probe_proxy", fake_probe)
    resp = flask_client.post("/api/proxy/test",
                             json={"proxy_url": "http://user:secretpass@proxy.example:8080"})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data["ok"] is True and data["status"] == 200
    assert seen["url"] == "http://user:secretpass@proxy.example:8080"
    # Masked in the response, password never appears.
    assert data["proxy_url_masked"] == "http://user:***@proxy.example:8080"
    assert "secretpass" not in resp.get_data(as_text=True)
    # Bad proxy URL -> 400; no proxy at all -> 400.
    assert flask_client.post("/api/proxy/test", json={"proxy_url": "notaurl"}).status_code == 400
    assert flask_client.post("/api/proxy/test", json={}).status_code == 400


def test_server_settings_restart_flag(flask_client):
    resp = flask_client.post("/api/settings", json={"port": 5999})
    assert resp.get_json()["restart_required"] is True
    assert "restart" in (resp.get_json()["restart_note"] or "").lower()
    resp = flask_client.post("/api/settings", json={"fee_pct": 12})
    assert resp.get_json()["restart_required"] is False


def test_config_back_compat(flask_client):
    resp = flask_client.post("/api/config", json={
        "price_rules": {"markup_pct": 50, "min_price": 40, "max_price": 400,
                        "round_to": 0.99, "currency": "EUR"}})
    assert resp.status_code == 200
    assert resp.get_json()["price_rules"]["markup_pct"] == 50
    data = flask_client.get("/api/config").get_json()
    assert data["price_rules"]["currency"] == "EUR"
    assert data["dry_run"] is True and data["live_mode"] is False


def test_mask_proxy():
    assert settings_mod.mask_proxy("") == ""
    assert settings_mod.mask_proxy("http://proxy.example:8080") == "http://proxy.example:8080"
    assert settings_mod.mask_proxy("http://user:pass123@proxy.example:8080") == \
        "http://user:***@proxy.example:8080"
