"""Payout-per-listing tests (v1.4.0) — no browser, no Viagogo.

Covers: PayPal email masking (never full in logs/API), the graceful
SQLite migration for pre-v1.4.0 databases, payout storage + update,
payload validation (PayPal needs an email, Direct deposit does not),
and the Flask API round-trip (bulk create WITH payout, masked in the
response, full email never in the response body).
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_PATH"] = str(TMP / "listings.db")

import db as store  # noqa: E402
from app import _validate_listing_payload, app  # noqa: E402

OLD_SCHEMA = """
CREATE TABLE listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_name TEXT NOT NULL,
  event_url TEXT,
  category TEXT DEFAULT 'football',
  section TEXT DEFAULT 'General Admission',
  quantity INTEGER DEFAULT 2,
  face_price REAL NOT NULL,
  listing_price REAL NOT NULL,
  currency TEXT DEFAULT 'GBP',
  status TEXT DEFAULT 'draft',
  viagogo_listing_id TEXT,
  last_error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
"""

BASE = {
    "event_name": "Metallica - 2 Day Pass",
    "event_url": "https://www.viagogo.com/DRY-RUN-EVENT",
    "category": "concert",
    "section": "Section 105",
    "quantity": 2,
    "face_price": 500,
    "listing_price": 899.99,
    "currency": "USD",
    "status": "draft",
}


def test_mask_email():
    assert store.mask_email("seller@example.com") == "sell***"
    assert store.mask_email("") == ""
    assert store.mask_email(None) == ""
    assert store.mask_email("ab@c") == "****"  # too short to show safely


def test_migration_adds_payout_columns_to_old_db():
    """A database created by v1.3.1 (no payout columns) gains them on
    connect, and its old rows stay readable with the PayPal default."""
    path = TMP / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SCHEMA)
    raw.execute("INSERT INTO listings (event_name, face_price, listing_price) "
                "VALUES ('Old Event', 100, 179.99)")
    raw.commit()
    raw.close()
    conn = store.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    assert "payout_method" in cols and "paypal_email" in cols
    row = store.get_listing(conn, 1)
    assert row["event_name"] == "Old Event"
    assert row["payout_method"] == "PayPal"  # column default
    assert row["paypal_email"] is None
    conn.close()


def test_create_listing_stores_payout_and_masks_it():
    conn = store.connect(TMP / "payout.db")
    lid = store.create_listing(conn, dict(BASE, payout_method="PayPal",
                                         paypal_email="seller@example.com"))
    row = store.get_listing(conn, lid)
    assert row["payout_method"] == "PayPal"
    assert row["paypal_email"] == "seller@example.com"  # DB keeps the real one (bot needs it)
    public = store.public_listing(row)
    assert public["paypal_email"] == "sell***"
    assert public["paypal_email_masked"] == "sell***"
    assert "seller@example.com" not in str(public)
    conn.close()


def test_update_listing_payout_fields():
    conn = store.connect(TMP / "payout2.db")
    lid = store.create_listing(conn, dict(BASE, payout_method="PayPal",
                                         paypal_email="a@example.com"))
    store.update_listing(conn, lid, payout_method="Direct deposit", paypal_email=None)
    row = store.get_listing(conn, lid)
    assert row["payout_method"] == "Direct deposit"
    assert row["paypal_email"] is None
    conn.close()


def test_validate_payload_requires_paypal_email():
    payload = dict(BASE, face_price=500, payout_method="PayPal", paypal_email="")
    assert any("paypal_email" in e for e in _validate_listing_payload(payload))
    payload = dict(BASE, face_price=500, payout_method="PayPal",
                   paypal_email="not-an-email")
    assert any("paypal_email" in e for e in _validate_listing_payload(payload))
    payload = dict(BASE, face_price=500, payout_method="PayPal",
                   paypal_email="seller@example.com")
    assert _validate_listing_payload(payload) == []
    # Direct deposit needs no email at all.
    payload = dict(BASE, face_price=500, payout_method="Direct deposit")
    assert _validate_listing_payload(payload) == []
    payload = dict(BASE, face_price=500, payout_method="Bitcoin")
    assert any("payout_method" in e for e in _validate_listing_payload(payload))


def test_api_bulk_create_with_payout_masked_in_response():
    client = app.test_client()
    resp = client.post("/api/bulk", json={
        "event_name": "Metallica - 2 Day Pass",
        "event_url": "https://www.viagogo.com/DRY-RUN-EVENT",
        "category": "concert", "section": "Section 105",
        "face_price": 500, "listings_per_event": 2, "quantity_per_listing": 2,
        "payout_method": "PayPal", "paypal_email": "seller@example.com"})
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    assert data["created"] == 2
    for listing in data["listings"]:
        assert listing["payout_method"] == "PayPal"
        assert listing["paypal_email"] == "sell***"
    # The full email must never appear in the response body.
    assert b"seller@example.com" not in resp.data


def test_api_bulk_create_refuses_paypal_without_email():
    client = app.test_client()
    resp = client.post("/api/bulk", json={
        "event_name": "Metallica - 2 Day Pass", "face_price": 500,
        "listings_per_event": 1, "quantity_per_listing": 2,
        "payout_method": "PayPal"})
    assert resp.status_code == 400
    assert any("paypal_email" in e for e in resp.get_json()["errors"])


def test_api_single_create_direct_deposit_needs_no_email():
    client = app.test_client()
    resp = client.post("/api/listings", json={
        "event_name": "Coldplay - London", "face_price": 100,
        "quantity": 2, "payout_method": "Direct deposit"})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["listing"]["payout_method"] == "Direct deposit"


def test_api_listings_show_payout_masked():
    client = app.test_client()
    resp = client.get("/api/listings")
    assert resp.status_code == 200
    assert b"seller@example.com" not in resp.data
    rows = resp.get_json()
    assert any(r.get("payout_method") == "PayPal" and r.get("paypal_email") == "sell***"
               for r in rows)


def test_plain_error_never_returns_a_traceback():
    from app import _plain_error

    assert _plain_error(RuntimeError("BLOCKED: add a card by hand first")).startswith("BLOCKED")
    assert "Traceback" not in _plain_error(Exception("Traceback (most recent call last):\n  File \"x\""))
    assert "File \"" not in _plain_error(Exception("File \"x\", line 1"))
    assert len(_plain_error(Exception("x" * 500))) <= 300
