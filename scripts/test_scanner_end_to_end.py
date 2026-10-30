"""Scanner end-to-end test — mock/sample data only, NO Viagogo, NO browser.

Proves: seed watchlist -> mock scan (sample snapshots stored) ->
ranked opportunities -> Discord opportunity payload (dry-run, not sent)
-> snapshots history endpoint -> Opportunities page loads.
Run:  python scripts/test_scanner_end_to_end.py
Exit 0 = pass.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DRY_RUN"] = "True"
os.environ["SCAN_LIVE"] = "False"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

with tempfile.TemporaryDirectory() as tmp:
    os.environ["DATABASE_PATH"] = os.path.join(tmp, "scanner.db")
    import app as webapp  # noqa: E402  (imported after env is set)

    client = webapp.app.test_client()

    # 1. Seed the example watchlist (5 events, Metallica first).
    r = client.post("/api/watchlist/seed")
    assert r.status_code == 200 and r.get_json()["added"] == 5, r.get_json()
    print("1. watchlist seeded: 5 events")

    # 1b. Price rules must fit the events: the USD Metallica sample is
    #     ~$860, above the GBP default max of 500, so raise the cap first
    #     (in real use Fayed sets rules per currency/event).
    r = client.post("/api/config", json={"price_rules": {
        "markup_pct": 80, "min_price": 50, "max_price": 1500,
        "round_to": 0.99, "currency": "USD"}})
    assert r.status_code == 200, r.get_json()
    print("1b. price rules set: max 1500 (USD events need a higher cap)")
    #    snapshots (honest low confidence, never invented prices).
    r = client.post("/api/scan", json={})
    data = r.get_json()
    assert r.status_code == 200 and data["mode"] == "mock-sample", data
    assert data["scanned"] == 5, data
    print(f"2. mock scan OK: {data['scanned']} snapshots, mode={data['mode']}")

    # 3. Ranked opportunities: Metallica must rank first — observed sample
    #    numbers (lowest $860, 152 searching, buy cost $700) give a real
    #    profit; placeholders have no market data so confidence 0.
    opps = data["opportunities"]
    assert len(opps) == 5, opps
    top = opps[0]
    assert "Metallica" in top["event_name"], top
    assert top["current_market_price"] == 860
    assert top["demand"] == "High"
    assert top["recommended_price"] is not None
    assert top["estimated_profit"] is not None and top["estimated_profit"] > 0
    assert top["confidence"] >= 80, top
    print(f"3. ranked OK: top = {top['event_name']} market ${top['current_market_price']} "
          f"-> list ${top['recommended_price']} profit ${top['estimated_profit']} "
          f"({top['profit_margin_pct']}%) confidence {top['confidence']}/100 "
          f"timing: {top['best_timing']}")

    # 4. GET /api/opportunities returns the same ranking.
    r = client.get("/api/opportunities")
    assert r.status_code == 200 and r.get_json()[0]["event_name"] == top["event_name"]
    print("4. GET /api/opportunities OK (same ranking)")

    # 5. Snapshots history accumulated (5 rows, for future ML training data).
    r = client.get("/api/snapshots")
    assert r.status_code == 200 and len(r.get_json()) == 5, r.get_json()
    print("5. snapshots history OK: 5 rows stored")

    # 6. Discord opportunity alert: payload built, NOT sent in dry-run.
    r = client.post("/api/opportunities/test-discord")
    disc = r.get_json()
    assert disc.get("sent") is False and "opportunity" in disc["payload"]["content"].lower(), disc
    print("6. Discord opportunity payload OK (dry-run, not sent):",
          disc["payload"]["content"][:100], "...")

    # 7. Opportunities page loads.
    r = client.get("/opportunities")
    assert r.status_code == 200 and b"Opportunity Scanner" in r.data
    print("7. /opportunities page OK (200)")

    # 8. Watchlist add/remove round-trip.
    r = client.post("/api/watchlist", json={
        "event_name": "Test Event", "event_url": "https://www.viagogo.com/test-event",
        "category": "concert", "section": "Standing", "face_price": 50, "quantity": 2})
    assert r.status_code == 201, r.get_json()
    wid = r.get_json()["watchlist"]["id"]
    r = client.delete(f"/api/watchlist/{wid}")
    assert r.status_code == 200
    print("8. watchlist add/remove OK")
    webapp._get_collector().stop()

print("\nALL SCANNER END-TO-END CHECKS PASSED ✔")
