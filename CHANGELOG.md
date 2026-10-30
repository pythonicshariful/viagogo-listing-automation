# Changelog

## v1.5.2 — 2026-10-30 — Fix live-test reliability and training-data controls

- Added bundled Chromium, Chrome, and Edge launch fallback with an actionable
  setup error when no browser is available.
- Added explicit live-check phases and infrastructure-failure evidence,
  including the browser-launch error and unavailable screenshot state.
- Fixed the standalone live verifier's artist-page event click-through call.
- Made Collect now validate Live scans before starting and show an immediate
  settings action when live scans are disabled.
- Preserved watchlist category and currency choices, inferred neutral event
  categories from URLs, and kept live scan currencies attached to prices.
- Added regression coverage for browser failures, collector behavior,
  evidence, and watchlist metadata.

## v1.5.1 — 2026-10-28 — Fix the live check: event pages, visible browser, dashboard live check

Shariful ran `scripts/verify_live.py` on his real Windows PC and all
three checks came back empty (all-None), the sell-gate output cut off,
and the browser never appeared on screen. Root cause
(`LIVE_VERIFICATION.md` §8): (1) the parser could not read the
"Tickets: 1,265.69 USD" format at all; (2) two of the three checked
pages were artist pages — the Real Madrid and FC Barcelona artist
pages contain NO prices for one event (the v1.5.0 evidence table
wrongly listed the "Tickets:" lines as if they were on the Barcelona
artist page — they live in structured per-event data / single-event
pages); (3) the browser never got the rendered event list and the
challenge check missed DataDome wording; (4) the sell gate launched a
second browser with no progress output and headless was the default.
His `logs/app.log` was the Flask log only — `verify_live.py` logged to
the console, so the reason was never findable in app.log. The settings
400 at 17:32:12 (then 200 at 17:32:14) was the live-confirmation guard
or a validation error he corrected 2 seconds later; the UI does show
settings errors, so it was not a silent failure.

- **Parser reads suffix-code prices (`market.py`).**
  `parse_suffix_prices` / `parse_tickets_price` read "Tickets:
  1,265.69 USD" (wired into `parse_prices` / `parse_snapshot_text`).
  A bare year ("2026 USD") is rejected. Lowest is now the cheapest
  amount actually on the page across all formats (Metallica artist
  page: lowest $463, not $895 — the first "From" is only the first
  event's price). The Barcelona excerpt alone now returns lowest
  $172.51 USD instead of all-None.
- **Artist pages are detected, not silently trusted (`market.py`).**
  `detect_page_kind` ("39 events in all locations" → artist),
  `is_empty_page`, `looks_like_artist_page_url` (path ends in
  "-Tickets"; the /E-<id> artist shape cannot be told from an event
  URL, so content detection is the real test). A snapshot from an
  artist page carries `page_kind`, `events_count` and a plain-English
  `page_note` ("This page lists 39 events — it is an artist page…").
- **The browser waits for real content (`market.py`).** `_read_page`
  waits for event rows / prices (up to the page timeout), scrolls,
  then checks for a challenge AFTER the wait; `collect_with_diagnostics`
  returns the snapshot + diagnostics (title, final URL, HTTP status,
  text length, 500-char excerpt, challenge, screenshot) and an empty
  page is source `"live-empty"`, never silently "live" all-None.
  `collect_event_via_artist` clicks through from an artist page to a
  single-event page. `scan_with_report` reports `"live-empty"` as a
  live error with a plain reason.
- **DataDome detection (`stealth.py`).** Challenge markers now include
  "datadome", "captcha-delivery", "please enable js", "enable
  javascript", "disable any ad blocker", "verify your browser" and
  titles "datadome" / "access denied" (datadome checked first).
- **Dashboard live check (Opportunities page, section 4 + `livecheck.py`,
  NEW + `app.py`).** `POST /api/live-check` starts a background run
  (202 + run id; 409 if one is running; 400 if the watchlist is
  empty), `GET /api/live-check/<id>` returns status + per-event
  results + diagnostics + sell-gate result + evidence file,
  `GET /api/live-check` lists recent runs. The page has a "Run live
  check" button + "Show browser" checkbox, live progress and results
  in the page, and an evidence note. The run uses the watchlist's
  first 3 URLs + the sell-portal gate and never logs in or posts
  anything. Watchlist POST returns a plain-English `warning` when the
  URL looks like an artist page; `addWatch()` shows it.
- **`scripts/verify_live.py` rewritten.** `--headed` flag (shows the
  browser; default hidden), diagnostics printed to the console with
  flush, evidence file `logs/live-check-<run>.txt` + screenshots,
  progress lines before slow steps. Checks: Metallica artist page
  (control) + click-through to the Metallica Oct 29 single event +
  click-through to a Real Madrid single event + sell gate (timeouts,
  never hangs).
- **Tests: 163 passed** (was 137: +26 in new `tests/test_livecheck.py`
  — suffix parsing, artist-vs-event, DataDome, diagnostics,
  live-check API with a mock runner, watchlist warning; new fixture
  `tests/fixtures/real_artist_pages_20261028.txt` is verbatim excerpts
  from the real pages fetched 2026-10-28). Full e2e scripts + mock
  portal + fresh Flask smoke test (temp port + temp DB, no .env)
  including the new live-check endpoints all pass.
- **Still unproven:** the v1.5.1 live check has not yet been run
  against the real site on a real PC (this dev VM's Chromium cannot
  reach Viagogo — egress proxy 403). Re-run from the dashboard
  (section 4) or `python scripts/verify_live.py --headed` on a normal
  computer.

## v1.5.0 — 2026-10-28 — Real live site checks + automatic ML training-data collection

- **Real Viagogo page parsing (`market.py`).** The parser now reads the
  words Viagogo really shows: "Tickets from $813" → lowest price
  ($813.0, USD), "3,895 people viewed … in the past hour" → 3895,
  "Only 1% of tickets left" / "Selling fast" / "Top seller" →
  demand signals, "20 tickets left" → listing count. The page's own
  currency ($/£/€) now wins over the watchlist entry's currency.
  `scan_with_report()` returns (snapshots, live_errors); a failed live
  check keeps source "live-challenge"/"live-failed" with prices None —
  it never falls back to sample data.
- **Honest LIVE vs SAMPLE, everywhere.** Every scan is labelled:
  dashboard LIVE DATA (green) / SAMPLE DATA (amber) badge, plus
  `"source": "live"` / `"source": "sample"` in `/api/opportunities`
  and `/api/scan` (`data_source`). An explicit live request with Live
  scans OFF → **400** ("Live scans are OFF… Nothing was scanned, and no
  sample data was substituted."); a live scan where every check fails
  → **502** with `live_errors`. The scanner refuses to silently
  downgrade a live request to mock.
- **Auto-collector (`collector.py`, NEW).** A background scheduler thread
  started with the Flask app (also under WSGI): scans the whole
  watchlist on a configurable interval (default every 6 hours, 1–24h),
  stores ONLY live snapshots in `price_snapshots` as ML training data.
  Never crashes the app, never loses old snapshots; a failed run is
  logged and the schedule continues. Dashboard controls on the
  Opportunities page (enabled, interval, run-on-start, "Collect now")
  + `GET/POST /api/collector` + `POST /api/collector/run-now`.
- **Training data section (Opportunities page, card 3).** Total / live /
  sample snapshot counts, events tracked, first→last date range, next
  scheduled run, last run status, plain-English ML readiness, and
  Download training data (CSV)/(JSON) links.
- **Export (`GET /api/snapshots/export?format=csv|json&source=live|sample|all`).**
  Default: CSV, live rows only, downloaded as
  `viagogo-training-data.csv`. Columns: snapshot_at, event_name,
  event_url, category, section, currency, lowest_price, avg_price,
  listings_count, people_searching, recent_sold_prices, days_to_event,
  source.
- **Live evidence (`LIVE_VERIFICATION.md`, NEW) + `scripts/verify_live.py`
  (NEW).** Real pages checked 2026-10-28: Metallica artist page
  (viagogo.com), Real Madrid CF artist page (E-151961718), FC Barcelona
  artist page (viagogo.co.uk) — real prices $1,265.69 (El Clásico Oct 25),
  $172.51, $277.80, $638.50. Plain HTTP gets a DataDome 403 (real
  browser required — validates the design). **Live Playwright could NOT
  run on the dev VM:** its egress proxy answers Chromium's CONNECT with
  403 `policy_denied` (net-log proven). The same browser code was proven
  against the real Viagogo page text on a local copy (lowest $813 USD,
  3,895 people, 20 tickets left). `scripts/verify_live.py` is the live
  proof for a normal computer.
- **Watchlist seed updated to real pages:** Metallica + Real Madrid CF
  now use the real public artist pages (verified live 2026-10-28).
- **Tests: 137 passed** (was 120: +17 in new `tests/test_autocollect.py`,
  incl. parser tests against the real-page fixture
  `tests/fixtures/real_page_text.txt`, real-Chromium scan of the real
  page structure, downgrade-refusal 400/502, export shape, failure
  survival). Full pytest + both e2e scripts + mock portal + fresh Flask
  smoke (16/16) green.

## v1.4.1 — 2026-10-28 — Dashboard UI redesign (ui-ux-pro-max skill)

- **Modern dashboard UI, both pages rebuilt** (`templates/index.html`,
  `templates/opportunities.html`) following the
  [ui-ux-pro-max skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
  (design-system search: "ticket seller dashboard modern clean",
  Vibrant &amp; Block-based style, density 8/10 dashboard, motion 3/10
  subtle). Sticky header with brand, nav (Listings / Opportunity
  Scanner) and the mode badge always visible; numbered section cards
  with shadows and a clear visual hierarchy; 2-column form grids on
  desktop, single column on mobile; violet primary buttons, orange
  accent for the two hero actions (Create drafts, Run scan), red danger
  for Delete / Clear session; status pills in the listings table and
  demand/risk pills on the Opportunities page; dark code-output blocks;
  visible focus rings, 40px minimum touch targets, `prefers-reduced-motion`
  respected. No external CDN or font downloads — fully self-contained
  inline CSS, works offline. Emoji icons replaced with inline SVG (skill
  rule: no emoji as icons). The DRY-RUN badge and the speculative-listing
  warning stay prominent at the top of every page.
- **Functionality unchanged.** Every element id, form field name, API
  call, button label and JS function is exactly as in v1.4.0 (verified:
  all ids present, pytest 120 passed, both pages 200, screenshots
  checked on desktop 1280px and mobile 390px).

## v1.4.0 — 2026-10-28 — Production-ready: payout per listing + real sale detection

- **Payout info per listing (closes the gap open since v1.1.0).**
  `db.py`: new `payout_method` (PayPal / Direct deposit) + `paypal_email`
  columns on `listings`, with a graceful migration (`ALTER TABLE` if the
  columns are missing) so databases created by v1.3.1 keep working and
  their old rows read back with the PayPal default. `create_listing` /
  `update_listing` store them; `public_listing()` returns listings with
  the email masked (first 4 chars + `***`, same as the NopeCHA key) and
  the API never returns the full email. The single-create and bulk-create
  endpoints validate them (PayPal requires a valid email, Direct deposit
  needs none) and the bulk form carries one payout for the whole batch.
  The dashboard shows the payout in the listings table (masked email).
  The bot's live pre-flight (`validate_price_inputs` + step 6) already
  used the listing's own payout info — it now always has real data to
  check, and refuses a live post without it. **One real bug found by
  the secrets audit:** `stealth.type_like_human()` logged the first 20
  characters of whatever it typed — including the PayPal email when
  typing failed and it fell back to `.fill()`. It now logs only the
  value's length, with a regression test.
- **Real sale detection (the `/api/sales/check` stub is gone).**
  `viagogo_bot.py`: `check_sales(listings)` drives the logged-in seller
  dashboard (`my.viagogo.com/seller/listings`, overridable with
  `VIAGOGO_SALES_URL`) with the saved session and matches sold rows to
  local listings in layers — exact text match → partial text match →
  page-text scan — logging which method matched each sale, and parsing
  the sale price from the row (falling back to the listing price).
  Returns `{"available", "reason", "sales"}`: in dry-run, or live
  without a saved session, it returns `available: false` with a
  plain-English reason and NEVER opens a browser or fakes a sale. New
  mock pages `mock/mock_sales_portal.html` (1 sold listing, $992.99)
  and `mock/mock_sales_portal_none_sold.html` (0 sales); new
  `tests/test_sales.py` (7 cases) + the mock-portal script now also
  proves sold-found (exact-text-match) and none-sold. The endpoint
  records newly-sold listings, fires the existing Discord sale alert,
  and never notifies twice for the same sale. Honest limit: the real
  sales-page URL and selectors are NOT verified against a real sale
  yet — the first real sale must be confirmed by hand.
- **Production polish sweep.**
  (a) Default Max price raised 500 → 1500 everywhere it was stated
  (`app.py` `_config()`, dashboard input, `config.example.json`,
  README tour + FAQ, DELIVERY.md) — USD events like Metallica (~$860)
  no longer clamp to 499.99 by default; the README tour no longer
  tells the user to raise it before scanning.
  (b) App still starts with zero config files and no `.env` (verified
  by the fresh smoke test below).
  (c) UI errors are plain English: new `app._plain_error()` (one line,
  capped, never a traceback) for bot failures, and `/api/sales/check`
  failures return a plain-English error instead of crashing; the 500
  handler already returned a generic message. Full tracebacks stay in
  `logs/app.log` only.
  (d) Secrets audit: every `logger` call reviewed — Discord webhook
  URL, session contents, PayPal email, NopeCHA key and proxy
  credentials are never logged (proxy shown only masked, key/email
  only masked, session only by file name/size/cookie count). The one
  leak found (stealth typing fallback, above) is fixed and tested.
  (e) Delivery zip contains no `venv/` / `*.db` / `.env` /
  `auth_state.json` / `logs/` / `__pycache__` (verified below).
- **Docs:** new `HANDOVER.md` (one-page client handover in simple
  English: what Fayed gets, 3-step start, exactly what only he can
  provide, and precisely what is / is not proven). README honest
  limits updated (sale detection implemented-but-unverified-live,
  payout per listing). DELIVERY.md go-live checklist step 8 updated.
- Tests: **120 passed** (102 existing still passing + 10 payout
  (incl. plain-error) + 7 sale detection + 1 stealth log-hygiene), dry-run + scanner end-to-end
  passed, mock-portal MOCK-0001 + mock sale detection passed, fresh
  Flask smoke test on a temp port + temp DB with NO `.env` file passed.

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
