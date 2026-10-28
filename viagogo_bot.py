"""Viagogo seller-portal automation (Playwright, listing-ONLY — never buys).

Sell pipeline VERIFIED live (observed 2026-10-28, logged in, Metallica
sample event, draft ID in URL ?ID=<uuid>, NO listing was created):
  1. Sell search   https://sell.viagogo.com/selltickets
  2. Quantity      /Secure/Pipeline/Sell/TicketDetails/Quantity?ID=...
  3. ListingNotes  /Secure/Pipeline/Sell/TicketDetails/ListingNotes?ID=...
  4. DeliveryDetails /Secure/Pipeline/Sell/TicketDetails/DeliveryDetails?ID=...
  5. SeatDetails   /Secure/Pipeline/Sell/TicketDetails/SeatDetails?ID=...
  6. PriceDetails  /Secure/Pipeline/Sell/PriceDetails?ID=...
     -> button "Create Listing" (NOT "Publish").

STILL UNVERIFIED: the "Create Listing" click itself. It is gated by a
card-on-file requirement ("CREDIT OR DEBIT CARD — Add Card On File"), a
face-value input and a payout method. The bot REFUSES to proceed if any
of those is missing and NEVER enters card details. Do not run a live
bulk batch until one single listing has been created by hand on the
real portal and the click confirmed.

Selectors are label/text-based (get_by_role / get_by_label / get_by_text),
not fragile CSS, because the portal is React-rendered and pages load
blank for a few seconds — every step waits for its heading first.

Stealth (v1.2.1, stealth.py): randomised desktop UA/viewport, locale +
timezone matching the seller store, an init script hiding the usual
automation tells, character-by-character typing and small mouse moves
before clicks. It reduces detection risk but does NOT guarantee
invisibility. By default it NEVER bypasses a CAPTCHA / Cloudflare
challenge — if one appears the bot stops and raises
ChallengeDetectedError. OPTIONAL NopeCHA path (v1.2.2, captcha.py):
only when the operator enables it AND configures their own NopeCHA
API key does the bot attempt ONE solve per challenge page (Token API
first); solving a CAPTCHA may violate Viagogo's terms and increases
account-ban risk, and a Cloudflare interstitial (no sitekey) cannot
be solved by the Token API. With no key, behaviour is stop-on-challenge.

DRY-RUN (default): every action is logged and simulated. No form is ever
submitted, no listing is ever posted. A fake listing id DRY-<n> is returned.
LIVE requires: LIVE_MODE=True AND DRY_RUN=False AND a saved session file
AND LIVE_CONFIRM=yes (checked at app startup).

Security: session file contents are NEVER logged. Only action names and
listing ids are logged, never credentials, cookies or tokens.
"""
from __future__ import annotations

import logging
import os
import random
import re
import time
import urllib.parse
from pathlib import Path

from captcha import solver_from_env
from stealth import (
    ChallengeDetectedError,
    check_challenge_or_solve,
    click_like_human,
    new_stealth_context,
    type_like_human,
)

logger = logging.getLogger("viagogo-listing-automation.bot")

# ---------------------------------------------------------------------------
# Verified pipeline — sell.viagogo.com (observed live 2026-10-28).
# Locators are by accessible label / role / visible text, NOT by CSS class
# or data-testid, so a React re-render does not silently break them.
# ---------------------------------------------------------------------------
SELL_BASE = "https://sell.viagogo.com"
SELL_URL = f"{SELL_BASE}/selltickets"
PAGE_TIMEOUT_MS = int(os.environ.get("VIAGOGO_TIMEOUT_MS", "60000"))
ACTION_TIMEOUT_MS = 15000
MAX_ATTEMPTS = 3

# Defaults observed on the live pipeline for a generic listing.
DEFAULTS = {
    "sell_together": True,  # "Sell all of my tickets together"
    "no_restrictions": True,
    "about_you": "Neither of these",
    "seller_type": "Normal seller (I am not a trader)",
    "delivery_method": "Mobile Ticket Transfer",
    "tickets_stored": "Unknown",
    "row": "Not Specified",
    "seat_reason": "The primary site has not provided me with this information",
    "payout_method": "PayPal",
}

SELECTORS = {
    # Step 1 — Sell search (sell.viagogo.com/selltickets)
    "event_search_placeholder": "Search your event and start selling",
    "sell_tickets_button": "Sell my tickets",
    "list_tickets_link": "List Tickets",
    # Step 2 — Quantity (/TicketDetails/Quantity?ID=...)
    "quantity_heading": "Select quantity",
    "quantity_combobox": "Quantity",
    "sell_together_radio": "Sell all of my tickets together",
    "sell_any_quantity_radio": "Sell any quantity of my tickets",
    # Step 3 — ListingNotes (/TicketDetails/ListingNotes?ID=...)
    "listing_notes_heading": "Fill us in on your tickets",
    "no_restrictions_checkbox": "No restrictions",
    "about_you_neither": "Neither of these",
    "seller_type_normal": "Normal seller (I am not a trader)",
    # Step 4 — DeliveryDetails (/TicketDetails/DeliveryDetails?ID=...)
    # Delivery types are per-event: only use what the page offers.
    # Barcode / Paper / PDF / Pickup are NOT offered for every event —
    # never hardcode them.
    "delivery_heading": "Select ticket type and delivery method",
    "delivery_mobile_transfer": "Mobile Ticket Transfer",
    "delivery_mobile_tickets": "Mobile Tickets",
    "tickets_stored_unknown": "Unknown",
    # Step 5 — SeatDetails (/TicketDetails/SeatDetails?ID=...)
    "seat_details_heading": "Enter seat details",
    "section_combobox": "Section",
    "row_combobox": "Row",
    "first_seat_textbox": "First seat",
    "last_seat_textbox": "Last seat",
    "seat_reason_primary_site": "The primary site has not provided me with this information",
    # Step 6 — PriceDetails (/PriceDetails?ID=...)
    "price_heading": "Set your ticket price",
    "per_ticket_spinbutton": "Per ticket US$",
    "face_value_section": "ENTER FACE VALUE",
    "payout_combobox": "Select payout method",
    "paypal_email_textbox": "PayPal Account Email",
    "terms_checkbox": "Terms and Conditions",
    "create_listing_button": "Create Listing",
    # Card blocker — presence of this means Create Listing is disabled.
    "card_on_file_text": "Add Card On File",
    "card_section_text": "CREDIT OR DEBIT CARD",
    # Shared
    "continue_button": "Continue",
}


def human_delay(a: float = 1.0, b: float = 3.0) -> None:
    time.sleep(random.uniform(a, b))


def _retry(fn, what: str):
    """Run fn up to 3 times with exponential backoff. Logs each attempt.

    A detected CAPTCHA / Cloudflare challenge is NEVER retried — the bot
    stops immediately (see stealth.ChallengeDetectedError)."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except ChallengeDetectedError:
            raise
        except Exception as exc:  # noqa: BLE001 — retried, then re-raised
            last_exc = exc
            logger.warning("%s failed (attempt %d/%d): %s", what, attempt, MAX_ATTEMPTS, exc)
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** attempt)  # 2s, then 4s
    assert last_exc is not None
    raise last_exc


def validate_price_inputs(listing: dict) -> list[str]:
    """Pure pre-flight check for step 6 (no browser needed).

    Returns a list of missing/invalid items; empty means OK to proceed
    to the price page. The card-on-file check needs the live page and is
    done separately by _has_card_blocker().
    """
    errors: list[str] = []
    face = listing.get("face_price")
    if face is None or not isinstance(face, (int, float)) or face <= 0:
        errors.append("face_price is required (face value must be entered on PriceDetails)")
    if not listing.get("listing_price"):
        errors.append("listing_price is required")
    payout = listing.get("payout_method") or DEFAULTS["payout_method"]
    if payout not in {"PayPal", "Direct deposit"}:
        errors.append(f"payout_method must be 'PayPal' or 'Direct deposit', got {payout!r}")
    if payout == "PayPal" and not listing.get("paypal_email"):
        errors.append("paypal_email is required when payout_method is PayPal")
    return errors


def _draft_id_from_url(url: str) -> str | None:
    """The pipeline carries the draft id as ?ID=<uuid> in every step URL."""
    try:
        return urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("ID", [None])[0]
    except Exception:
        return None


class ViagogoBot:
    """Thin wrapper around Playwright. All live methods raise in dry-run
    unless they are explicitly simulation-safe (create_listing simulates)."""

    def __init__(self, dry_run: bool = True, headless: bool = True,
                 proxy: str | None = None, session_file: str | None = None,
                 mock_url: str | None = None, captcha_solver=None):
        self.dry_run = dry_run
        self.headless = headless
        self.proxy = proxy or os.environ.get("VIAGOGO_PROXY") or None
        self.session_file = session_file or os.environ.get("VIAGOGO_SESSION_FILE", "auth_state.json")
        self.mock_url = mock_url or os.environ.get("MOCK_PORTAL_URL") or None
        # Optional NopeCHA solver (captcha.py): from the environment by
        # default (NOPECHA_API_KEY + NOPECHA_ENABLED); the web app passes
        # one built from the dashboard config instead. With no key it is
        # inert — challenge pages still stop the bot.
        self._captcha_solver = (captcha_solver if captcha_solver is not None
                                else solver_from_env())
        self._dry_counter = 0
        self.log: list[str] = []

    def _note(self, msg: str) -> None:
        self.log.append(msg)
        logger.info("[bot] %s", msg)

    def _require_live(self) -> None:
        if self.dry_run:
            raise RuntimeError("Refusing live browser action in DRY-RUN mode")
        if os.environ.get("LIVE_MODE", "False").lower() != "true":
            raise RuntimeError("LIVE_MODE=True is required for any live action")
        if os.environ.get("LIVE_CONFIRM", "").lower() != "yes":
            raise RuntimeError("LIVE_CONFIRM=yes is required for any live action")
        if not Path(self.session_file).exists():
            raise RuntimeError(f"Saved session not found: {self.session_file} — log in once and save it (see DELIVERY.md)")

    def _launch(self):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        kwargs: dict = {"headless": self.headless}
        if self.proxy:
            # Proxy is set at browser launch, so it keeps working with
            # stealth on (stealth only configures the context).
            kwargs["proxy"] = {"server": self.proxy}
        browser = pw.chromium.launch(**kwargs)
        storage_state = self.session_file if Path(self.session_file).exists() else None
        context = new_stealth_context(browser, storage_state=storage_state)
        return pw, browser, context

    def _goto(self, page, url: str) -> None:
        """Page load with a challenge gate: if Viagogo shows a CAPTCHA /
        Cloudflare challenge, try ONE NopeCHA solve only when the solver
        is enabled and configured — otherwise stop immediately (never
        solve or bypass it)."""
        page.goto(url, timeout=PAGE_TIMEOUT_MS)
        check_challenge_or_solve(page, self._captcha_solver)

    # -- shared page helpers (label/text-based) ------------------------------
    @staticmethod
    def _wait_heading(page, text: str) -> None:
        # Pages load blank for a few seconds — wait generously for the heading.
        page.get_by_role("heading", name=text).first.wait_for(timeout=PAGE_TIMEOUT_MS)

    @staticmethod
    def _click_continue(page) -> None:
        # Small random mouse move before the click (stealth jitter); the
        # locator itself is unchanged.
        click_like_human(
            page, page.get_by_role("button", name=SELECTORS["continue_button"], exact=False),
            timeout=ACTION_TIMEOUT_MS)

    @staticmethod
    def _check_radio_if_present(page, label: str) -> bool:
        loc = page.get_by_role("radio", name=label, exact=False)
        if loc.count() == 0:
            return False
        loc.first.check(timeout=ACTION_TIMEOUT_MS)
        return True

    @staticmethod
    def _check_box_if_present(page, label: str) -> bool:
        loc = page.get_by_role("checkbox", name=label, exact=False)
        if loc.count() == 0:
            return False
        loc.first.check(timeout=ACTION_TIMEOUT_MS)
        return True

    @staticmethod
    def _has_card_blocker(page) -> bool:
        """True if the page asks to add a card on file — Create Listing is
        disabled until a card is added. The bot must refuse, never enter
        card details."""
        return (
            page.get_by_text(SELECTORS["card_on_file_text"], exact=False).count() > 0
            or page.get_by_text(SELECTORS["card_section_text"], exact=False).count() > 0
        )

    def _require_live_or_mock(self) -> None:
        if self.mock_url:
            return  # mock portal is safe to drive with a real browser
        self._require_live()

    # -- public actions ------------------------------------------------------
    def search_event(self, query: str, category: str = "football") -> list[dict]:
        """Dry-run: return a fake match. Live/mock: open the Sell page and search."""
        if self.dry_run and not self.mock_url:
            self._note(f"DRY-RUN search_event({query!r}, {category}) -> 1 fake match")
            return [{"event_name": query, "event_url": "https://www.viagogo.com/DRY-RUN-EVENT",
                     "category": category}]
        self._require_live_or_mock()

        def _do():
            pw, browser, context = self._launch()
            try:
                page = context.new_page()
                self._goto(page, self.mock_url or SELL_URL)
                human_delay()
                type_like_human(
                    page.get_by_placeholder(SELECTORS["event_search_placeholder"]), query,
                    timeout=ACTION_TIMEOUT_MS)
                human_delay()
                return [{"event_name": query, "event_url": page.url, "category": category}]
            finally:
                browser.close(); pw.stop()

        return _retry(_do, "search_event")

    # -- the 6-step pipeline -------------------------------------------------
    def _step1_sell_search(self, page, listing: dict) -> None:
        """Sell search -> FindEvent -> List Tickets. Leaves the browser on
        the Quantity step (draft ?ID=... in the URL)."""
        self._note("step 1/6 Sell search: sell.viagogo.com/selltickets")
        event_url = listing.get("event_url") or ""
        if event_url and "FindEvent" in event_url:
            self._goto(page, event_url)
        else:
            self._goto(page, self.mock_url or SELL_URL)
            human_delay()
            type_like_human(
                page.get_by_placeholder(SELECTORS["event_search_placeholder"]),
                listing["event_name"], timeout=ACTION_TIMEOUT_MS)
            human_delay()
            # "Sell my tickets" focuses the search box / shows results.
            btn = page.get_by_role("button", name=SELECTORS["sell_tickets_button"], exact=False)
            if btn.count():
                click_like_human(page, btn, timeout=ACTION_TIMEOUT_MS)
            human_delay()
        link = page.get_by_role("link", name=SELECTORS["list_tickets_link"], exact=False)
        if link.count() == 0:
            # Mock portal / some layouts render it as a button.
            link = page.get_by_role("button", name=SELECTORS["list_tickets_link"], exact=False)
        click_like_human(page, link, timeout=ACTION_TIMEOUT_MS)
        check_challenge_or_solve(page, self._captcha_solver)
        human_delay()
        draft = _draft_id_from_url(page.url)
        self._note(f"step 1/6 done: draft ID={draft or 'n/a (mock)'} url={page.url}")

    def _step2_quantity(self, page, listing: dict) -> None:
        self._wait_heading(page, SELECTORS["quantity_heading"])
        qty = int(listing.get("quantity", 2))
        if not 1 <= qty <= 30:
            raise ValueError(f"quantity must be 1-30 (Viagogo limit), got {qty}")
        self._note(f"step 2/6 Quantity: {qty} tickets")
        page.get_by_role("combobox", name=SELECTORS["quantity_combobox"]).first.select_option(
            str(qty), timeout=ACTION_TIMEOUT_MS)
        together = listing.get("sell_together", DEFAULTS["sell_together"])
        label = (SELECTORS["sell_together_radio"] if together
                 else SELECTORS["sell_any_quantity_radio"])
        page.get_by_role("radio", name=label, exact=False).first.check(timeout=ACTION_TIMEOUT_MS)
        human_delay(0.5, 1.5)
        self._click_continue(page)
        human_delay()

    def _step3_listing_notes(self, page, listing: dict) -> None:
        self._wait_heading(page, SELECTORS["listing_notes_heading"])
        self._note("step 3/6 ListingNotes: No restrictions / Neither of these / Normal seller")
        if listing.get("no_restrictions", DEFAULTS["no_restrictions"]):
            self._check_box_if_present(page, SELECTORS["no_restrictions_checkbox"])
        self._check_radio_if_present(page, listing.get("about_you", DEFAULTS["about_you"]))
        self._check_radio_if_present(page, listing.get("seller_type", DEFAULTS["seller_type"]))
        human_delay(0.5, 1.5)
        self._click_continue(page)
        human_delay()

    def _step4_delivery(self, page, listing: dict) -> None:
        self._wait_heading(page, SELECTORS["delivery_heading"])
        method = listing.get("delivery_method", DEFAULTS["delivery_method"])
        # Only use a delivery type the page actually offers — per-event.
        # Never hardcode Barcode / Paper / PDF / Pickup.
        if self._check_radio_if_present(page, method):
            self._note(f"step 4/6 DeliveryDetails: {method}")
        else:
            self._note(f"step 4/6 DeliveryDetails: '{method}' not offered for this event, "
                       "keeping the page default")
        stored = listing.get("tickets_stored", DEFAULTS["tickets_stored"])
        self._check_radio_if_present(page, stored)
        human_delay(0.5, 1.5)
        self._click_continue(page)
        human_delay()

    def _step5_seat_details(self, page, listing: dict) -> None:
        self._wait_heading(page, SELECTORS["seat_details_heading"])
        section = listing.get("section") or "General Admission"
        if not section:
            raise ValueError("Section is required on SeatDetails")
        self._note(f"step 5/6 SeatDetails: section={section!r} (generic: row Not Specified, seats blank)")
        combo = page.get_by_role("combobox", name=SELECTORS["section_combobox"]).first
        try:
            combo.select_option(label=section, timeout=ACTION_TIMEOUT_MS)
        except Exception:
            combo.fill(section, timeout=ACTION_TIMEOUT_MS)
        row = listing.get("row", DEFAULTS["row"])
        row_combo = page.get_by_role("combobox", name=SELECTORS["row_combobox"], exact=False)
        if row_combo.count():
            try:
                row_combo.first.select_option(label=row, timeout=ACTION_TIMEOUT_MS)
            except Exception:
                pass  # leave the page default if the label is not offered
        # Generic listing: First / Last seat stay BLANK on purpose.
        if listing.get("first_seat"):
            page.get_by_label(SELECTORS["first_seat_textbox"], exact=False).first.fill(
                str(listing["first_seat"]), timeout=ACTION_TIMEOUT_MS)
        if listing.get("last_seat"):
            page.get_by_label(SELECTORS["last_seat_textbox"], exact=False).first.fill(
                str(listing["last_seat"]), timeout=ACTION_TIMEOUT_MS)
        self._check_radio_if_present(page, listing.get("seat_reason", DEFAULTS["seat_reason"]))
        human_delay(0.5, 1.5)
        self._click_continue(page)
        human_delay()

    def _step6_price_details(self, page, listing: dict) -> dict:
        self._wait_heading(page, SELECTORS["price_heading"])
        errors = validate_price_inputs(listing)
        if errors:
            raise RuntimeError("PriceDetails pre-flight failed: " + "; ".join(errors))
        if self._has_card_blocker(page):
            raise RuntimeError(
                "BLOCKED: Viagogo requires a credit/debit card on file before "
                "'Create Listing' enables ('Add Card On File'). The bot never "
                "enters card details — add a card by hand in the seller account, "
                "then retry. No listing was created.")
        price = float(listing["listing_price"])
        face = float(listing["face_price"])
        self._note(f"step 6/6 PriceDetails: listing {price} / face {face} "
                   f"(currency per page, payout={listing.get('payout_method', DEFAULTS['payout_method'])})")
        # Two "Per ticket US$" spinbuttons: listing price first, face value
        # second (inside ENTER FACE VALUE). Type them character-by-character
        # (stealth jitter); same end values as .fill().
        spins = page.get_by_role("spinbutton", name=SELECTORS["per_ticket_spinbutton"], exact=False)
        if spins.count() < 2:
            raise RuntimeError(f"PriceDetails: expected 2 'Per ticket US$' spinbuttons, found {spins.count()}")
        type_like_human(spins.nth(0), str(price), timeout=ACTION_TIMEOUT_MS)
        type_like_human(spins.nth(1), str(face), timeout=ACTION_TIMEOUT_MS)
        payout = listing.get("payout_method", DEFAULTS["payout_method"])
        payout_combo = page.get_by_role("combobox", name=SELECTORS["payout_combobox"], exact=False)
        if payout_combo.count():
            payout_combo.first.select_option(label=payout, timeout=ACTION_TIMEOUT_MS)
        if payout == "PayPal":
            type_like_human(
                page.get_by_label(SELECTORS["paypal_email_textbox"], exact=False).first,
                listing["paypal_email"], timeout=ACTION_TIMEOUT_MS)
        # Terms + buyer-info consent checkboxes (check any that are present).
        for box in page.get_by_role("checkbox", name=re.compile("Terms and Conditions", re.I)).all():
            box.check(timeout=ACTION_TIMEOUT_MS)
        human_delay(0.5, 1.5)
        # "Create Listing" — NOT "Publish". This click itself is still
        # unverified live (it was never clicked in the observed session).
        click_like_human(
            page, page.get_by_role("button", name=SELECTORS["create_listing_button"], exact=False),
            timeout=ACTION_TIMEOUT_MS)
        check_challenge_or_solve(page, self._captcha_solver)
        human_delay(2, 4)
        draft = _draft_id_from_url(page.url)
        self._note(f"step 6/6 done: Create Listing clicked, url={page.url}")
        return {"ok": True, "viagogo_listing_id": draft or page.url}

    def create_listing(self, listing: dict) -> dict:
        """Post ONE listing through the verified 6-step pipeline.
        Dry-run simulates all 6 steps; mock drives the fake portal;
        live drives the real seller portal."""
        if self.dry_run and not self.mock_url:
            self._dry_counter += 1
            fake_id = f"DRY-{self._dry_counter:04d}"
            for step in ("1/6 Sell search", "2/6 Quantity", "3/6 ListingNotes",
                         "4/6 DeliveryDetails", "5/6 SeatDetails", "6/6 PriceDetails"):
                self._note(f"DRY-RUN {step}: {listing['event_name']} (simulated)")
            errors = validate_price_inputs(listing)
            # Dry-run simulates the flow: missing prices are a hard failure,
            # but missing payout info is only a warning here — the LIVE
            # pre-flight in _step6_price_details still refuses it outright.
            price_errors = [e for e in errors
                            if "face_price" in e or "listing_price" in e]
            if price_errors:
                return {"ok": False, "dry_run": True, "error": "; ".join(price_errors)}
            if errors:
                self._note("DRY-RUN warning: " + "; ".join(errors)
                           + " — a live post would be refused until fixed")
            self._note(f"DRY-RUN create_listing: {listing['event_name']} | "
                       f"{listing.get('section')} x{listing.get('quantity')} @ "
                       f"{listing.get('currency', 'GBP')} {listing.get('listing_price')} -> {fake_id} (NOT posted)")
            return {"ok": True, "dry_run": True, "viagogo_listing_id": fake_id}
        self._require_live_or_mock()

        def _do():
            pw, browser, context = self._launch()
            try:
                page = context.new_page()
                self._step1_sell_search(page, listing)
                self._step2_quantity(page, listing)
                self._step3_listing_notes(page, listing)
                self._step4_delivery(page, listing)
                self._step5_seat_details(page, listing)
                if self.mock_url:
                    result = self._step6_price_details(page, listing)
                    result["mock"] = True
                    result["viagogo_listing_id"] = "MOCK-0001"
                    return result
                return self._step6_price_details(page, listing)
            finally:
                browser.close(); pw.stop()

        return _retry(_do, "create_listing")

    def update_price(self, viagogo_listing_id: str, new_price: float) -> dict:
        if self.dry_run and not self.mock_url:
            self._note(f"DRY-RUN update_price {viagogo_listing_id} -> {new_price} (NOT changed)")
            return {"ok": True, "dry_run": True}
        self._require_live_or_mock()
        return {"ok": True, "note": "VERIFY: implement against live listings table — price is edited on PriceDetails in the live pipeline"}

    def set_listing_status(self, viagogo_listing_id: str, action: str) -> dict:
        """action: pause | resume | delete | relist"""
        assert action in {"pause", "resume", "delete", "relist"}
        if self.dry_run and not self.mock_url:
            self._note(f"DRY-RUN {action} {viagogo_listing_id} (NOT changed)")
            return {"ok": True, "dry_run": True}
        self._require_live_or_mock()
        return {"ok": True, "note": f"VERIFY: implement {action} against live listings table"}

    def check_sales(self) -> list[dict]:
        """Poll the seller dashboard for new sales. Dry-run: none.
        Live: VERIFY — scrape the sales section and return
        [{listing_id, sale_price}] for sales not yet notified."""
        if self.dry_run and not self.mock_url:
            return []
        self._require_live_or_mock()
        return []  # implement after selector verification; sales also arrive via email/Discord polling in v2
