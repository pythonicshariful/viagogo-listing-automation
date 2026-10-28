"""Bot pipeline tests — no browser, no Viagogo, no credentials.

Verifies the verified 6-step Sell pipeline (observed live 2026-10-28):
dry-run simulates all 6 steps, the pre-flight refuses missing face
value / payout, and no selector ever references a "Publish" button
(the real button is "Create Listing").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viagogo_bot import (  # noqa: E402
    DEFAULTS,
    SELECTORS,
    SELL_BASE,
    _draft_id_from_url,
    validate_price_inputs,
    ViagogoBot,
)

BASE_LISTING = {
    "event_name": "Metallica - 2 Day Pass",
    "event_url": "https://sell.viagogo.com/SellTickets/FindEvent/4690",
    "category": "concert",
    "section": "General Admission",
    "quantity": 2,
    "face_price": 100,
    "listing_price": 179.99,
    "currency": "USD",
    "payout_method": "PayPal",
    "paypal_email": "seller@example.com",
}


def test_sell_base_is_sell_subdomain():
    assert SELL_BASE == "https://sell.viagogo.com"


def test_create_listing_button_is_not_publish():
    assert SELECTORS["create_listing_button"] == "Create Listing"
    assert not any("Publish" in v for v in SELECTORS.values())


def test_draft_id_parsed_from_pipeline_url():
    url = "https://sell.viagogo.com/Secure/Pipeline/Sell/PriceDetails?ID=abc-123-def"
    assert _draft_id_from_url(url) == "abc-123-def"
    assert _draft_id_from_url("https://sell.viagogo.com/selltickets") is None


def test_validate_price_inputs_ok():
    assert validate_price_inputs(BASE_LISTING) == []


def test_validate_price_inputs_missing_face_value():
    bad = dict(BASE_LISTING, face_price=None)
    errors = validate_price_inputs(bad)
    assert any("face_price" in e for e in errors)


def test_validate_price_inputs_missing_paypal_email():
    bad = dict(BASE_LISTING, paypal_email="")
    errors = validate_price_inputs(bad)
    assert any("paypal_email" in e for e in errors)


def test_validate_price_inputs_bad_payout():
    bad = dict(BASE_LISTING, payout_method="Bitcoin")
    assert validate_price_inputs(bad)


def test_dry_run_simulates_all_six_steps():
    bot = ViagogoBot(dry_run=True)
    res = bot.create_listing(BASE_LISTING)
    assert res["ok"] and res["dry_run"] and res["viagogo_listing_id"].startswith("DRY-")
    for step in ("1/6 Sell search", "2/6 Quantity", "3/6 ListingNotes",
                 "4/6 DeliveryDetails", "5/6 SeatDetails", "6/6 PriceDetails"):
        assert any(step in entry for entry in bot.log), bot.log


def test_dry_run_refuses_missing_face_value():
    bot = ViagogoBot(dry_run=True)
    res = bot.create_listing(dict(BASE_LISTING, face_price=0))
    assert not res["ok"]
    assert "face_price" in res["error"]


def test_dry_run_warns_but_simulates_missing_payout_email():
    # UI-created listings carry no payout info yet; dry-run warns, the
    # LIVE pre-flight in step 6 still refuses outright.
    bot = ViagogoBot(dry_run=True)
    listing = dict(BASE_LISTING, paypal_email="")
    res = bot.create_listing(listing)
    assert res["ok"] and res["viagogo_listing_id"].startswith("DRY-")
    assert any("warning" in e.lower() for e in bot.log)
    assert validate_price_inputs(listing)  # live gate would still refuse


def test_generic_defaults():
    # Generic listing defaults observed live: row Not Specified, seats blank,
    # delivery Mobile Ticket Transfer, storage Unknown, seller Normal.
    assert DEFAULTS["row"] == "Not Specified"
    assert DEFAULTS["delivery_method"] == "Mobile Ticket Transfer"
    assert DEFAULTS["tickets_stored"] == "Unknown"
    assert DEFAULTS["seller_type"] == "Normal seller (I am not a trader)"
    assert "first_seat" not in BASE_LISTING and "last_seat" not in BASE_LISTING
