"""Pricing rules for Viagogo listings — pure functions, no I/O.

Above-market pricing: listing = face_price * (1 + markup_pct/100),
clamped to [min_price, max_price], then rounded to the configured
ending (e.g. .99). All money is in the configured currency (GBP default).
"""
from __future__ import annotations

import math


def apply_markup(face_price: float, markup_pct: float) -> float:
    if face_price <= 0:
        raise ValueError("face_price must be > 0")
    if markup_pct < 0:
        raise ValueError("markup_pct must be >= 0")
    return face_price * (1 + markup_pct / 100.0)


def clamp_price(price: float, min_price: float | None, max_price: float | None) -> float:
    if min_price is not None and price < min_price:
        price = min_price
    if max_price is not None and price > max_price:
        price = max_price
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("min_price must be <= max_price")
    return price


def round_price(price: float, round_to: float | None = 0.99) -> float:
    """Round down to the nearest price ending in round_to's cents.

    round_to=0.99 -> 179.99, 180.0 -> 179.99; round_to=None -> 2dp.
    """
    if round_to is None:
        return round(price, 2)
    whole = math.floor(price)
    candidate = whole + round_to
    if candidate > price:
        candidate = (whole - 1) + round_to
    return round(candidate, 2)


def compute_listing_price(face_price: float, rules: dict) -> float:
    """Full pipeline: markup -> clamp -> round. Raises ValueError on bad input."""
    markup_pct = float(rules.get("markup_pct", 0))
    min_price = rules.get("min_price")
    max_price = rules.get("max_price")
    price = apply_markup(face_price, markup_pct)
    price = clamp_price(price, min_price, max_price)
    price = round_price(price, rules.get("round_to", 0.99))
    # Rounding down can dip just below min_price (e.g. min 50 -> 49.99);
    # re-clamp to min in that edge case, without re-rounding.
    if min_price is not None and price < min_price:
        price = float(min_price)
    return price


def validate_rules(rules: dict) -> list[str]:
    errors = []
    try:
        if float(rules.get("markup_pct", 0)) < 0:
            errors.append("markup_pct must be >= 0")
    except (TypeError, ValueError):
        errors.append("markup_pct must be a number")
    mn, mx = rules.get("min_price"), rules.get("max_price")
    if mn is not None and mx is not None:
        try:
            if float(mn) > float(mx):
                errors.append("min_price must be <= max_price")
        except (TypeError, ValueError):
            errors.append("min_price / max_price must be numbers")
    return errors
