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
SALES_MOCK_URL = (BASE / "mock" / "mock_sales_portal.html").as_uri()
SALES_NONE_MOCK_URL = (BASE / "mock" / "mock_sales_portal_none_sold.html").as_uri()

LISTINGS_FOR_SALES = [
    {"id": 1, "event_name": "Metallica - 2 Day Pass", "section": "Section 105",
     "quantity": 2, "listing_price": 992.99, "currency": "USD"},
    {"id": 2, "event_name": "Coldplay - London", "section": "Standing",
     "quantity": 2, "listing_price": 179.99, "currency": "USD"},
]

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

    # --- v1.4.0: real sale detection against the mock sales pages --------
    sales_bot = ViagogoBot(dry_run=True, mock_sales_url=SALES_MOCK_URL)
    result = sales_bot.check_sales(LISTINGS_FOR_SALES)
    assert result["available"] is True, result
    assert len(result["sales"]) == 1, result
    sale = result["sales"][0]
    assert sale["listing_id"] == 1 and sale["sale_price"] == 992.99, sale
    print(f"MOCK SALE DETECTION PASSED ✔ (sold listing 1 found via "
          f"{sale['method']}, price {sale['sale_price']})")

    none_bot = ViagogoBot(dry_run=True, mock_sales_url=SALES_NONE_MOCK_URL)
    none_result = none_bot.check_sales(LISTINGS_FOR_SALES)
    assert none_result["available"] is True, none_result
    assert none_result["sales"] == [], none_result
    print("MOCK SALE DETECTION (none sold) PASSED ✔ (0 sales found, none faked)")

    # Dry-run without a mock sales page must say "not available", never fake.
    dry_bot = ViagogoBot(dry_run=True)
    dry_result = dry_bot.check_sales(LISTINGS_FOR_SALES)
    assert dry_result["available"] is False and dry_result["sales"] == [], dry_result
    print("DRY-RUN SALE CHECK PASSED ✔ (not available, no sale faked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
