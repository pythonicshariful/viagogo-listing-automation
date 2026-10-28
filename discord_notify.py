"""Discord notifications via webhook — sale alerts + test message.

No Discord library needed; a plain POST to the webhook URL.
In DRY-RUN (or with no webhook configured) nothing is sent to Discord;
the payload is returned so the caller / UI can show what WOULD be sent.

Security: the webhook URL is NEVER logged. It is validated (format only)
before any send attempt, and sends are retried at most 3 times with
backoff. A failed send returns an error dict — it never raises into the API.
"""
from __future__ import annotations

import logging
import re
import time

import requests

logger = logging.getLogger("viagogo-listing-automation.discord")
TIMEOUT = 10
MAX_ATTEMPTS = 3
_WEBHOOK_RE = re.compile(r"^https://discord(?:app)?\.com/api/webhooks/\d+/[\w\-]+$")


def is_valid_webhook_url(url: str | None) -> bool:
    """Format check only — does not prove the webhook exists or is live."""
    if not isinstance(url, str):
        return False
    return bool(_WEBHOOK_RE.match(url.strip()))


def _post(webhook_url: str, payload: dict, dry_run: bool) -> dict:
    if dry_run or not webhook_url:
        return {"sent": False, "dry_run": dry_run,
                "reason": "no webhook configured" if not webhook_url else "dry_run",
                "payload": payload}
    if not is_valid_webhook_url(webhook_url):
        return {"sent": False, "error": "webhook URL must be https://discord.com/api/webhooks/<id>/<token>"}
    last_error: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            logger.info("Discord notification sent (attempt %d, status %s)", attempt, resp.status_code)
            return {"sent": True, "status_code": resp.status_code}
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("Discord send failed (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)  # 2s, then 4s
    return {"sent": False, "error": f"Discord send failed after {MAX_ATTEMPTS} attempts: {last_error}"}


def sale_payload(listing: dict, sale_price: float | None = None) -> dict:
    price = sale_price if sale_price is not None else listing.get("listing_price")
    return {
        "content": f"🎟️ **SALE on Viagogo!** {listing.get('event_name')} — "
                   f"{listing.get('section', 'General')} x{listing.get('quantity', 1)} "
                   f"sold for {listing.get('currency', 'GBP')} {price}. "
                   f"Buy the ticket now and deliver it. Listing ID: {listing.get('id')}",
        "embeds": [{
            "title": "Viagogo sale — action needed",
            "fields": [
                {"name": "Event", "value": str(listing.get("event_name")), "inline": True},
                {"name": "Section", "value": str(listing.get("section", "General")), "inline": True},
                {"name": "Qty", "value": str(listing.get("quantity", 1)), "inline": True},
                {"name": "Sale price", "value": f"{listing.get('currency', 'GBP')} {price}", "inline": True},
                {"name": "Listing ID", "value": str(listing.get("id")), "inline": True},
            ],
        }],
    }


def notify_sale(webhook_url: str, listing: dict, sale_price: float | None = None, dry_run: bool = False) -> dict:
    return _post(webhook_url, sale_payload(listing, sale_price), dry_run)


def opportunity_payload(opportunity: dict) -> dict:
    """Opportunity alert — event, prices, profit, confidence. No secrets."""
    cur = opportunity.get("currency", "GBP")
    return {
        "content": f"💡 **Viagogo opportunity!** {opportunity.get('event_name')} — "
                   f"{opportunity.get('section', 'General')} | market {cur} "
                   f"{opportunity.get('current_market_price')} → list at {cur} "
                   f"{opportunity.get('recommended_price')} | est. profit {cur} "
                   f"{opportunity.get('estimated_profit')} ({opportunity.get('profit_margin_pct')}%) "
                   f"| demand {opportunity.get('demand')} / risk {opportunity.get('risk')} "
                   f"| confidence {opportunity.get('confidence')}/100 — {opportunity.get('best_timing')}",
        "embeds": [{
            "title": "Viagogo opportunity — ranked by profit × confidence",
            "fields": [
                {"name": "Event", "value": str(opportunity.get("event_name")), "inline": True},
                {"name": "Section", "value": str(opportunity.get("section", "General")), "inline": True},
                {"name": "Market price", "value": f"{cur} {opportunity.get('current_market_price')}", "inline": True},
                {"name": "Recommended price", "value": f"{cur} {opportunity.get('recommended_price')}", "inline": True},
                {"name": "Est. profit (total)", "value": f"{cur} {opportunity.get('estimated_profit')} ({opportunity.get('profit_margin_pct')}%)", "inline": True},
                {"name": "Demand / Risk", "value": f"{opportunity.get('demand')} / {opportunity.get('risk')}", "inline": True},
                {"name": "Confidence", "value": f"{opportunity.get('confidence')}/100", "inline": True},
                {"name": "Best timing", "value": str(opportunity.get("best_timing")), "inline": True},
            ],
        }],
    }


def notify_opportunity(webhook_url: str, opportunity: dict, dry_run: bool = False) -> dict:
    return _post(webhook_url, opportunity_payload(opportunity), dry_run)


def send_test(webhook_url: str, dry_run: bool = False) -> dict:
    payload = {"content": "✅ Viagogo Listing Automation — Discord test. If you see this, sale alerts will reach this channel."}
    return _post(webhook_url, payload, dry_run)
