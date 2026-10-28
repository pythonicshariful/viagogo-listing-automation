"""Sale detection tests (v1.4.0) — real detection, no Viagogo account.

Covers the pure parser (sold-found + none-sold against the mock sales
pages), the dry-run / no-session "not available" contract (never fakes
a sale), and the real-browser flow against both mock sales pages
(skipped cleanly if Chromium is missing).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from viagogo_bot import (  # noqa: E402
    ViagogoBot,
    find_sold_in_text,
    parse_sales_html,
)

BASE = Path(__file__).resolve().parents[1]
SALES_MOCK = (BASE / "mock" / "mock_sales_portal.html").as_uri()
SALES_NONE_MOCK = (BASE / "mock" / "mock_sales_portal_none_sold.html").as_uri()

LISTINGS = [
    {"id": 1, "event_name": "Metallica - 2 Day Pass", "section": "Section 105",
     "quantity": 2, "listing_price": 992.99, "currency": "USD"},
    {"id": 2, "event_name": "Coldplay - London", "section": "Standing",
     "quantity": 2, "listing_price": 179.99, "currency": "USD"},
    {"id": 3, "event_name": "Real Madrid vs FC Barcelona",
     "section": "General Admission", "quantity": 2,
     "listing_price": 179.99, "currency": "GBP"},
]


def _mock_html(name: str) -> str:
    return (BASE / "mock" / name).read_text(encoding="utf-8")


def test_parse_sales_html_finds_the_one_sold_listing():
    sales = parse_sales_html(_mock_html("mock_sales_portal.html"), LISTINGS)
    assert len(sales) == 1, sales
    sale = sales[0]
    assert sale["listing_id"] == 1
    assert sale["sale_price"] == 992.99
    assert sale["method"] == "page-text-scan"
    assert "Metallica" in sale["matched_text"]


def test_parse_sales_html_none_sold_finds_nothing():
    sales = parse_sales_html(_mock_html("mock_sales_portal_none_sold.html"), LISTINGS)
    assert sales == []


def test_find_sold_in_text_needs_sold_marker_nearby():
    # Event name present, but no "sold" anywhere near it -> no sale.
    text = "Coldplay - London\nStanding\n$179.99\nActive\n—"
    assert find_sold_in_text(text, LISTINGS) == []
    # Event name absent entirely -> no sale, even with "Sold" on the page.
    text = "Some Other Event\nSold\n$10.00"
    assert find_sold_in_text(text, LISTINGS) == []
    # Sold marker far away from the name (>200 chars) -> no sale.
    text = "Metallica - 2 Day Pass\n" + ("x" * 300) + "\nSold"
    assert find_sold_in_text(text, LISTINGS) == []


def test_check_sales_dry_run_is_not_available_and_never_fakes():
    bot = ViagogoBot(dry_run=True)
    result = bot.check_sales(LISTINGS)
    assert result["available"] is False
    assert result["sales"] == []
    assert "dry-run" in result["reason"].lower()


def test_check_sales_live_without_session_is_not_available():
    bot = ViagogoBot(dry_run=False, live_mode=True, live_confirmed=True,
                     session_file=str(BASE / "does-not-exist-auth_state.json"))
    result = bot.check_sales(LISTINGS)
    assert result["available"] is False
    assert result["sales"] == []
    assert "session" in result["reason"].lower()


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _browser_available(), reason="Chromium not installed")
def test_browser_mock_sales_page_finds_sold_listing():
    bot = ViagogoBot(dry_run=True, mock_sales_url=SALES_MOCK)
    result = bot.check_sales(LISTINGS)
    assert result["available"] is True, result
    assert len(result["sales"]) == 1, result
    sale = result["sales"][0]
    assert sale["listing_id"] == 1
    assert sale["sale_price"] == 992.99
    # Browser layers run first: exact text match on the table row.
    assert sale["method"] in {"exact-text-match", "partial-text-match", "page-text-scan"}
    assert any("exact-text-match" in e or "partial-text-match" in e or "page-text-scan" in e
               for e in bot.log)


@pytest.mark.skipif(not _browser_available(), reason="Chromium not installed")
def test_browser_mock_sales_page_none_sold_finds_nothing():
    bot = ViagogoBot(dry_run=True, mock_sales_url=SALES_NONE_MOCK)
    result = bot.check_sales(LISTINGS)
    assert result["available"] is True, result
    assert result["sales"] == []
