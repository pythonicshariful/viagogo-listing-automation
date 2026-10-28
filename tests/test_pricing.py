import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pricing import compute_listing_price, validate_rules  # noqa: E402


def test_markup_and_rounding():
    # 100 face, +80% = 180 -> 179.99
    assert compute_listing_price(100, {"markup_pct": 80, "min_price": 50, "max_price": 500}) == 179.99


def test_max_clamp():
    # 200 face, +200% = 600, capped at 500 -> 499.99
    assert compute_listing_price(200, {"markup_pct": 200, "min_price": 50, "max_price": 500}) == 499.99


def test_min_clamp():
    # 10 face, +10% = 11, floored at 50
    assert compute_listing_price(10, {"markup_pct": 10, "min_price": 50, "max_price": 500}) == 50.0


def test_bad_rules():
    assert validate_rules({"markup_pct": -5})
    assert validate_rules({"markup_pct": 50, "min_price": 600, "max_price": 500})
    assert not validate_rules({"markup_pct": 80, "min_price": 50, "max_price": 500})
