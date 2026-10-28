# Viagogo Listing Automation — v1.2.2 (listing-only + Opportunity Scanner + stealth + NopeCHA)

**Start here: [`DELIVERY.md`](DELIVERY.md)** — what the client gets,
5-minute Windows/Linux setup, dry-run demo, and the live go-live checklist.

Bulk-post and maintain Viagogo listings for EU football and concerts, with
configurable above-market pricing and Discord sale alerts. **The bot never
buys tickets.** After a sale, the client buys the ticket manually and delivers it.

> **Status: production-ready package, v1.2.2 adds optional NopeCHA
> CAPTCHA solving (off by default, no key configured).** The 6-step Sell
> pipeline is **verified to PriceDetails** against the real portal
> (observed live 2026-10-28, logged in, Metallica sample, no listing
> created). The **"Create Listing" click itself is still unverified**
> — it needs a card on file + face value + payout, and the bot refuses without them
> (it never enters card details). Sale detection (`/api/sales/check`)
> is still a **stub**. The scanner is **heuristic only — NO ML model**:
> it scores the latest snapshot with documented rules, and stores price
> history so a future ML model has training data. Stealth **reduces**
> detection risk — it does **NOT** guarantee invisibility, and by
> default it never bypasses a CAPTCHA or Cloudflare challenge: if one
> appears, the bot stops — unless the operator explicitly enables
> NopeCHA with their own key (see § NopeCHA). See § Stealth.

## ⚠️ Warning — read this first

**Viagogo prohibits speculative listings** — listings for tickets the seller
does not yet own — and can remove listings, fine the seller, or **permanently
suspend the seller account**. This tool gives **no guarantee of account
safety**. The client must accept that risk in writing before any live run.
Listings should only be posted for tickets the client can actually buy and
deliver. Viagogo also uses Cloudflare bot protection, so the seller portal
may block or rate-limit automated access at any time.

## What the system does

- **Web UI** (`http://127.0.0.1:5002`): price rules, bulk-create form, listings table
- **Bulk posting**: N listings per event, quantity per listing (volume control)
- **Generic listings**: section/zone only, no exact seat
- **Pricing**: face × (1 + markup%) clamped to min/max, rounded to .99
- **Maintain**: post / pause / resume / relist / delete / reprice
- **Discord**: sale alert via webhook + a test button; a sale-simulation
  endpoint proves the Discord path without Viagogo
- **Storage**: SQLite (`data/listings.db`), config in the DB
- **Opportunity Scanner** (`/opportunities`): watchlist + market scans +
  ranked opportunities with heuristic scoring (see below)

## Stealth / anti-detection (v1.2.1) — reduces risk, does NOT guarantee invisibility

`stealth.py` is shared by the seller bot (`viagogo_bot.py`) and the market
monitor (`market.py`). It is **on by default** (`STEALTH_ENABLED=True`).

What it does:

- **Randomised desktop user-agent** — picked per browser launch from a
  small pool of current Chrome-on-Windows/Mac strings (override with
  `STEALTH_USER_AGENTS`, comma-separated). Desktop only — a mobile UA on
  a desktop viewport would be an obvious mismatch.
- **Randomised desktop viewport** — picked per launch from a small pool
  (1920×1080, 1366×768, 1536×864, 1440×900, 1280×720).
- **Locale + timezone matching the seller store** — `en-US` /
  `America/New_York` by default (override with `STEALTH_LOCALE` /
  `STEALTH_TIMEZONE`), so the fingerprint is internally consistent.
- **Init script hiding the usual automation tells** — via Playwright's
  `add_init_script` (no extra dependency, no stealth plugin):
  `navigator.webdriver` undefined, `window.chrome.runtime` present,
  notifications permission behaving like a real browser, a non-empty
  plugins list, `navigator.languages` = `['en-US', 'en']`.
- **Per-action jitter** — search box, price and PayPal-email fields are
  typed character-by-character with small random delays; Continue /
  List Tickets / Create Listing clicks are preceded by a small random
  mouse move. The locators and the 6-step pipeline are unchanged.
- **Proxy keeps working** — the proxy is set at browser launch, stealth
  only configures the context, so `VIAGOGO_PROXY` works with stealth on.

What it does **NOT** do (honest limits):

- It does **not** defeat Cloudflare or any serious bot-detection system.
  It only removes the most obvious tells. Viagogo can still detect,
  rate-limit or block automated access at any time.
- It **never** bypasses, solves, clicks through, or waits out a CAPTCHA
  or Cloudflare challenge. `detect_challenge()` checks every page load:
  if a challenge page appears (e.g. "Just a moment…", "Attention
  Required", "Verify you are human", any CAPTCHA text), the bot **stops
  immediately**, logs `CHALLENGE DETECTED (…)`, and raises
  `ChallengeDetectedError` — the listing bot does not retry it, and the
  market scanner records that event as `live-challenge` and moves on.
  If challenges appear often, stop automating and use the portal by hand.
- Randomisation is per browser launch (one UA + viewport per session),
  not per page — rotating the fingerprint mid-session would look *more*
  suspicious, not less.

Disable it with `STEALTH_ENABLED=False` in `.env` (e.g. for debugging —
  a plain Playwright fingerprint is easier to tell apart in logs).

## NopeCHA CAPTCHA solver (v1.2.2, optional, OFF by default)

`captcha.py` adds optional NopeCHA support. **The bot works without
it**: with no key configured, a challenge still stops the bot exactly
as before. Nothing is solved silently — solving must be an explicit
operator choice.

How it works:

- **Token API first** — for reCAPTCHA v2/v3 and Cloudflare Turnstile:
  sitekey + page URL → token, which is injected into the page's hidden
  response field. **Recognition API as a fallback** — for image/audio
  challenges, returns click positions / text for the browser to apply.
- **One attempt per challenge page, max 2 attempts per solve call.**
  A second attempt on the same page is refused. A challenge with no
  sitekey (e.g. a Cloudflare "Just a moment…" interstitial) cannot be
  solved by the Token API — the bot stops on those pages.
- **Key source:** `NOPECHA_API_KEY` in `.env` (checked first) or pasted
  in the dashboard — main page, section 4 "CAPTCHA Solver (NopeCHA)":
  enable toggle + password field + **Save**, **Check status / balance**
  (GET `https://api.nopecha.com/v1/status`), and **Test** (a mock solve
  — no real API call, no credits spent). The key is stored in the local
  SQLite config (`nopecha_api_key`), shown back only masked (first 4
  chars + `***`), and never logged; a returned token is never logged
  either. Endpoints: `GET/POST /api/captcha/config`,
  `POST /api/captcha/status`, `POST /api/captcha/test`.
- **Where it hooks in:** `stealth.check_challenge_or_solve()` — used by
  the seller bot (`viagogo_bot.py`, on page loads and after the
  Create Listing click) and the market scanner (`market.py`, on live
  page loads). Uses the official `nopecha` Python package when
  installed (`pip install nopecha`, already in `requirements.txt` as
  an optional dependency); with the package missing it reports
  "not installed" instead of crashing.

Where to get a key: https://nopecha.com — free tier 100 recognitions
per day; Starter $4.99/month (2,000 solves/day). The key and the
subscription are the operator's to pay for.

Honest limits (also in `captcha.py`):

- Solving a CAPTCHA to bypass anti-bot controls **may violate
  Viagogo's terms of service and increases the risk of the seller
  account being flagged, rate-limited or suspended**. NopeCHA does
  **not** guarantee a solve — challenges can fail, time out, or return
  a token Viagogo rejects. The hCaptcha Token endpoint was
  discontinued by NopeCHA in Oct 2026, so hCaptcha solves may answer
  410 — handled as a normal solve failure.
- This does not make the bot invisible: stealth still only reduces
  detection risk, and Cloudflare can still block automated access.

## Opportunity Scanner (v1.2.0) — heuristic scoring, NO ML

Fayed asked for a SMART system, not just bulk listings: find profitable
opportunities, score them, alert on the best ones. The scanner does that
with transparent rules — **no ML model, no prediction of the future** —
because no historical data exists yet. ML is Phase 2 (the +$500 module
Fayed offered): it needs weeks of snapshots collected by this scanner
first. Every scan stores a row in `price_snapshots`, so that history is
already accumulating.

How it works: add events to the watchlist (`/opportunities` page or
`POST /api/watchlist`, or seed the 5-event example with
`POST /api/watchlist/seed`), run a scan (`POST /api/scan`), and the
ranked list shows, per event: current market price, recommended price,
estimated profit + margin, demand, risk, confidence 0-100, best timing.
Opportunities crossing the alert thresholds (default: profit ≥ 50 and
confidence ≥ 50) are sent to Discord via `discord_notify.py`.

Scoring rules (full list with R1–R12 in `scoring.py` — the code IS the spec):
market price = lowest listing (else average); recommended price = market
+ demand premium (High +10%, Medium +5%, Low +0%) + scarcity premium
(≤5 listings +5%, >20 listings −5%) + urgency premium (event ≤7 days
and High demand +5%), clamped to min/max and rounded to .99; profit =
recommended × (1 − fee%) − buy cost (fee% is an estimate, default 10%,
the seller must confirm the real fee); confidence starts at 100 and
loses points for every missing field (no lowest price −40, no buy cost
−20, …); risk is High when margin <10% or confidence <40 or the market
is crowded or the event is <3 days away; ranking is profit × confidence.

**Sample data warning:** scans are mock/sample by default
(`mock/sample_snapshots.json`, every number labelled SAMPLE) — no
network, no Viagogo. A live scrape needs `SCAN_LIVE=True` in `.env`
**and** `{"live": true}` in the scan request; without both, a live
request is silently downgraded to mock. Live scans are polite
(≥5s between pages, max 2 attempts, proxy via `VIAGOGO_PROXY`).
**Price-rule cap:** the default max price is 500 — USD events like the
Metallica sample (~$860) need a higher cap in the price rules, or the
recommendation clamps and profit goes negative. Set rules per currency.

## Safety model

- `DRY_RUN=True` by default. In dry-run, posting is **simulated** and returns
  a fake id like `DRY-0001`. Nothing is submitted to Viagogo.
- A live run needs **all four**: `LIVE_MODE=True` **and** `DRY_RUN=False`
  **and** a saved session file (`auth_state.json`) **and** `LIVE_CONFIRM=yes`.
  The app refuses to start in live mode without the session and the
  confirmation (see `DELIVERY.md`); the bot refuses live actions otherwise.
- No real Viagogo credentials are in this repo. Login is via a saved browser
  session only (see Live checklist). `.env`, `*.db`, `auth_state.json`, `logs/`
  are gitignored. The webhook URL and session contents are never logged.

## Setup

```bash
cd viagogo-listing-automation
./run.sh            # Linux/macOS: venv + deps + start  (or run.bat on Windows)
# python -m playwright install chromium   # only for LIVE / mock-portal mode
cp .env.example .env
cp config.example.json config.json     # edit price rules / sample events
```

## Run

```bash
./run.sh            # or: run.bat   (Windows)
# open http://127.0.0.1:5002
# health: http://127.0.0.1:5002/api/health
```

Docker: `docker compose up -d --build`. systemd: see `viagogo.service`.

## Dry-run test (no Viagogo account, no browser, no Discord needed)

```bash
python -m pytest tests/ -q
python scripts/test_end_to_end.py
python scripts/test_mock_portal.py   # needs Chromium: python -m playwright install chromium
```

Expected: pricing tests pass, and the end-to-end script prints
`ALL DRY-RUN END-TO-END CHECKS PASSED` — pricing → 3 bulk drafts →
dry-run post (`DRY-0001`, not posted) → simulated sale → Discord payload
(built, not sent) → pause/resume → dry-run guard.

Mock-portal browser test (proves the 6-step Playwright flow with a real
browser, still no Viagogo): `python scripts/test_mock_portal.py` drives
`mock/mock_seller_portal.html` (same 6 steps, same labels) and expects
`MOCK-0001`. Needs Chromium once: `python -m playwright install chromium`.

## API (all under the Flask app)

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | health check: ok, version, dry_run, live_mode |
| GET | `/opportunities` | Opportunities page (watchlist + ranked list) |
| GET | `/api/opportunities` | ranked opportunities (heuristic scoring) |
| POST | `/api/scan` | run a market scan (mock/sample by default; live only with SCAN_LIVE=True + `{"live": true}`) |
| GET/POST | `/api/watchlist` | list / add a watched event |
| DELETE | `/api/watchlist/<id>` | remove a watched event |
| POST | `/api/watchlist/seed` | load `watchlist.example.json` (5 events, skips duplicates) |
| GET | `/api/snapshots` | price-snapshot history (`?event_url=…&limit=50`) |
| POST | `/api/opportunities/test-discord` | send top opportunity to Discord (dry-run payload if no webhook) |
| GET/POST | `/api/config` | price rules + Discord webhook |
| GET/POST | `/api/listings` | list / create one draft |
| POST | `/api/bulk` | create N drafts for one event |
| POST | `/api/listings/<id>/post` | post via bot (simulated in dry-run) |
| POST | `/api/listings/<id>/pause\|resume\|relist\|delete` | maintain a listing |
| POST | `/api/listings/<id>/reprice` | reprice (face_price or listing_price) |
| POST | `/api/discord/test` | send Discord test message |
| POST | `/api/sales/check` | poll seller dashboard for new sales |
| POST | `/api/sales/simulate` | test-only: mark sold + fire Discord alert |
| GET/POST | `/api/captcha/config` | NopeCHA settings (key returned only masked) |
| POST | `/api/captcha/status` | check the NopeCHA key (GET api.nopecha.com/v1/status) |
| POST | `/api/captcha/test` | mock solve — no real API call, no credits spent |
| GET | `/api/events/search?q=…` | event search (fake match in dry-run) |

## Files

```
app.py                  Flask UI + API (listings + Opportunity Scanner)
viagogo_bot.py          Playwright seller-portal bot — verified 6-step Sell
                        pipeline (label/text locators), card-blocker pre-flight
stealth.py              Anti-detection hardening (shared by bot + scanner):
                        randomised UA/viewport, locale/timezone, init script
                        hiding automation tells, typing/click jitter, and
                        challenge detection that STOPS the bot (or attempts
                        ONE NopeCHA solve when enabled + configured)
captcha.py              OPTIONAL NopeCHA CAPTCHA solving (v1.2.2): Token API
                        (reCAPTCHA v2/v3, Turnstile) + Recognition API,
                        one attempt per page, key never logged, works
                        without a key (stop-on-challenge) and without the
                        `nopecha` package installed
market.py               Public market monitor (Playwright, no login) + parsers
scoring.py              Heuristic opportunity scoring, rules R1–R12 (pure, tested)
pricing.py              Markup / clamp / round rules (pure functions)
discord_notify.py       Discord webhook (sale + opportunity alerts + test)
db.py                   SQLite: listings, sales, config, price_snapshots, watchlist
templates/index.html    Single-page UI (listings)
templates/opportunities.html  Opportunities page (watchlist + ranked list)
mock/mock_seller_portal.html   fake 6-step seller flow for browser testing
mock/sample_snapshots.json     SAMPLE market data for offline scanner demos
watchlist.example.json  5-event watchlist template (Metallica verified + placeholders)
tests/test_pricing.py   pricing unit tests
tests/test_bot_steps.py bot pipeline unit tests (no browser)
tests/test_stealth.py   stealth unit tests (24 cases: UA/viewport pools,
                        init script, challenge detection, jitter bounds,
                        real-Chromium webdriver check when installed)
tests/test_captcha.py   NopeCHA unit tests (27 cases, all mock/offline:
                        no-key/disabled behaviour, masked keys, Token +
                        Recognition with a fake client, quota errors,
                        package-not-installed, one-attempt-per-page,
                        dashboard config masking)
tests/test_scoring.py   scoring unit tests (15 cases)
tests/test_market_parse.py  market text-parser unit tests
scripts/test_end_to_end.py     full dry-run flow, no browser/Viagogo
scripts/test_scanner_end_to_end.py  scanner flow: seed -> mock scan -> ranked -> Discord
scripts/test_mock_portal.py    mock-portal browser test (needs Chromium)
config.example.json / .env.example   templates — no real credentials
```

## What still needs the client's real account to go live

**Missing inputs — do NOT run live until all are in hand:**

1. **Viagogo seller account login** — the client logs in once in a browser;
   save the session to `auth_state.json` (Playwright `storage_state`).
   No username/password is stored in this repo.
2. **1 sample event link** — a real Viagogo event URL from the client's
   account (the example in `config.example.json` is a placeholder).
   Use it for the first single-listing live test before any bulk run.
3. **Discord webhook URL** — paste it in the UI or `.env` as
   `DISCORD_WEBHOOK_URL`; use the UI test button to confirm it arrives.
4. **Card on file, face value, payout** — before the first live run:
   add a valid credit/debit card to the seller account by hand, have a
   face value for every listing, and set a payout method (PayPal email
   or Direct deposit). The bot checks all three on PriceDetails and
   refuses with a clear error if any is missing; it never enters card
   details. The "Create Listing" click itself is still unverified —
   do ONE listing by hand first, then ONE via the bot.
5. **Proxy (optional)** — if the client uses one, set `VIAGOGO_PROXY`.
6. **Written risk acceptance** — the client accepts the speculative-listing
   suspension risk (see warning above) before `LIVE_MODE=True`.

Suggested live rollout: 1 listing on the sample event → confirm it appears
in the seller dashboard → confirm a Discord test → then a small bulk batch
(3–5 listings) → only then scale volume.
```

## Known limits (v1.2.1)

- No official Viagogo seller API was found; the bot drives the seller portal
  in a browser, so portal changes or Cloudflare challenges can break it.
  No Cloudflare/CAPTCHA was seen in the logged-in pipeline on 2026-10-28,
  but pages load blank for a few seconds — the bot waits generously.
  **Stealth (v1.2.1) only reduces detection risk; it does not guarantee
  invisibility and never bypasses a challenge — if one appears the bot
  stops.** See § Stealth.
- The "Create Listing" click is **unverified live** (needs card on file +
  face value + payout); the bot refuses without them.
- Sale detection (`/api/sales/check`) is a stub until the live sales-page
  selectors are verified; the Discord path itself is proven by simulation.
- No automatic ticket buying, no e-ticket upload, no multi-account support.
- Prices are per-listing rules only; no competitor-price scraping yet.
- Listings created through the UI carry no payout info yet — the bot warns
  in dry-run and refuses a live post until payout method + PayPal email
  (or Direct deposit) are supplied per listing.
- The scanner scores the LATEST snapshot only; it does not predict future
  prices (no ML). Live market data needs SCAN_LIVE=True and Fayed's real
  event list — sample numbers must never be acted on.
- NopeCHA (v1.2.2) is optional and OFF by default. It attempts at most
  ONE solve per challenge page and never retries a page; a Cloudflare
  interstitial (no sitekey) cannot be solved by the Token API, and
  solving a CAPTCHA may violate Viagogo's terms and increases
  account-ban risk. NopeCHA does not guarantee a solve.
