"""Auto-collector + honest-live tests (v1.5.0) — all mock/offline.

No .env file, no network, no Viagogo. A temp SQLite DB + temp app
folder stand in for the real install. Covers:
- the parser against REAL Viagogo page text (tests/fixtures/real_page_text.txt
  — verbatim strings observed on viagogo.com / viagogo.co.uk on 2026-10-28)
- the REAL MarketMonitor browser code against a local page built from
  that real text (file:// URL, real Chromium, no internet)
- collector scheduling / failure survival / training-data-only-live rule
- the API refusing to silently downgrade a live request to sample
- training stats + CSV/JSON export shape

The live Playwright run against viagogo.com itself cannot run on the
dev VM (its egress proxy answers Chromium's CONNECT with 403
policy_denied — see LIVE_VERIFICATION.md). Run
scripts/verify_live.py on a normal machine for that proof.
"""
import io
import json
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import (AutoCollector, is_live_training_snapshot,
                       next_run_at, validate_interval_hours)
from market import (MarketMonitor, parse_currency, parse_from_price,
                    parse_scarcity, parse_snapshot_text)

BASE = Path(__file__).resolve().parents[1]
FIXTURE = (BASE / "tests" / "fixtures" / "real_page_text.txt").read_text(encoding="utf-8")

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

    monkeypatch.setattr(app_module, "DB_PATH", str(tmp_path / "autocollect-test.db"))
    monkeypatch.setattr(app_module, "BASE", tmp_path)
    # watchlist_seed reads BASE/watchlist.example.json — give the temp
    # app folder the real seed file.
    import shutil

    shutil.copy(BASE / "watchlist.example.json", tmp_path / "watchlist.example.json")
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as client:
        yield client


def _seed_watchlist(client):
    resp = client.post("/api/watchlist/seed", json={})
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["added"]


# ---------------------------------------------------------------------------
# 1. Parser against REAL Viagogo page text
# ---------------------------------------------------------------------------
def test_real_page_from_price_and_currency():
    price, currency = parse_from_price(FIXTURE)
    assert price == 813.0
    assert currency == "USD"
    assert parse_currency(FIXTURE) == "USD"
    assert parse_currency("£1,299.50") == "GBP"
    assert parse_currency("€99") == "EUR"
    assert parse_currency("no prices here") is None
    assert parse_from_price("no headline price") == (None, None)


def test_real_page_people_viewed_and_scarcity():
    snap = parse_snapshot_text(FIXTURE, {"event_name": "Real Madrid CF",
                                         "event_url": "https://www.viagogo.com/x",
                                         "category": "football"})
    # "3,895 people viewed Real Madrid CF events in the past hour"
    assert snap["people_searching"] == 3895
    # "Only 1% of tickets left", "Selling fast", "Top seller" — Viagogo's words.
    assert snap["demand_signals"] == ["only_1pct_left", "selling_fast", "top_seller"]
    # "20 tickets left" on the page.
    assert snap["listings_count"] == 20
    # The fixture mashes three pages together; the cheapest real price
    # in it is the Alavés "Tickets: 172.51 USD" line. The headline
    # "Tickets from $813" is still recorded separately as from_price.
    assert snap["lowest_price"] == 172.51
    assert snap["from_price"] == 813.0
    assert snap["currency"] == "USD"
    assert snap["source"] == "live"
    # The mashed text says "39 events in all locations" — an artist page.
    assert snap["page_kind"] == "artist"
    assert snap["events_count"] == 39


def test_parse_scarcity_empty():
    assert parse_scarcity("nothing special here") == []
    assert parse_scarcity("") == []


# ---------------------------------------------------------------------------
# 2. REAL MarketMonitor browser code against a page built from real text
# ---------------------------------------------------------------------------
def test_live_monitor_against_real_structure_page(tmp_path):
    """The actual Playwright scanner code (stealth context, challenge
    check, inner_text, parse) run against a local page whose text is
    the real Viagogo page text. No internet — file:// URL."""
    page = tmp_path / "real-structure.html"
    body = FIXTURE.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = body.replace("\n", "<br>\n")
    page.write_text(f"<!doctype html><html><head><title>Real Madrid CF Tickets</title>"
                    f"</head><body>{body}</body></html>", encoding="utf-8")
    monitor = MarketMonitor(live=True, scan_live=True)
    snap = monitor.collect({"event_name": "Real Madrid CF",
                            "event_url": page.as_uri(),
                            "category": "football", "section": "General Admission",
                            "currency": "EUR"})
    assert snap["source"] == "live", snap
    # Cheapest real price in the mashed fixture text is the Alavés
    # "Tickets: 172.51 USD" line (the $813 headline is from_price).
    assert snap["lowest_price"] == 172.51, snap
    assert snap["from_price"] == 813.0, snap
    assert snap["currency"] == "USD", snap  # page currency wins over the event's EUR
    assert snap["people_searching"] == 3895, snap
    assert snap["listings_count"] == 20, snap
    assert "only_1pct_left" in snap["demand_signals"], snap


# ---------------------------------------------------------------------------
# 3. Collector rules (pure logic, no threads needed for most)
# ---------------------------------------------------------------------------
def test_collector_interval_validation():
    assert validate_interval_hours(6) == (6.0, None)
    assert validate_interval_hours("2.5") == (2.5, None)
    assert validate_interval_hours(0)[1] is not None
    assert validate_interval_hours(25)[1] is not None
    assert validate_interval_hours("soon")[1] is not None


def test_collector_next_run():
    nxt = next_run_at("2026-10-28T10:00:00+00:00", 6.0)
    assert nxt.startswith("2026-10-28T16:00:00")
    assert next_run_at(None, 6.0)  # no last run -> one interval from now


def test_only_live_snapshots_are_training_data():
    assert is_live_training_snapshot({"source": "live", "lowest_price": 813.0}) is True
    assert is_live_training_snapshot({"source": "mock-sample", "lowest_price": 813.0}) is False
    assert is_live_training_snapshot({"source": "live", "lowest_price": None}) is False
    assert is_live_training_snapshot({"source": "live-challenge", "lowest_price": None}) is False
    assert is_live_training_snapshot({"source": "live-failed", "lowest_price": None}) is False


def test_collector_run_once_stores_and_reports():
    saved: dict = {}

    def collect_fn():
        return {"ok": True, "stored": 3, "scanned": 3, "errors": []}

    col = AutoCollector(collect_fn, lambda: saved, lambda s: saved.update(s))
    result = col.run_once()
    assert result["stored"] == 3
    status = col.status()
    assert status["total_runs"] == 1
    assert status["total_snapshots"] == 3
    assert status["last_run_status"].startswith("ok — 3 live snapshots stored")


def test_collector_failure_does_not_kill_schedule():
    calls = {"n": 0}

    def collect_fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("browser exploded")
        return {"ok": True, "stored": 2, "scanned": 2, "errors": []}

    saved: dict = {}
    col = AutoCollector(collect_fn, lambda: saved, lambda s: saved.update(s))
    first = col.run_once()
    assert first["ok"] is False
    assert col.status()["last_run_status"].startswith("failed")
    second = col.run_once()
    assert second["ok"] is True and second["stored"] == 2
    assert col.status()["total_runs"] == 2
    assert col.status()["total_snapshots"] == 2


def test_collector_skipped_run_records_reason():
    def collect_fn():
        return {"ok": True, "stored": 0, "scanned": 0, "skipped": True,
                "skip_reason": "live scans are off"}

    saved: dict = {}
    col = AutoCollector(collect_fn, lambda: saved, lambda s: saved.update(s))
    col.run_once()
    assert col.status()["last_run_status"].startswith("skipped")
    assert col.status()["total_snapshots"] == 0


def test_collector_run_in_background_never_stacks():
    started = threading.Event()
    release = threading.Event()

    def collect_fn():
        started.set()
        release.wait(timeout=10)
        return {"ok": True, "stored": 1, "scanned": 1, "errors": []}

    saved: dict = {}
    col = AutoCollector(collect_fn, lambda: saved, lambda s: saved.update(s))
    assert col.run_in_background() is True
    assert started.wait(timeout=5)
    assert col.run_in_background() is False  # already running — refused
    release.set()
    time.sleep(0.5)
    assert col.run_in_background() is True


# ---------------------------------------------------------------------------
# 4. API: no silent downgrade, training stats, export, collector settings
# ---------------------------------------------------------------------------
def test_scan_refuses_live_when_toggle_off(flask_client):
    _seed_watchlist(flask_client)
    resp = flask_client.post("/api/scan", json={"live": True})
    assert resp.status_code == 400, resp.get_json()
    assert "Live scans are OFF" in resp.get_json()["error"]
    # And nothing was scanned / no sample substituted.
    assert resp.get_json().get("scanned") is None


def test_scan_sample_is_labelled(flask_client):
    _seed_watchlist(flask_client)
    resp = flask_client.post("/api/scan", json={})
    data = resp.get_json()
    assert resp.status_code == 200, data
    assert data["data_source"] == "sample"
    assert "SAMPLE DATA" in data["sample_warning"]
    assert data["live_errors"] == []


def test_scan_live_all_failed_returns_502_not_sample(flask_client, monkeypatch):
    import app as app_module

    _seed_watchlist(flask_client)
    flask_client.post("/api/settings", json={"scan_live": True})

    class FailingMonitor:
        def __init__(self, *a, **k):
            self.log = []

        def scan_with_report(self, watch):
            snaps = [{"event_name": w["event_name"], "event_url": w["event_url"],
                      "category": w.get("category", "football"), "section": "General",
                      "currency": "GBP", "lowest_price": None, "avg_price": None,
                      "listings_count": None, "people_searching": None,
                      "recent_sold_prices": [], "days_to_event": None,
                      "snapshot_at": "2026-10-28T00:00:00+00:00",
                      "source": "live-failed", "from_price": None,
                      "demand_signals": []} for w in watch]
            errs = [{"event_name": w["event_name"], "event_url": w["event_url"],
                     "source": "live-failed", "reason": "boom"} for w in watch]
            return snaps, errs

    monkeypatch.setattr(app_module, "MarketMonitor", FailingMonitor)
    resp = flask_client.post("/api/scan", json={"live": True})
    assert resp.status_code == 502, resp.get_json()
    data = resp.get_json()
    assert data["ok"] is False
    assert data["data_source"] == "live"
    assert len(data["live_errors"]) == 5
    # The stored rows are labelled live-failed, NOT sample.
    rows = flask_client.get("/api/snapshots?limit=10").get_json()
    assert rows and all(r["source"] == "live-failed" for r in rows)


def test_training_stats_and_export(flask_client):
    _seed_watchlist(flask_client)
    flask_client.post("/api/scan", json={})  # sample scan stores 5 mock rows
    data = flask_client.get("/api/training").get_json()
    assert data["ok"] is True
    assert data["total_snapshots"] == 5
    assert data["live_snapshots"] == 0
    assert data["sample_snapshots"] == 5
    assert data["events_tracked"] == 5
    assert "No live training data yet" in data["ml_readiness"]
    assert data["collector"]["enabled"] is True
    assert data["collector"]["interval_hours"] == 6.0

    # Export defaults to live-only training data: empty, but a valid file.
    resp = flask_client.get("/api/snapshots/export?format=csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment;")
    assert resp.get_data(as_text=True).startswith("snapshot_at,event_name")
    # Export all: the 5 sample rows, with their source label.
    resp = flask_client.get("/api/snapshots/export?format=csv&source=all")
    lines = resp.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 6  # header + 5 rows
    assert "mock-sample" in lines[1]
    resp = flask_client.get("/api/snapshots/export?format=json&source=all")
    assert len(resp.get_json()) == 5
    assert flask_client.get("/api/snapshots/export?format=xml").status_code == 400


def test_collector_api_round_trip(flask_client):
    data = flask_client.get("/api/collector").get_json()
    assert data["ok"] is True
    assert data["enabled"] is True and data["interval_hours"] == 6.0
    assert data["last_run_status"] == "never run"

    resp = flask_client.post("/api/collector", json={"interval_hours": 0})
    assert resp.status_code == 400
    resp = flask_client.post("/api/collector", json={"interval_hours": 25})
    assert resp.status_code == 400
    resp = flask_client.post("/api/collector",
                             json={"enabled": False, "interval_hours": 2,
                                   "run_on_start": True})
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["enabled"] is False
    assert resp.get_json()["interval_hours"] == 2.0
    # The same values are visible through Settings (one store, not two).
    settings = flask_client.get("/api/settings").get_json()["settings"]
    assert settings["collector_enabled"] is False
    assert settings["collector_interval_hours"] == 2.0
    assert settings["collector_run_on_start"] is True


def test_collector_run_now_endpoint(flask_client):
    resp = flask_client.post("/api/collector/run-now", json={})
    assert resp.status_code == 409, resp.get_json()
    data = resp.get_json()
    assert data["live_scans_off"] is True
    assert data["started"] is False
    assert "Turn them on" in data["error"]


def test_watchlist_infers_concert_category_and_uses_explicit_currency(flask_client):
    resp = flask_client.post("/api/watchlist", json={
        "event_name": "Metallica",
        "event_url": "https://www.viagogo.com/Concert-Tickets/Metallica-Tickets/E-1",
        "section": "General",
        "face_price": 100,
        "quantity": 2,
        "currency": "USD",
    })
    assert resp.status_code == 201, resp.get_json()
    row = resp.get_json()["watchlist"]
    assert row["category"] == "concert"
    assert row["currency"] == "USD"
