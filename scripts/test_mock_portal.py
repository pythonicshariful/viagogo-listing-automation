"""Mock-portal browser test — drives the 6-step pipeline against
mock/mock_seller_portal.html in a REAL Chromium browser, still with
NO Viagogo account, NO live listing, NO credentials.

Requires Chromium:  python -m playwright install chromium
Run:  python scripts/test_mock_portal.py
Exit 0 = pass. Skips cleanly (exit 0, "SKIPPED") if Chromium is missing.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viagogo_bot import ViagogoBot  # noqa: E402

BASE = Path(__file__).resolve().parents[1]
MOCK_URL = (BASE / "mock" / "mock_seller_portal.html").as_uri()

LISTING = {
    "event_name": "Metallica - 2 Day Pass",
    "event_url": MOCK_URL,
    "category": "concert",
    "section": "General Admission",
    "quantity": 2,
    "face_price": 100,
    "listing_price": 179.99,
    "currency": "USD",
    "payout_method": "PayPal",
    "paypal_email": "seller@example.com",  # mock only, never a real address
}


def main() -> int:
    bot = ViagogoBot(dry_run=True, mock_url=MOCK_URL)
    try:
        res = bot.create_listing(LISTING)
    except Exception as exc:
        if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
            print("SKIPPED: Chromium is not installed — run: python -m playwright install chromium")
            return 0
        raise
    print("bot log:")
    for entry in bot.log:
        print("  ", entry)
    assert res["ok"], res
    assert res.get("mock") and res["viagogo_listing_id"] == "MOCK-0001", res
    for step in ("1/6 Sell search", "2/6 Quantity", "3/6 ListingNotes",
                 "4/6 DeliveryDetails", "5/6 SeatDetails", "6/6 PriceDetails"):
        assert any(step in e for e in bot.log), bot.log
    print("\nMOCK-PORTAL 6-STEP FLOW PASSED ✔ (MOCK-0001, nothing posted to Viagogo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
