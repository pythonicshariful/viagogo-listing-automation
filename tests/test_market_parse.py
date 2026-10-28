"""Unit tests for market page-text parsing (market.py, no browser, no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market import parse_listings_count, parse_people_searching, parse_prices, parse_snapshot_text

TEXT = """
Metallica - 2 Day Pass. 152 people are currently searching for tickets
to this event. Tickets from $860. Cheapest $895. 12 tickets available.
Section 105 sold $860 each, $900 each.
"""


def test_parse_prices():
    assert parse_prices(TEXT) == [860.0, 895.0, 860.0, 900.0]
    assert parse_prices("no prices here") == []
    assert parse_prices("£1,299.50 and €99") == [1299.5, 99.0]


def test_parse_people_searching():
    assert parse_people_searching(TEXT) == 152
    assert parse_people_searching("no demand text") is None
    assert parse_people_searching("1,234 people are searching") == 1234


def test_parse_listings_count():
    assert parse_listings_count(TEXT) == 12
    assert parse_listings_count("37 listings available") == 37
    assert parse_listings_count("nothing here") is None


def test_parse_snapshot_text():
    snap = parse_snapshot_text(TEXT, {"event_name": "Metallica", "event_url": "https://example.com/x",
                                      "category": "concert", "days_to_event": 1})
    assert snap["lowest_price"] == 860.0
    assert snap["avg_price"] == 878.75
    assert snap["listings_count"] == 12
    assert snap["people_searching"] == 152
    assert snap["source"] == "live"


def test_parse_snapshot_text_empty_never_crashes():
    snap = parse_snapshot_text("", {"event_name": "Empty"})
    assert snap["lowest_price"] is None
    assert snap["avg_price"] is None
    assert snap["listings_count"] is None
    assert snap["people_searching"] is None
