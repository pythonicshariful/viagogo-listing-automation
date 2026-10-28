"""End-to-end dry-run test — NO Viagogo, NO browser, NO real Discord.

Proves: pricing -> bulk create (SQLite) -> dry-run post (fake DRY id)
-> simulate sale -> Discord payload (dry-run, not sent) -> pause/relist.
Run:  python scripts/test_end_to_end.py
Exit 0 = pass.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DRY_RUN"] = "True"

from pricing import compute_listing_price  # noqa: E402
import db as store  # noqa: E402
from discord_notify import notify_sale  # noqa: E402
from viagogo_bot import ViagogoBot  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    db_path = os.path.join(tmp, "test.db")
    conn = store.connect(db_path)
    rules = {"markup_pct": 80, "min_price": 50, "max_price": 500, "round_to": 0.99}
    price = compute_listing_price(100, rules)
    assert price == 179.99, price
    print(f"1. pricing OK: face 100 +80% -> {price}")

    ids = []
    for _ in range(3):  # bulk: 3 listings, 1 event
        ids.append(store.create_listing(conn, {
            "event_name": "Real Madrid vs FC Barcelona", "event_url": "https://www.viagogo.com/DRY-RUN-EVENT",
            "category": "football", "section": "General Admission", "quantity": 2,
            "face_price": 100, "listing_price": price, "currency": "GBP", "status": "draft"}))
    assert len(store.list_listings(conn)) == 3
    print(f"2. bulk create OK: 3 drafts, ids={ids}")

    bot = ViagogoBot(dry_run=True)
    row = store.get_listing(conn, ids[0])
    res = bot.create_listing(row)
    assert res["ok"] and res["dry_run"] and res["viagogo_listing_id"].startswith("DRY-")
    store.update_listing(conn, ids[0], status="active", viagogo_listing_id=res["viagogo_listing_id"])
    print(f"3. dry-run post OK: {res['viagogo_listing_id']} (NOT posted to Viagogo)")

    row = store.get_listing(conn, ids[0])
    store.record_sale(conn, ids[0], row["listing_price"])
    store.update_listing(conn, ids[0], status="sold")
    disc = notify_sale("", row, row["listing_price"], dry_run=True)
    assert not disc["sent"] and "SALE" in disc["payload"]["content"]
    print("4. sale + Discord payload OK (dry-run, not sent):", disc["payload"]["content"][:90], "...")

    store.update_listing(conn, ids[1], status="paused")
    store.update_listing(conn, ids[1], status="active")
    assert store.get_listing(conn, ids[1])["status"] == "active"
    print("5. pause/resume OK")

    # Bot must refuse a live action in dry-run
    try:
        bot._require_live()
        raise AssertionError("dry-run bot should refuse live actions")
    except RuntimeError as e:
        print(f"6. dry-run guard OK: {e}")

print("\nALL DRY-RUN END-TO-END CHECKS PASSED ✔")
