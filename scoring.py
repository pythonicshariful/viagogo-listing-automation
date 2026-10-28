"""Opportunity scoring — HEURISTIC ONLY, no ML. Pure functions, no I/O.

Fayed (Fiverr client) clarified he does NOT want just a bulk-listing bot:
he wants a SMART system that finds profitable opportunities. This module
is that first step. It scores a market snapshot with transparent,
documented rules — every number can be traced to a rule below.

WHAT THIS IS NOT: it does NOT predict the future. There is no ML model
here and no historical training data exists (Fayed has none). ML
prediction is Phase 2 and needs weeks of snapshots collected by the
scanner first (see README / DELIVERY.md). Until then every score is a
heuristic over the LATEST snapshot only, plus the seller's own buy cost.

SCORING RULES (all in one place, so Fayed can ask for them to change):
  R1  Market price = lowest listing price if known, else average price,
      else None (no market price -> no profit estimate, low confidence).
  R2  Base recommended price = market price. Premium is ADDED, never
      assumed: the bot does NOT always list cheapest.
  R3  Demand premium: High demand -> +10% over market price,
      Medium -> +5%, Low -> +0% (list at market, do not undercut).
  R4  Scarcity premium: <=5 listings on the market -> +5%;
      6-20 listings -> +0%; >20 listings -> -5% (crowded market,
      premium is hard to hold).
  R5  Urgency: event within 7 days AND demand High -> +5% more
      (last-minute buyers pay more); event >60 days away -> +0%
      (plenty of time, no urgency premium).
  R6  Recommended price is clamped to [min_price, max_price] from the
      price rules and rounded to .99 (same helpers as pricing.py).
      If the clamp binds, the note says so.
  R7  Profit per ticket = recommended * (1 - fee_pct/100) - buy_cost.
      fee_pct is an ESTIMATE the seller must confirm (Viagogo seller
      fees vary; default 10%). Total profit = per-ticket profit x qty.
      Margin % = per-ticket profit / buy_cost x 100.
  R8  Demand level (from snapshot only):
        High   if people_searching >= 150, or people/listings >= 20
        Medium if people_searching >= 50,  or people/listings >= 5
        Low    otherwise (including no demand data at all).
  R9  Risk level:
        High   if margin < 10%, or confidence < 40, or listings > 30,
               or event < 3 days away (little time left to sell after
               buying), or no market price at all.
        Medium if margin 10-30%, or demand Low, or listings 21-30.
        Low    otherwise (margin > 30% + demand High + scarce).
  R10 Confidence 0-100 (starts at 100, subtract for missing data):
        no lowest price -40, no average price -10, no listings count -15,
        no demand text/people -15, no recent sold prices -10,
        no buy cost / face value -20. Never below 0, never above 100.
        A score with confidence < 40 should not be acted on alone.
  R11 Best timing:
        confidence < 40            -> "wait — collect more data"
        demand High + <=14 days    -> "list now"
        demand High + >14 days     -> "list now at premium, monitor weekly"
        demand Low  + >30 days     -> "wait — monitor, list closer to event"
        demand Low  + <=30 days    -> "list now at market price, no premium"
        otherwise                  -> "list now"
  R12 Ranking: opportunities sort by (profit_per_ticket x confidence/100)
      descending — a big profit with low confidence ranks below a solid
      profit with high confidence. The sort key is in the output as
      `rank_score` so it can be checked by hand.
"""
from __future__ import annotations

from pricing import clamp_price, round_price

DEFAULT_FEE_PCT = 10.0  # ESTIMATE — seller must confirm the real Viagogo fee
DEFAULT_MIN_CONFIDENCE = 50
DEFAULT_MIN_PROFIT = 50.0


def demand_level(snapshot: dict) -> str:
    """R8: High / Medium / Low from people-searching + listings count."""
    people = snapshot.get("people_searching")
    listings = snapshot.get("listings_count")
    if people is not None and people >= 150:
        return "High"
    if people is not None and listings:
        ratio = people / listings
        if ratio >= 20:
            return "High"
        if ratio >= 5:
            return "Medium"
    if people is not None and people >= 50:
        return "Medium"
    return "Low"


def confidence_score(snapshot: dict, buy_cost: float | None) -> int:
    """R10: 0-100, penalise every missing piece of data."""
    score = 100
    if snapshot.get("lowest_price") is None:
        score -= 40
    if snapshot.get("avg_price") is None:
        score -= 10
    if snapshot.get("listings_count") is None:
        score -= 15
    if snapshot.get("people_searching") is None:
        score -= 15
    if not snapshot.get("recent_sold_prices"):
        score -= 10
    if buy_cost is None or buy_cost <= 0:
        score -= 20
    return max(0, min(100, score))


def recommended_price(snapshot: dict, rules: dict | None = None) -> tuple[float | None, list[str]]:
    """R2-R6: market price + demand/scarcity/urgency premiums, clamped, .99.

    Returns (price or None, notes). None when no market price is known.
    """
    rules = rules or {}
    market = snapshot.get("lowest_price") or snapshot.get("avg_price")
    if market is None:
        return None, ["no market price in snapshot — cannot recommend a price"]
    notes: list[str] = []
    price = float(market)
    demand = demand_level(snapshot)
    if demand == "High":
        price *= 1.10
        notes.append("High demand: +10% premium over market")
    elif demand == "Medium":
        price *= 1.05
        notes.append("Medium demand: +5% premium over market")
    else:
        notes.append("Low demand: list at market price, no premium")
    listings = snapshot.get("listings_count")
    if listings is not None and listings <= 5:
        price *= 1.05
        notes.append("Scarce listings (<=5): +5% premium")
    elif listings is not None and listings > 20:
        price *= 0.95
        notes.append("Crowded market (>20 listings): -5%")
    days = snapshot.get("days_to_event")
    if days is not None and days <= 7 and demand == "High":
        price *= 1.05
        notes.append("Event within 7 days + high demand: +5% urgency premium")
    price = clamp_price(price, rules.get("min_price"), rules.get("max_price"))
    if rules.get("min_price") is not None and price <= float(rules["min_price"]):
        notes.append("recommended price hit the min-price clamp")
    if rules.get("max_price") is not None and price >= float(rules["max_price"]):
        notes.append("recommended price hit the max-price clamp")
    price = round_price(price, rules.get("round_to", 0.99))
    # Rounding down can dip just below min_price (e.g. min 100 -> 99.99);
    # re-clamp to min in that edge case, without re-rounding (as pricing.py does).
    if rules.get("min_price") is not None and price < float(rules["min_price"]):
        price = float(rules["min_price"])
    return price, notes


def risk_level(margin_pct: float | None, demand: str, snapshot: dict, confidence: int) -> str:
    """R9: High / Medium / Low."""
    listings = snapshot.get("listings_count")
    days = snapshot.get("days_to_event")
    if margin_pct is None or margin_pct < 10 or confidence < 40:
        return "High"
    if listings is not None and listings > 30:
        return "High"
    if days is not None and days < 3:
        return "High"
    if margin_pct <= 30 or demand == "Low":
        return "Medium"
    if listings is not None and 21 <= listings <= 30:
        return "Medium"
    return "Low"


def best_timing(demand: str, snapshot: dict, confidence: int) -> str:
    """R11: plain-language timing advice."""
    days = snapshot.get("days_to_event")
    if confidence < 40:
        return "wait — collect more data"
    if demand == "High":
        if days is not None and days <= 14:
            return "list now"
        return "list now at premium, monitor weekly"
    if demand == "Low":
        if days is not None and days > 30:
            return "wait — monitor, list closer to event"
        return "list now at market price, no premium"
    return "list now"


def score_opportunity(snapshot: dict, buy_cost: float | None = None,
                      quantity: int = 2, fee_pct: float = DEFAULT_FEE_PCT,
                      rules: dict | None = None) -> dict:
    """Score ONE snapshot. All money in the snapshot's currency.

    snapshot keys (all optional except event_name): event_name, category,
    section, event_url, currency, lowest_price, avg_price, listings_count,
    people_searching, recent_sold_prices (list), days_to_event.
    buy_cost = what Fayed expects to pay per ticket (face value if unknown
    is NOT assumed — pass None and profit is left blank).
    """
    rules = rules or {}
    demand = demand_level(snapshot)
    confidence = confidence_score(snapshot, buy_cost)
    rec_price, notes = recommended_price(snapshot, rules)
    market = snapshot.get("lowest_price") or snapshot.get("avg_price")

    profit_per = None
    profit_total = None
    margin_pct = None
    if rec_price is not None and buy_cost:
        profit_per = round(rec_price * (1 - fee_pct / 100.0) - float(buy_cost), 2)
        profit_total = round(profit_per * int(quantity), 2)
        margin_pct = round(profit_per / float(buy_cost) * 100, 1) if buy_cost else None
    risk = risk_level(margin_pct, demand, snapshot, confidence)
    timing = best_timing(demand, snapshot, confidence)
    rank_score = round((profit_per or 0) * confidence / 100.0, 2)

    return {
        "event_name": snapshot.get("event_name", "Unknown event"),
        "event_url": snapshot.get("event_url"),
        "category": snapshot.get("category", "football"),
        "section": snapshot.get("section", "General"),
        "currency": snapshot.get("currency", "GBP"),
        "quantity": int(quantity),
        "current_market_price": market,
        "lowest_price": snapshot.get("lowest_price"),
        "avg_price": snapshot.get("avg_price"),
        "listings_count": snapshot.get("listings_count"),
        "people_searching": snapshot.get("people_searching"),
        "recent_sold_prices": snapshot.get("recent_sold_prices") or [],
        "days_to_event": snapshot.get("days_to_event"),
        "buy_cost": buy_cost,
        "fee_pct": fee_pct,
        "recommended_price": rec_price,
        "estimated_profit_per_ticket": profit_per,
        "estimated_profit": profit_total,
        "profit_margin_pct": margin_pct,
        "demand": demand,
        "risk": risk,
        "confidence": confidence,
        "best_timing": timing,
        "rank_score": rank_score,
        "notes": notes,
        "snapshot_at": snapshot.get("snapshot_at"),
        "source": snapshot.get("source", "unknown"),
    }


def rank_opportunities(items: list[dict]) -> list[dict]:
    """R12: best first by rank_score (profit x confidence)."""
    return sorted(items, key=lambda o: o.get("rank_score", 0), reverse=True)


def crosses_threshold(opportunity: dict, min_profit: float = DEFAULT_MIN_PROFIT,
                     min_confidence: int = DEFAULT_MIN_CONFIDENCE) -> bool:
    """Alert gate: only notify when profit AND confidence both clear the bar."""
    profit = opportunity.get("estimated_profit")
    return (profit is not None and profit >= min_profit
            and opportunity.get("confidence", 0) >= min_confidence)
