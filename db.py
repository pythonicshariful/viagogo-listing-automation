"""SQLite storage for listings, sales and config. Stdlib only."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_name TEXT NOT NULL,
  event_url TEXT,
  category TEXT DEFAULT 'football',
  section TEXT DEFAULT 'General Admission',
  quantity INTEGER DEFAULT 2,
  face_price REAL NOT NULL,
  listing_price REAL NOT NULL,
  currency TEXT DEFAULT 'GBP',
  payout_method TEXT DEFAULT 'PayPal',  -- PayPal | Direct deposit
  paypal_email TEXT,  -- required when payout_method is PayPal
  status TEXT DEFAULT 'draft',  -- draft | active | paused | sold | failed | deleted
  viagogo_listing_id TEXT,
  last_error TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER REFERENCES listings(id),
  sale_price REAL,
  notified INTEGER DEFAULT 0,
  sold_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- Opportunity Scanner (v1.2.0): price history accumulates here so a
-- future ML model (Phase 2) has training data. One row per scan per event.
CREATE TABLE IF NOT EXISTS price_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_name TEXT NOT NULL,
  event_url TEXT,
  category TEXT DEFAULT 'football',
  section TEXT DEFAULT 'General',
  currency TEXT DEFAULT 'GBP',
  lowest_price REAL,
  avg_price REAL,
  listings_count INTEGER,
  people_searching INTEGER,
  recent_sold_prices TEXT,  -- JSON list
  days_to_event INTEGER,
  source TEXT DEFAULT 'unknown',
  snapshot_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS watchlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_name TEXT NOT NULL,
  event_url TEXT NOT NULL,
  category TEXT DEFAULT 'football',
  section TEXT DEFAULT 'General',
  currency TEXT DEFAULT 'GBP',
  face_price REAL,
  quantity INTEGER DEFAULT 2,
  created_at TEXT DEFAULT (datetime('now'))
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn) -> None:
    """Graceful migration for databases created before v1.4.0: add the
    payout columns to an existing listings table if they are missing.
    A fresh DB already has them from SCHEMA, so this is a no-op there."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "payout_method" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN payout_method TEXT DEFAULT 'PayPal'")
    if "paypal_email" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN paypal_email TEXT")
    conn.commit()


def mask_email(email: str | None) -> str:
    """PayPal email, masked the same way as the NopeCHA key: first 4
    chars + '***'. This is the only form the email ever takes in a log
    or an API response. Empty/None -> ''."""
    if not email:
        return ""
    email = str(email)
    return (email[:4] + "***") if len(email) > 4 else "****"


def public_listing(row: dict) -> dict:
    """A listing as returned by the API / shown in the UI: the PayPal
    email is masked. The bot reads the raw row from the DB (it needs
    the real address to fill the PriceDetails form)."""
    out = dict(row)
    out["paypal_email"] = mask_email(row.get("paypal_email"))
    out["paypal_email_masked"] = mask_email(row.get("paypal_email"))
    return out


def create_listing(conn, data: dict) -> int:
    cur = conn.execute(
        """INSERT INTO listings
        (event_name, event_url, category, section, quantity, face_price,
         listing_price, currency, payout_method, paypal_email, status,
         viagogo_listing_id, last_error)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (data["event_name"], data.get("event_url"), data.get("category", "football"),
         data.get("section", "General Admission"), data.get("quantity", 2),
         data["face_price"], data["listing_price"], data.get("currency", "GBP"),
         data.get("payout_method", "PayPal"), data.get("paypal_email"),
         data.get("status", "draft"), data.get("viagogo_listing_id"), data.get("last_error")),
    )
    conn.commit()
    return cur.lastrowid


def get_listing(conn, listing_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM listings WHERE id=?", (listing_id,)).fetchone()
    return dict(row) if row else None


def list_listings(conn, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM listings ORDER BY id DESC"
    args: tuple = ()
    if status:
        q = "SELECT * FROM listings WHERE status=? ORDER BY id DESC"
        args = (status,)
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def update_listing(conn, listing_id: int, **fields) -> None:
    allowed = {"event_name", "event_url", "category", "section", "quantity",
               "face_price", "listing_price", "currency", "payout_method",
               "paypal_email", "status", "viagogo_listing_id", "last_error"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at=datetime('now')")
    conn.execute(f"UPDATE listings SET {', '.join(sets)} WHERE id=?", (*vals, listing_id))
    conn.commit()


def record_sale(conn, listing_id: int, sale_price: float) -> int:
    cur = conn.execute("INSERT INTO sales (listing_id, sale_price) VALUES (?,?)",
                       (listing_id, sale_price))
    conn.commit()
    return cur.lastrowid


def get_config(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_config(conn, key: str, value) -> None:
    conn.execute("INSERT INTO config(key,value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))
    conn.commit()


# --- Opportunity Scanner storage -------------------------------------------
def save_snapshot(conn, snap: dict) -> int:
    cur = conn.execute(
        """INSERT INTO price_snapshots
        (event_name, event_url, category, section, currency, lowest_price,
         avg_price, listings_count, people_searching, recent_sold_prices,
         days_to_event, source, snapshot_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (snap.get("event_name"), snap.get("event_url"), snap.get("category", "football"),
         snap.get("section", "General"), snap.get("currency", "GBP"),
         snap.get("lowest_price"), snap.get("avg_price"), snap.get("listings_count"),
         snap.get("people_searching"), json.dumps(snap.get("recent_sold_prices") or []),
         snap.get("days_to_event"), snap.get("source", "unknown"),
         snap.get("snapshot_at")))
    conn.commit()
    return cur.lastrowid


def _snapshot_row(row) -> dict:
    d = dict(row)
    try:
        d["recent_sold_prices"] = json.loads(d.get("recent_sold_prices") or "[]")
    except (TypeError, ValueError):
        d["recent_sold_prices"] = []
    return d


def latest_snapshots(conn) -> list[dict]:
    """Latest snapshot per event_url (one row per watched event)."""
    rows = conn.execute(
        "SELECT * FROM price_snapshots ORDER BY snapshot_at DESC, id DESC").fetchall()
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = row["event_url"] or row["event_name"]
        if key in seen:
            continue
        seen.add(key)
        out.append(_snapshot_row(row))
    return out


def list_snapshots(conn, event_url: str | None = None, limit: int = 50) -> list[dict]:
    if event_url:
        rows = conn.execute(
            "SELECT * FROM price_snapshots WHERE event_url=? ORDER BY snapshot_at DESC, id DESC LIMIT ?",
            (event_url, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM price_snapshots ORDER BY snapshot_at DESC, id DESC LIMIT ?",
            (limit,)).fetchall()
    return [_snapshot_row(r) for r in rows]


def add_watchlist(conn, data: dict) -> int:
    cur = conn.execute(
        """INSERT INTO watchlist
        (event_name, event_url, category, section, currency, face_price, quantity)
        VALUES (?,?,?,?,?,?,?)""",
        (data["event_name"], data["event_url"], data.get("category", "football"),
         data.get("section", "General"), data.get("currency", "GBP"),
         data.get("face_price"), int(data.get("quantity", 2))))
    conn.commit()
    return cur.lastrowid


def list_watchlist(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM watchlist ORDER BY id").fetchall()]


def remove_watchlist(conn, watch_id: int) -> bool:
    cur = conn.execute("DELETE FROM watchlist WHERE id=?", (watch_id,))
    conn.commit()
    return cur.rowcount > 0
