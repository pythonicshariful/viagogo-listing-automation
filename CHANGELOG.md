# Changelog

## v1.3.1 — 2026-10-28 — README rewritten for non-technical users (docs only)

- **README rewritten from scratch for a non-technical user** (Fayed):
  plain simple English, short sentences, every term explained the first
  time it is used. Covers Python install from python.org (with the
  "Add Python to PATH" box and how to check it), getting the program
  (GitHub ZIP download or `git clone`), starting it (`run.bat` /
  `./run.sh`, first-run setup, leave the black window open), a guided
  5-minute tour (DRY-RUN badge → price rules → dry-run demo → the
  Opportunities page), one plain-words paragraph per Settings group,
  the live go-live checklist, and a "If something goes wrong" FAQ
  table (Python not found, port in use, page won't open, Create Listing
  disabled, challenge pages, NopeCHA not configured, what to send
  Shariful for help). The developer section (tests, API table, file
  list, honest limits) moved to the bottom. No code behaviour changed.
- DELIVERY.md install sections now point at the README steps instead of
  duplicating them.

## v1.3.0 — 2026-10-28 — All settings in the dashboard UI, no .env needed

- **No .env file needed.** The app runs with safe defaults and every
  setting is changeable in the dashboard (main page, section 5
  "Settings") and stored in the SQLite config. `run.sh` / `run.bat` no
  longer copy `.env.example` — double-click and open
  http://127.0.0.1:5002. Environment variables remain only as an
  optional override for advanced users (a set variable wins over the
  dashboard value, and the dashboard says so). `.env.example` now says
  "OPTIONAL" at the top.
- New `settings.py`: defaults, pure validation (unknown keys fail
  loudly), storage_state validation, proxy masking + probing. New API:
  `GET/POST /api/settings`, `POST /api/session/upload` (multipart,
  validates Playwright storage_state JSON, never returns or logs its
  contents), `POST /api/session/clear`, `POST /api/proxy/test` (quick
  request through the proxy, URL returned only masked).
- **Mode (safety kept):** Dry-run / Live toggle in Settings. Switching
  to Live needs the two-step confirmation (tick the box AND type `LIVE`);
  switching back to dry-run clears it. The app now always starts — even
  in live mode with blockers — so the user can fix them in the dashboard
  (e.g. upload the session); live ACTIONS are still refused without a
  saved session + confirmation + the existing card / face-value / payout
  pre-flight. The big DRY-RUN / LIVE badge shows on both pages.
- **Seller session:** status in Settings (file name, size, last modified
  — never contents) + upload + clear.
- **Scanner:** live-scan toggle (replaces `SCAN_LIVE`), scan delay,
  page timeout, headless on/off — wired into `MarketMonitor` (params,
  env as fallback). **Seller fee %** (default 10) is now a setting and
  is used by scoring in `/api/opportunities` and `/api/scan`
  (`DEFAULT_FEE_PCT` stays as the fallback).
- **Proxy:** URL field + Test button, wired into the bot and scanner.
- **Stealth:** enabled toggle + locale/timezone dropdowns, wired into
  `new_stealth_context()` and both browser flows via optional params
  (env behaviour unchanged when not passed).
- **Server:** host / port / log level editable in Settings, stored in
  config, applied on next restart (the response flags `restart_required`
  and says so). `DATABASE_PATH` is intentionally NOT exposed in the UI.
- Price rules, Discord webhook and NopeCHA keep working unchanged;
  `/api/config` is untouched (back-compat).
- Tests: 16 new cases in `tests/test_settings.py` (all mock/offline);
  full suite **102 passed** (86 existing still passing), listing +
  scanner end-to-end passed, mock-portal `MOCK-0001` passed, fresh
  Flask smoke test on a temp port + temp DB with NO `.env` file passed.

## v1.2.2 — 2026-10-28 — NopeCHA CAPTCHA solving (optional, OFF by default)

- New `captcha.py`: optional NopeCHA support, no key needed to run the
  bot — with no key configured every solve call returns "not configured"
  and challenge pages still stop the bot exactly as before. Token API
  for reCAPTCHA v2/v3 + Cloudflare Turnstile (sitekey + page URL ->
  token, injected into the page's hidden response field), Recognition
  API as a fallback for image/audio challenges. Uses the official
  `nopecha` package when installed (added to `requirements.txt` as an
  optional dependency, `nopecha==2.0.1`); with the package missing it
  reports "not installed" instead of crashing. Key from env
  `NOPECHA_API_KEY` first, then the dashboard (SQLite config
  `nopecha_api_key`); toggle from env `NOPECHA_ENABLED` or the
  dashboard (`nopecha_enabled`). Key never logged (first 4 chars +
  "***" only) and a returned token is never logged.
- One attempt per challenge page (enforced — a second attempt on the
  same page is refused), max 2 attempts per solve call. A challenge
  with no sitekey (Cloudflare "Just a moment…" interstitial) cannot be
  solved by the Token API — the bot stops. Quota/balance failures are
  reported clearly. Wired in via `stealth.check_challenge_or_solve()`
  (new; `check_challenge_or_raise()` unchanged) in the seller bot
  (page loads + after the Create Listing click) and the market scanner
  (live page loads). The web app passes the dashboard solver into
  both; the bot/scanner processes fall back to the env solver.
- Dashboard (main page, section 4 "CAPTCHA Solver (NopeCHA)"):
  enable toggle + password field + Save, **Check status / balance**
  (GET `https://api.nopecha.com/v1/status`, whitelisted fields only),
  **Test** (mock solve — no real API call, no credits spent). New
  endpoints: `GET/POST /api/captcha/config` (key returned only
  masked), `POST /api/captcha/status`, `POST /api/captcha/test`.
  Opportunities page links to the section.
- Honest limits (README + DELIVERY + captcha.py): solving a CAPTCHA
  may violate Viagogo's terms and increases account-ban risk; NopeCHA
  does not guarantee a solve; hCaptcha Token was discontinued by
  NopeCHA in Oct 2026 (410s are handled as normal failures).
- Tests: new `tests/test_captcha.py` (27 cases, all mock/offline:
  no-key/disabled behaviour, masked keys, Token + Recognition with a
  fake client, quota errors, package-not-installed, one-attempt-per-
  page, no-sitekey challenge, dashboard config masking). Full suite
  now 86 passed (was 59); mock-portal MOCK-0001, scanner + dry-run
  end-to-end unchanged; Flask smoke test covers the captcha endpoints
  (no key -> "not configured"; fake key -> mock test passes).

## v1.2.1 — 2026-10-28 — Stealth / anti-detection hardening

- New `stealth.py`, shared by `viagogo_bot.py` and `market.py`, on by
  default (`STEALTH_ENABLED=True`): randomised desktop user-agent per
  launch (pool of 5 current Chrome-on-Windows/Mac strings, override
  with `STEALTH_USER_AGENTS`), randomised desktop viewport per launch
  (pool of 5: 1920×1080 … 1280×720), locale/timezone matching the
  seller store (`en-US` / `America/New_York`, env-overridable), and a
  Playwright `add_init_script` init script hiding the usual automation
  tells (`navigator.webdriver`, missing `window.chrome`, empty plugins,
  headless permissions/languages). No stealth plugin, no new dependency.
- Per-action jitter: search box, price and PayPal-email fields are typed
  character-by-character with small random delays; Continue / List
  Tickets / Create Listing clicks are preceded by a small random mouse
  move. All label/text locators and the 6-step pipeline are unchanged.
- Proxy keeps working with stealth on (proxy is set at browser launch;
  stealth only configures the context).
- Safety: `detect_challenge()` checks every page load. A CAPTCHA /
  Cloudflare challenge page ("Just a moment…", "Attention Required",
  "Verify you are human", any CAPTCHA text) makes the bot STOP
  immediately with `ChallengeDetectedError` — never solved, clicked
  through, or retried (the listing bot's `_retry` re-raises it at once;
  the scanner records that event as `live-challenge`). README and
  DELIVERY state this honestly: stealth reduces detection risk but does
  NOT guarantee invisibility.
- Tests: new `tests/test_stealth.py` (24 cases: UA/viewport pools + env
  override, init-script contents, challenge detection on sample HTML
  including the mock portal, jitter bounds, STEALTH_ENABLED switch,
  real-Chromium check that `navigator.webdriver` is hidden). Full suite
  now 59 passed (was 35); mock-portal browser test still returns
  MOCK-0001; scanner end-to-end + dry-run end-to-end unchanged.

## v1.2.0 — 2026-10-28 — Opportunity Scanner (heuristic, NO ML)

Fayed clarified (Aug 17) he does NOT want just a bulk-listing bot — he
wants a SMART system that finds profitable opportunities. This release
adds that, with heuristic scoring only. NO ML model: no historical data
exists, and ML prediction is Phase 2 (the +$500 module Fayed offered),
needing weeks of snapshots collected by this scanner first.

- New `scoring.py`: pure functions, rules R1–R12 documented in the code
  (market price, demand premium High +10% / Medium +5% / Low +0%,
  scarcity ≤5 listings +5% / >20 −5%, urgency ≤7 days + High demand
  +5%, clamp to min/max + .99, profit = recommended × (1 − fee%) −
  buy cost, confidence 0–100 penalised per missing field, risk
  High/Medium/Low, best-timing note, ranking = profit × confidence).
  One real bug found by the tests and fixed: rounding to .99 could dip
  a clamped price below min_price (100 → 99.99); scoring now re-clamps
  to min, as pricing.py already did.
- New `market.py`: public market monitor (Playwright, no login, polite
  ≥5s between live pages, max 2 attempts, proxy via `VIAGOGO_PROXY`),
  text parsers for prices / people-searching / listings count. Mock
  mode is default (`mock/sample_snapshots.json`, every number labelled
  SAMPLE); live needs `SCAN_LIVE=True` **and** `{"live": true}`.
- New storage in `db.py`: `price_snapshots` (history for future ML)
  + `watchlist` tables and helpers.
- New Flask routes: `/opportunities` page, `GET /api/opportunities`
  (ranked), `POST /api/scan`, `GET/POST/DELETE /api/watchlist`,
  `POST /api/watchlist/seed`, `GET /api/snapshots`,
  `POST /api/opportunities/test-discord`. Discord opportunity alerts
  via new `notify_opportunity()` (thresholds: profit ≥ 50, confidence
  ≥ 50 by default). Main UI links to the Opportunities page.
- New `watchlist.example.json` (5 events: Metallica verified live
  + 4 clearly-marked placeholders for Fayed's real 10–20 events).
- Tests: pytest 35 passed (was 15: +15 scoring, +5 market parsing),
  scanner end-to-end passed, Flask smoke test passed (incl. live-scan
  guard: live request with SCAN_LIVE=False stays mock), mock-portal
  browser test passed, dry-run end-to-end passed.
- STILL UNVERIFIED / NOT BUILT: the "Create Listing" click itself,
  live sale detection (stub), ML prediction (Phase 2), live market
  data (needs SCAN_LIVE + Fayed's real event list).

## v1.1.0 — 2026-10-28 — Sell pipeline verified to PriceDetails

- `viagogo_bot.py` rewritten to the REAL Sell pipeline observed live
  (logged in, Metallica sample, 2026-10-28, no listing created): Sell
  search → Quantity (1–30, sell together) → ListingNotes (No
  restrictions / Neither of these / Normal seller) → DeliveryDetails
  (Mobile Ticket Transfer, tickets stored Unknown; only per-event
  delivery types used, never hardcoded Barcode/Paper/PDF) →
  SeatDetails (Section required, Row "Not Specified", seats blank for
  generic, reason "primary site has not provided me...") →
  PriceDetails (listing price + face value spinbuttons, payout
  PayPal/Direct deposit, PayPal email, Terms checkboxes, button
  "Create Listing" — NOT "Publish"). Selectors are now label/text-based.
- New pre-flight in step 6: refuses with a clear error if face value,
  payout method / PayPal email, or card-on-file ("Add Card On File")
  is missing — the bot NEVER enters card details.
- New `validate_price_inputs()` (pure, unit-tested) + `_draft_id_from_url()`
  (draft `?ID=<uuid>` carried through every step URL).
- Mock portal rebuilt as the same 6 steps; new
  `scripts/test_mock_portal.py` proves the flow in real Chromium
  (MOCK-0001) — Chromium install once failed, succeeded on retry.
- Dry-run now logs all 6 steps and warns (not fails) when payout info
  is missing; the live gate still refuses it. Face-value gaps still
  fail in dry-run.
- Tests: pytest 15 passed (was 4), dry-run end-to-end passed, mock-portal
  browser test passed, Flask smoke test passed.
- STILL UNVERIFIED: the "Create Listing" click itself (needs card on
  file + face value + payout), and sale detection remains a stub.

## v1.0.0 — 2026-10-28 — Production-ready package

- Hardened `app.py`: no debug mode by default (`FLASK_DEBUG` env only),
  `/api/health` endpoint, structured logging to `logs/app.log` + console,
  request validation on every write endpoint (event, price, quantity,
  bulk cap 1–50), JSON error handlers (404/405/400/500), host/port from
  env (`FLASK_HOST`/`FLASK_PORT`, default `127.0.0.1:5002`), startup
  live-mode guard — refuses `LIVE_MODE=True` + `DRY_RUN=False` without
  `auth_state.json` **and** `LIVE_CONFIRM=yes`.
- Hardened `viagogo_bot.py`: page/action timeouts, retries with backoff
  (max 3 attempts), structured logging, never logs session contents.
- Hardened `discord_notify.py`: webhook format validated before sending,
  retries with backoff (max 3), webhook URL never logged, failures return
  an error dict instead of crashing the API.
- Packaging: `run.sh` (Linux/macOS) + `run.bat` (Windows), `Dockerfile`
  (python:3.11-slim, non-root user, healthcheck on `/api/health`),
  `docker-compose.yml`, systemd example `viagogo.service`.
- Delivery: new `DELIVERY.md` (5-minute Windows/Linux setup, dry-run demo,
  live go-live checklist); README updated to point to it.
- Tests re-run green: pytest 4 passed, dry-run end-to-end script passed,
  fresh Flask smoke test passed (see DELIVERY.md § Verification).
- Safety unchanged: `DRY_RUN=True` default, triple live guard
  (`LIVE_MODE=True` + `DRY_RUN=False` + `auth_state.json` + `LIVE_CONFIRM=yes`).
- Honest limits (unchanged): live portal selectors are **unverified**
  (no Viagogo account was available), sale detection is a **stub** until
  live verification, no official Viagogo seller API exists.

## v0.1.0 — 2026-10-28 — MVP

- Flask UI + API on port 5002, Playwright seller-portal bot (listing-only),
  pricing rules (markup/clamp/round to .99), Discord webhook sale alerts,
  SQLite storage, mock seller portal, pricing unit tests (4 passed),
  dry-run end-to-end script.
