"""Tests for the v1.5.1 live-check fix.

Evidence base: tests/fixtures/real_artist_pages_20261028.txt — verbatim
excerpts from the REAL Viagogo pages fetched 2026-10-28, the day
Shariful's verify_live.py run returned all-None. These tests prove the
root cause (artist pages have no prices for one event; the "Tickets:
N USD" format was invisible to the parser) and the fix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from livecheck import (LiveCheckStore, check_sell_gate, event_link_hint,
                       format_diag, format_result, new_run_id, run_live_check,
                       write_evidence)
from market import (detect_page_kind, is_empty_page,
                    looks_like_artist_page_url, parse_prices,
                    parse_snapshot_text, parse_suffix_prices,
                    parse_tickets_price)
from stealth import detect_challenge_text

FIXTURE = Path(__file__).parent / "fixtures" / "real_artist_pages_20261028.txt"


def _sections() -> dict[str, str]:
    """Split the fixture on its '# --- SECTION <name>' markers."""
    text = FIXTURE.read_text(encoding="utf-8")
    parts = re.split(r"# --- SECTION (.+?)\n", text)
    out: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip().rstrip("-").strip()
        body = parts[i + 1]
        # Drop comment lines inside the section body.
        body = "\n".join(line for line in body.splitlines()
                         if not line.strip().startswith("#")).strip()
        out[name] = body
    return out


SECTIONS = _sections()
MADRID = SECTIONS["Real Madrid CF artist page, viagogo.com, 2026-10-28"]
BARCA = SECTIONS["FC Barcelona artist page, viagogo.co.uk, 2026-10-28"]
METALLICA = SECTIONS["Metallica artist page, viagogo.com, 2026-10-28"]
STRUCTURED = SECTIONS["Structured per-event data (viagogo.com.tr JSON-LD), 2026-10-28"]

EVENT = {"event_name": "Test event", "event_url": "https://www.viagogo.com/x",
         "category": "football", "section": "General", "currency": "GBP"}


# --- Root cause 1: the "Tickets: N USD" format was invisible -----------
def test_suffix_prices_read_tickets_usd_format():
    assert parse_suffix_prices("Tickets: 1,265.69 USD") == [(1265.69, "USD")]
    assert parse_suffix_prices("Tickets: 172.51 USD") == [(172.51, "USD")]
    assert parse_suffix_prices("Tickets: 7,849.52 USD") == [(7849.52, "USD")]
    assert parse_suffix_prices("Tickets: 127.58 USD") == [(127.58, "USD")]


def test_suffix_prices_reject_years_and_unknown_codes():
    # "2026 USD" is a year, not a price — the old regex would have
    # misread it; the new one must not.
    assert parse_suffix_prices("When: 2026-10-25 USD") == []
    assert parse_suffix_prices("Tickets: 50 ABC") == []  # not a currency
    # A decimal amount IS returned as a real-looking price here; the
    # snapshot-level filter (1 <= price <= 100000) drops sub-$1 values
    # before they can become a "lowest price".
    assert parse_suffix_prices("Tickets: 0.50 USD") == [(0.5, "USD")]
    snap = parse_snapshot_text("Tickets: 0.50 USD", EVENT)
    assert snap["lowest_price"] is None


def test_tickets_price_takes_cheapest_tickets_line():
    assert parse_tickets_price("Tickets: 1,265.69 USD\nTickets: 172.51 USD") == (172.51, "USD")
    assert parse_tickets_price("No tickets line here") == (None, None)


def test_parse_prices_now_includes_suffix_format():
    prices = parse_prices("Tickets: 1,265.69 USD and $860 and $900")
    assert 1265.69 in prices and 860.0 in prices and 900.0 in prices


def test_structured_per_event_data_reads_prices():
    snap = parse_snapshot_text(STRUCTURED, EVENT)
    assert snap["lowest_price"] == 127.58  # RB Leipzig — cheapest of the four
    assert snap["currency"] == "USD"
    assert snap["source"] == "live"


# --- Root cause 2: artist pages have no prices for one event -----------
def test_real_madrid_artist_page_has_no_prices():
    snap = parse_snapshot_text(MADRID, {**EVENT, "currency": "EUR"})
    assert snap["lowest_price"] is None
    assert snap["avg_price"] is None
    # But the page DOES show demand: this is what Shariful's run saw
    # (people None / signals [] meant his browser never got this text).
    assert snap["people_searching"] == 3895
    assert snap["demand_signals"] == ["only_1pct_left", "selling_fast", "top_seller"]
    assert snap["page_kind"] == "artist"
    assert snap["events_count"] == 39
    assert "artist page" in snap["page_note"]
    assert "no prices" in snap["page_note"]


def test_barcelona_artist_page_has_no_prices():
    snap = parse_snapshot_text(BARCA, EVENT)
    assert snap["lowest_price"] is None
    assert snap["page_kind"] == "artist"
    assert snap["events_count"] == 34
    assert "artist page" in snap["page_note"]


def test_metallica_artist_page_has_per_event_from_prices():
    snap = parse_snapshot_text(METALLICA, {**EVENT, "currency": "USD"})
    # Cheapest event on the page is $463 (Oct 29 single); the headline
    # "From $895" is only the FIRST event's price, not the cheapest.
    assert snap["lowest_price"] == 463.0
    assert snap["from_price"] == 895.0
    assert snap["page_kind"] == "artist"
    assert snap["events_count"] == 38
    assert "artist page" in snap["page_note"]


def test_detect_page_kind_and_empty_page():
    assert detect_page_kind(MADRID)["kind"] == "artist"
    assert detect_page_kind(METALLICA)["kind"] == "artist"
    assert detect_page_kind("Some random page with no event count")["kind"] == "unknown"
    # A single-event page has no "N events" marker either — it is also
    # "unknown" (not "artist"); "unknown" means "not provably an artist
    # page", not "empty" (see is_empty_page for that).
    assert detect_page_kind("Tickets from $813 — buy now")["kind"] == "unknown"
    assert is_empty_page("", "Viagogo") is True
    assert is_empty_page("x" * 50, "Viagogo") is True  # too little text
    assert is_empty_page("viagogo " + "x" * 300, "t") is False


# --- URL hint: artist page vs single-event page -------------------------
def test_artist_page_url_hint():
    assert looks_like_artist_page_url(
        "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets") is True
    assert looks_like_artist_page_url(
        "https://www.viagogo.co.uk/Sports-Tickets/Football/International-Football/Spanish-Premier-League/FC-Barcelona-Tickets") is True
    # A single-event URL ends in /E-<id>, not in "-Tickets".
    assert looks_like_artist_page_url(
        "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets/E-152000000") is False
    # The Real Madrid artist page ends in /E-<id> too — the URL alone
    # cannot tell it from an event page; content detection must catch it.
    assert looks_like_artist_page_url(
        "https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-151961718") is False
    assert looks_like_artist_page_url("not a url") is False
    assert looks_like_artist_page_url("") is False


def test_event_link_hint():
    assert event_link_hint("Real Madrid CF (artist page) — Real Madrid CF vs Villarreal CF") == \
        "Real Madrid CF vs Villarreal CF"
    assert event_link_hint("Metallica (artist page) — Metallica - 2 Day Pass (October 29 & 31)") == \
        "Metallica - 2 Day Pass (October 29 & 31)"
    assert event_link_hint("Plain event name") == "Plain event name"


# --- Challenge detection: DataDome --------------------------------------
def test_datadome_challenge_detected():
    assert detect_challenge_text(
        "Access denied",
        "Please enable JS and disable any ad blocker. geo.captcha-delivery.com") == "datadome"
    assert detect_challenge_text("DataDome", "Verify your browser") == "datadome"
    assert detect_challenge_text("Viagogo", "Tickets from $813") is None


# --- Diagnostics formatting ----------------------------------------------
def test_format_diag_names_the_cause():
    diag = {"title": "Viagogo", "final_url": "https://www.viagogo.com/x",
            "http_status": 200, "text_chars": 120, "elapsed_s": 12.3,
            "text_excerpt": "Real Madrid CF Tickets",
            "challenge": "datadome", "screenshot": "logs/x.png",
            "reason": "Viagogo showed a bot challenge (datadome)"}
    out = format_diag(diag)
    assert "datadome" in out
    assert "Real Madrid CF Tickets" in out
    assert "120 chars" in out
    assert "logs/x.png" in out


def test_format_result_failed_states_reason():
    result = {"event_name": "Real Madrid CF", "event_url": "https://www.viagogo.com/x",
              "status": "failed", "reason": "no prices found on this page",
              "snapshot": {"source": "live", "currency": "EUR", "lowest_price": None,
                           "avg_price": None, "listings_count": None,
                           "people_searching": 3895, "demand_signals": [],
                           "page_kind": "artist", "page_note": "artist page"},
              "diagnostics": {"title": "Viagogo", "text_chars": 400,
                              "text_excerpt": "Real Madrid CF Tickets",
                              "elapsed_s": 10.0}}
    out = format_result(result)
    assert "FAILED" in out
    assert "no prices found on this page" in out
    assert "artist" in out


def test_write_evidence_file(tmp_path):
    run = {"run_id": "abc123", "started_at": "2026-10-28T00:00:00+00:00",
           "finished_at": "2026-10-28T00:01:00+00:00", "status": "failed",
           "headed": False,
           "results": [{"event_name": "E", "event_url": "https://x",
                        "status": "failed", "reason": "no prices",
                        "snapshot": {"source": "live", "currency": "USD",
                                     "lowest_price": None, "avg_price": None,
                                     "listings_count": None, "people_searching": None,
                                     "demand_signals": []},
                        "diagnostics": {"title": "T", "text_chars": 10,
                                        "text_excerpt": "hello", "elapsed_s": 1.0}}],
           "sell_gate": {"url": "https://sell.viagogo.com/selltickets",
                         "title": "Sell", "http_status": 200,
                         "login_gate_reached": True, "page_text_chars": 100,
                         "text_excerpt": "Sign in", "screenshot": None, "error": None}}
    path = write_evidence(tmp_path, "abc123", run)
    assert path.name == "live-check-abc123.txt"
    body = path.read_text(encoding="utf-8")
    assert "run abc123" in body
    assert "no prices" in body
    assert "login gate reached: True" in body


# --- run_live_check with a fake monitor (no real network) ---------------
class _FakeMonitor:
    """Stands in for MarketMonitor.collect_with_diagnostics."""

    def __init__(self, *args, **kwargs):
        self.delay_s = 0

    def collect_with_diagnostics(self, event, screenshot_dir=None, headed=False,
                                 max_attempts=2):
        snap = parse_snapshot_text(MADRID, event)
        snap["source"] = "live"
        diag = {"event_name": event["event_name"], "event_url": event["event_url"],
                "title": "Viagogo", "final_url": event["event_url"],
                "http_status": 200, "text_chars": len(MADRID),
                "text_excerpt": MADRID[:500], "elapsed_s": 1.0,
                "reason": snap.get("page_note", "")}
        return snap, diag


def test_run_live_check_with_fake_monitor(monkeypatch):
    import livecheck
    import market

    monkeypatch.setattr(market, "MarketMonitor", _FakeMonitor)
    monkeypatch.setattr(livecheck, "check_sell_gate",
                        lambda **kw: {"url": "https://sell.viagogo.com/selltickets",
                                      "title": "Sell", "http_status": 200,
                                      "login_gate_reached": True,
                                      "page_text_chars": 100, "text_excerpt": "Sign in",
                                      "screenshot": None, "elapsed_s": 1.0, "error": None})
    watchlist = [{"event_name": "Real Madrid CF", "event_url": "https://www.viagogo.com/x",
                  "category": "football", "section": "General", "currency": "EUR"}]
    run = run_live_check(watchlist, settings={"scan_delay_s": 0}, headed=False)
    assert run["status"] == "failed"  # artist page: no prices, gate OK
    assert len(run["results"]) == 1
    assert run["results"][0]["status"] == "failed"
    assert "artist page" in run["results"][0]["reason"]
    assert run["sell_gate"]["login_gate_reached"] is True


def test_run_live_check_empty_watchlist(monkeypatch):
    import livecheck

    monkeypatch.setattr(livecheck, "check_sell_gate",
                        lambda **kw: {"url": "https://sell.viagogo.com/selltickets",
                                      "title": "Sell", "http_status": 200,
                                      "login_gate_reached": True,
                                      "page_text_chars": 100, "text_excerpt": "Sign in",
                                      "screenshot": None, "elapsed_s": 1.0, "error": None})
    run = run_live_check([], settings={})
    assert run["results"] == []
    # No event was checked, so nothing was proven — not a pass.
    # (The dashboard API refuses an empty watchlist with 400 first.)
    assert run["status"] == "failed"
    assert run["sell_gate"]["login_gate_reached"] is True


def test_live_check_store_keeps_last_runs():
    store = LiveCheckStore(max_runs=2)
    assert store.running() is False
    store.start({"run_id": "a", "status": "running"})
    assert store.running() is True
    store.start({"run_id": "b", "status": "passed"})
    store.start({"run_id": "c", "status": "passed"})
    assert store.get("a") is None  # trimmed: only the last 2 kept
    assert store.get("c")["status"] == "passed"
    assert [r["run_id"] for r in store.list()] == ["c", "b"]


def test_new_run_id_is_short_hex():
    assert re.fullmatch(r"[0-9a-f]{8}", new_run_id())


# --- Dashboard API: POST/GET /api/live-check (mock runner, no network) ---
import time

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

    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "livecheck-test.db"))
    monkeypatch.setattr(app_module, "BASE", tmp_path)
    monkeypatch.setattr(app_module, "LOG_DIR", tmp_path / "logs")
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def _fake_run(watchlist, **kw):
    """Instant completed run — stands in for the real browser check."""
    return {"run_id": kw.get("run_id", "test-run"), "status": "passed",
            "headed": kw.get("headed", False),
            "started_at": "2026-10-28T00:00:00+00:00",
            "finished_at": "2026-10-28T00:01:00+00:00",
            "results": [{"event_name": w["event_name"], "event_url": w["event_url"],
                         "status": "ok", "reason": "",
                         "snapshot": {"source": "live", "currency": "USD",
                                      "lowest_price": 813.0, "avg_price": 813.0,
                                      "listings_count": 20, "people_searching": 3895,
                                      "demand_signals": ["selling_fast"],
                                      "page_kind": None, "page_note": ""},
                         "diagnostics": {"title": "Viagogo",
                                         "final_url": w["event_url"],
                                         "http_status": 200, "text_chars": 500,
                                         "text_excerpt": "Metallica Tickets",
                                         "elapsed_s": 5.0}}
                        for w in watchlist[:1]],
            "sell_gate": {"url": "https://sell.viagogo.com/selltickets",
                          "title": "Sell", "http_status": 200,
                          "login_gate_reached": True, "page_text_chars": 100,
                          "text_excerpt": "Sign in", "screenshot": None,
                          "elapsed_s": 2.0, "error": None},
            "evidence_file": None}


def _add_watchlist_event(client):
    resp = client.post("/api/watchlist", json={
        "event_name": "Metallica - Sphere, Las Vegas",
        "event_url": "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets/E-152000000",
        "category": "concert", "section": "100 Level",
        "currency": "USD", "face_price": 500, "quantity": 2})
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()


def _poll_until_done(client, run_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/live-check/{run_id}").get_json()
        if data.get("status") != "running":
            return data
        time.sleep(0.2)
    raise AssertionError(f"live check {run_id} still running after {timeout}s")


def test_live_check_api_full_flow(flask_client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "run_live_check", _fake_run)
    _add_watchlist_event(flask_client)
    resp = flask_client.post("/api/live-check", json={"headed": False})
    assert resp.status_code == 202, resp.get_json()
    run_id = resp.get_json()["run_id"]
    done = _poll_until_done(flask_client, run_id)
    assert done["status"] == "passed"
    assert done["results"][0]["status"] == "ok"
    assert done["results"][0]["snapshot"]["lowest_price"] == 813.0
    assert done["sell_gate"]["login_gate_reached"] is True
    listing = flask_client.get("/api/live-check").get_json()
    assert any(r["run_id"] == run_id for r in listing["runs"])


def test_live_check_api_empty_watchlist(flask_client):
    resp = flask_client.post("/api/live-check", json={})
    assert resp.status_code == 400
    assert "watchlist is empty" in resp.get_json()["error"]


def test_live_check_api_unknown_run(flask_client):
    assert flask_client.get("/api/live-check/no-such-run").status_code == 404


def test_live_check_api_second_run_while_running(flask_client, monkeypatch):
    import app as app_module

    def _slow_run(watchlist, **kw):
        time.sleep(3)
        return _fake_run(watchlist, **kw)

    monkeypatch.setattr(app_module, "run_live_check", _slow_run)
    _add_watchlist_event(flask_client)
    first = flask_client.post("/api/live-check", json={})
    assert first.status_code == 202, first.get_json()
    second = flask_client.post("/api/live-check", json={})
    assert second.status_code == 409
    assert "already running" in second.get_json()["error"]
    _poll_until_done(flask_client, first.get_json()["run_id"], timeout=10.0)


def test_watchlist_warns_on_artist_page_url(flask_client):
    resp = flask_client.post("/api/watchlist", json={
        "event_name": "Metallica (artist page)",
        "event_url": "https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets",
        "category": "concert", "section": "General",
        "currency": "USD", "face_price": 500, "quantity": 2})
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert "warning" in data
    assert "ARTIST page" in data["warning"]
    assert "single event page" in data["warning"]


def test_watchlist_no_warning_for_single_event_url(flask_client):
    data = _add_watchlist_event(flask_client)
    assert "warning" not in data


# --- Sell gate never hangs: a raising Playwright is reported, not raised -
def test_check_sell_gate_reports_playwright_failure(monkeypatch):
    import livecheck
    import playwright.sync_api as pw_api

    class _Boom:
        def __enter__(self):
            raise RuntimeError("browser launch failed")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pw_api, "sync_playwright", lambda: _Boom())
    gate = check_sell_gate(progress=lambda m: None)
    assert gate["login_gate_reached"] is False
    assert "browser launch failed" in gate["error"]
