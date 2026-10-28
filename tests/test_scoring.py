"""Unit tests for heuristic opportunity scoring (scoring.py, NO ML).

Every expected number is hand-computed from the rules R1-R12 in
scoring.py — if a rule changes, these tests must change with it.
Run:  python -m pytest tests/test_scoring.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scoring import (best_timing, confidence_score, crosses_threshold,
                     demand_level, rank_opportunities, recommended_price,
                     risk_level, score_opportunity)

RULES = {"min_price": 50, "max_price": 500, "round_to": 0.99}


def snap(**kw):
    base = {"event_name": "Test Event", "category": "concert", "section": "General",
            "currency": "GBP", "lowest_price": 200, "avg_price": 210,
            "listings_count": 8, "people_searching": 200,
            "recent_sold_prices": [190, 205], "days_to_event": 10}
    base.update(kw)
    return base


def test_high_demand_premium_pricing():
    # R3: High demand +10% over market 200 -> 220 -> .99 = 219.99
    opp = score_opportunity(snap(), buy_cost=100, quantity=2, rules=RULES)
    assert opp["demand"] == "High"
    assert opp["recommended_price"] == 219.99
    assert opp["estimated_profit_per_ticket"] == 97.99  # 219.99*0.9 - 100
    assert opp["estimated_profit"] == 195.98
    assert opp["profit_margin_pct"] == 98.0
    assert opp["confidence"] == 100
    assert opp["risk"] == "Low"
    assert opp["best_timing"] == "list now"


def test_low_demand_caution_and_crowded_market():
    # R3 Low: no premium; R4 >20 listings: -5% -> 100*0.95=95 -> 94.99
    opp = score_opportunity(snap(lowest_price=100, avg_price=105, listings_count=40,
                                 people_searching=10, recent_sold_prices=[],
                                 days_to_event=20), buy_cost=80, quantity=2, rules=RULES)
    assert opp["demand"] == "Low"
    assert opp["recommended_price"] == 94.99
    assert opp["estimated_profit_per_ticket"] == 5.49  # 94.99*0.9 - 80
    assert opp["profit_margin_pct"] == 6.9
    assert opp["risk"] == "High"  # margin < 10%
    assert opp["confidence"] == 90  # -10 for no sold prices
    assert opp["best_timing"] == "list now at market price, no premium"


def test_scarce_listings_boost():
    # R8: people 60 / listings 3 = ratio 20 -> High demand (+10%, not +5%);
    # R4 <=5 listings +5%: 150*1.10*1.05=173.25 -> 172.99
    opp = score_opportunity(snap(lowest_price=150, avg_price=160, listings_count=3,
                                 people_searching=60, days_to_event=20),
                            buy_cost=100, quantity=2, rules=RULES)
    assert opp["demand"] == "High"
    assert opp["recommended_price"] == 172.99
    assert opp["estimated_profit_per_ticket"] == 55.69
    assert opp["profit_margin_pct"] == 55.7


def test_no_data_low_confidence():
    # R10: every penalty applies -> confidence 0, no price, no profit.
    opp = score_opportunity({}, buy_cost=None, quantity=2, rules=RULES)
    assert opp["confidence"] == 0
    assert opp["current_market_price"] is None
    assert opp["recommended_price"] is None
    assert opp["estimated_profit"] is None
    assert opp["risk"] == "High"
    assert opp["best_timing"] == "wait — collect more data"


def test_fee_and_profit_math():
    # fee 0%: 200 -> 199.99, profit 99.99; fee 20%: profit 59.99
    opp0 = score_opportunity(snap(lowest_price=200, listings_count=10,
                                  people_searching=10, recent_sold_prices=[180]),
                             buy_cost=100, quantity=1, fee_pct=0, rules=RULES)
    assert opp0["estimated_profit_per_ticket"] == 99.99
    assert opp0["profit_margin_pct"] == 100.0
    opp20 = score_opportunity(snap(lowest_price=200, listings_count=10,
                                   people_searching=10, recent_sold_prices=[180]),
                              buy_cost=100, quantity=1, fee_pct=20, rules=RULES)
    assert opp20["estimated_profit_per_ticket"] == 59.99


def test_min_price_clamp():
    rules = {"min_price": 100, "max_price": 500, "round_to": 0.99}
    opp = score_opportunity(snap(lowest_price=60, listings_count=10,
                                 people_searching=10, recent_sold_prices=[55]),
                            buy_cost=10, quantity=1, rules=rules)
    assert opp["recommended_price"] == 100.0  # clamped to min
    assert any("min-price clamp" in n for n in opp["notes"])


def test_max_price_clamp():
    opp = score_opportunity(snap(lowest_price=1000, avg_price=1000, listings_count=10,
                                 people_searching=200, recent_sold_prices=[900]),
                            buy_cost=100, quantity=1, rules=RULES)
    assert opp["recommended_price"] == 499.99  # clamped to max, then .99
    assert any("max-price clamp" in n for n in opp["notes"])


def test_urgency_premium_near_event():
    # R5: days<=7 + High demand -> extra +5%: 100*1.10*1.05=115.50 -> 114.99
    opp = score_opportunity(snap(lowest_price=100, avg_price=100, listings_count=10,
                                 people_searching=200, recent_sold_prices=[95],
                                 days_to_event=5),
                            buy_cost=50, quantity=1, rules=RULES)
    assert opp["recommended_price"] == 114.99
    assert any("urgency premium" in n for n in opp["notes"])


def test_demand_levels():
    assert demand_level({"people_searching": 200, "listings_count": 8}) == "High"
    assert demand_level({"people_searching": 100, "listings_count": 5}) == "High"  # ratio 20
    assert demand_level({"people_searching": 60, "listings_count": 10}) == "Medium"
    assert demand_level({"people_searching": 10, "listings_count": 40}) == "Low"
    assert demand_level({}) == "Low"


def test_confidence_penalties():
    full = snap()
    assert confidence_score(full, 100) == 100
    assert confidence_score({**full, "lowest_price": None}, 100) == 60
    assert confidence_score(full, None) == 80
    assert confidence_score({}, None) == 0


def test_risk_levels():
    assert risk_level(50.0, "High", {"listings_count": 5, "days_to_event": 20}, 90) == "Low"
    assert risk_level(20.0, "Medium", {"listings_count": 10, "days_to_event": 20}, 90) == "Medium"
    assert risk_level(5.0, "High", {"listings_count": 5, "days_to_event": 20}, 90) == "High"
    assert risk_level(50.0, "High", {"listings_count": 5, "days_to_event": 20}, 30) == "High"
    assert risk_level(50.0, "High", {"listings_count": 5, "days_to_event": 2}, 90) == "High"


def test_best_timing_rules():
    assert best_timing("High", {"days_to_event": 5}, 90) == "list now"
    assert best_timing("High", {"days_to_event": 30}, 90) == "list now at premium, monitor weekly"
    assert best_timing("Low", {"days_to_event": 40}, 90) == "wait — monitor, list closer to event"
    assert best_timing("Low", {"days_to_event": 10}, 90) == "list now at market price, no premium"
    assert best_timing("High", {"days_to_event": 5}, 20) == "wait — collect more data"


def test_ranking_prefers_profit_times_confidence():
    # Big profit + LOW confidence (50) ranks BELOW solid profit + HIGH confidence.
    # big: market 250, no avg/listings/people/sold data -> rec 249.99,
    # profit 124.99, confidence 50 -> rank 62.50
    big = score_opportunity({"event_name": "Big", "lowest_price": 250, "avg_price": None,
                             "listings_count": None, "people_searching": None,
                             "recent_sold_prices": [], "days_to_event": 20},
                            buy_cost=100, quantity=1, rules=RULES)
    solid = score_opportunity(snap(lowest_price=200, listings_count=8,
                                   people_searching=200, recent_sold_prices=[190]),
                              buy_cost=100, quantity=1, rules=RULES)
    assert big["rank_score"] == 62.49  # 124.99 x 50% (float rounding)
    assert solid["rank_score"] == 97.99
    ranked = rank_opportunities([big, solid])
    assert ranked[0] is solid
    assert ranked[1] is big


def test_threshold_gate():
    good = {"estimated_profit": 120.0, "confidence": 80}
    assert crosses_threshold(good, min_profit=50, min_confidence=50) is True
    assert crosses_threshold({**good, "estimated_profit": 40}, 50, 50) is False
    assert crosses_threshold({**good, "confidence": 30}, 50, 50) is False
    assert crosses_threshold({"estimated_profit": None, "confidence": 90}, 50, 50) is False


def test_recommended_price_needs_market():
    price, notes = recommended_price({}, RULES)
    assert price is None
    assert notes
