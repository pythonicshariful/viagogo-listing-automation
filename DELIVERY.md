# Delivery — Viagogo Listing Automation v1.5.1

**Listing-only. The bot never buys tickets.** After a sale, the client buys
the ticket manually and delivers it.

> **Honest status — read this first.** This is a **production-ready
> package**: hardened app, logging, validation, packaging, tests green.
> The 6-step Sell pipeline is now **verified to PriceDetails** against
> the real portal (observed live 2026-10-28, logged in, Metallica sample,
> no listing created). **Still unverified: the "Create Listing" click itself.**
> **New in v1.4.0: payout per listing + real sale detection** — every
> listing carries its own payout method (PayPal email or Direct
> deposit, email shown only masked); `/api/sales/check` now drives the
> seller dashboard and matches sold rows (exact → partial → page-text
> scan), proven against the mock sales pages only — the real sales
> page is NOT verified against a real sale yet. Default Max price
> raised 500 → 1500. See HANDOVER.md for the one-page client handover.
> **New in v1.5.0: real live site checks + automatic ML training-data
> collection.** `market.py` now parses the REAL Viagogo page text
> ("Tickets from $813", "3,895 people viewed …", "Only 1% of tickets
> left") and the scanner is honest about what it is showing: every
> scan is labelled LIVE or SAMPLE (dashboard badge, `/api/opportunities`,
> `/api/scan`), an explicit live request with Live scans OFF is refused
> with a 400, and if every live check fails you get a 502 with the
> reasons — sample data is NEVER substituted for a failed live request.
> A new auto-collector (`collector.py`) runs in a background thread with
> the app (default every 6 hours, configurable in the Opportunities
> page, "Collect now" button, run-on-start toggle) and stores ONLY live
> snapshots as ML training data; a failed run is logged and the schedule
> keeps going. New Training data section on the Opportunities page
> (stats, next run, last status, ML readiness in plain English) and a
> download endpoint `GET /api/snapshots/export?format=csv|json`. Full
> evidence in `LIVE_VERIFICATION.md`. **Honest limit, read it:** a live
> Playwright run against viagogo.com could NOT be done from the dev VM
> — its egress proxy answers Chromium's CONNECT with 403
> `policy_denied` (proven with a net-log; plain HTTP gets a DataDome
> 403). The same browser code was proven against the real Viagogo page
> text on a local copy (lowest $172.51 USD — the cheapest real price
> in the mashed fixture; headline from_price $813 — 3,895 people, 20
> tickets left).
> The live proof is `scripts/verify_live.py` — run it on a normal
> computer. Until that passes, "live verified against viagogo.com" is
> NOT claimed.
> **New in v1.5.1: the live check is fixed — and it now runs from the
> dashboard.** Shariful ran `verify_live.py` on his real Windows PC on
> 2026-10-28 and ALL THREE checks came back empty (all-None), the sell
> gate output cut off, and the browser never appeared on screen. The
> root cause is in `LIVE_VERIFICATION.md` §8: (1) the parser could not
> read the "Tickets: 1,265.69 USD" format at all; (2) two of the three
> checked pages were artist pages — the Real Madrid and FC Barcelona
> artist pages contain NO prices for one event, only event lists
> (the v1.5.0 table wrongly listed the "Tickets:" lines as if they
> were on the Barcelona artist page — they live in structured
> per-event data / single-event pages); (3) the browser never got the
> rendered event list and the challenge check missed DataDome wording;
> (4) the sell gate launched a second browser with no progress output,
> so it looked hung, and headless was the default. v1.5.1 fixes all
> four: the parser reads suffix-code prices; the check uses
> single-event pages (the dashboard warns in plain English when you
> paste an artist-page URL, and the parser reports `page_kind:
> "artist"` whenever it sees one); the browser waits for real content,
> scrolls, and checks for a DataDome challenge AFTER the wait, and an
> empty page is reported as `live-empty` instead of silently "live"
> all-None; the sell gate has timeouts and prints progress; `--headed`
> shows the browser on screen; and the Opportunities page has a new
> section 4 **"Live check"** — a Run live check button + "Show
> browser" checkbox, per-event progress and results in the page, and
> an evidence file (`logs/live-check-<run>.txt` + screenshots) for
> every run. The check never logs in and never posts anything.
> **Still unproven:** the v1.5.1 live check itself has not yet been
> run against the real site on a real PC — that is the exact remaining
> step (dashboard section 4, or `python scripts/verify_live.py
> --headed`).
> **New in v1.4.1: dashboard UI redesigned** with the ui-ux-pro-max skill
> (sticky header, mode badge always visible, numbered cards, styled
> buttons/tables/pills, mobile-responsive, no external dependencies) —
> functionality unchanged.
> **New in v1.3.0: every setting is in the dashboard (Settings, main
> page)** — mode, session upload, scanner, proxy (+ test button),
> stealth, seller fee %, server (host/port/log level, restart to apply).
> NO .env file is needed: the app runs with safe defaults and stores
> settings in the local database. `.env` remains only as an optional
> override for advanced users. Live mode still needs the two-step
> confirmation (tick the box AND type LIVE) and live actions are still
> refused without a saved session. **New in v1.2.2: optional NopeCHA CAPTCHA solving** (`captcha.py`) —
> OFF by default, no key configured: with no key the bot still stops
> on a challenge exactly as before. With the operator's own key pasted
> in the dashboard and the toggle on, it attempts ONE solve per
> challenge page (Token API first). Solving a CAPTCHA may violate
> Viagogo's terms and increases account-ban risk; NopeCHA does not
> guarantee a solve. **New in v1.2.1: stealth / anti-detection hardening** (`stealth.py`) —
> randomised desktop UA/viewport, seller-store locale/timezone, an init
> script hiding the usual automation tells, and typing/click jitter.
> It **reduces** detection risk but does **NOT** guarantee invisibility,
> and by default it **never** bypasses a CAPTCHA or Cloudflare challenge: if one
> appears the bot stops and reports it. **New in v1.2.0: the Opportunity
> Scanner** (heuristic scoring, NO ML) — it ranks watched events by
> profit × confidence and alerts on Discord.
> Scanner scores are computed from the latest snapshot only and mock
> scans use labelled SAMPLE numbers — they are not live market data and
> must never be acted on. Live scans need the "Live scans" toggle in
> Settings + Fayed's real event list. ML prediction is Phase 2 and needs weeks of collected
> snapshots first. **New in v1.5.0: the auto-collector builds that
> dataset by itself** — it runs with the app (default every 6 hours),
> scans the whole watchlist, and stores ONLY live snapshots as training
> data. **How this becomes ML training data:** every row in
> `price_snapshots` (downloadable as CSV/JSON from
> `/api/snapshots/export`) is one observation — when it was taken,
> which event, the event URL, category, section, currency, lowest
> price, average price, listing count, people searching, days until
> the event, and the source (live/sample). Phase 2 ML learns from the
> *change* in these numbers over time (price going up as the event gets
> closer, listings disappearing, demand signals appearing) — that is
> why it needs **weeks of daily snapshots, roughly 20+ live snapshots
> per event** before a model is worth training. A single snapshot tells
> you today's price; a history of snapshots teaches the model how prices
> move. The collector is what builds that history automatically — no
> one has to remember to click anything.

## What the client gets

| File | What it is |
|---|---|
| `app.py` | Flask UI + API (port 5002 by default) |
| `viagogo_bot.py` | Playwright seller-portal bot, listing-only — verified 6-step pipeline |
| `stealth.py` | **New in v1.2.1:** anti-detection hardening shared by bot + scanner — randomised UA/viewport, locale/timezone, init script hiding automation tells, typing/click jitter, challenge detection that STOPS the bot (or attempts ONE NopeCHA solve when enabled + configured) |
| `captcha.py` | **New in v1.2.2:** optional NopeCHA CAPTCHA solving — Token API (reCAPTCHA v2/v3, Turnstile) + Recognition API, one attempt per page, key never logged, works without a key and without the `nopecha` package |
| `tests/test_captcha.py` | **New in v1.2.2:** 27 NopeCHA unit tests (all mock/offline) |
| `tests/test_stealth.py` | **New in v1.2.1:** 24 stealth unit tests (pools, init script, challenge detection, jitter, real-Chromium check) |
| `pricing.py` | Markup / clamp / round-to-.99 pricing rules |
| `discord_notify.py` | Discord webhook sale alerts + test message |
| `db.py` | SQLite storage (`data/listings.db`) — v1.4.0: payout columns + migration for old DBs, masked public listings |
| `templates/index.html` | Single-page UI: price rules, bulk form, listings table |
| `mock/mock_seller_portal.html` | Fake 6-step seller flow — proves the browser flow with no Viagogo |
| `mock/mock_sales_portal.html` | **New in v1.4.0:** fake seller sales page (1 sold listing) — proves sale detection offline |
| `mock/mock_sales_portal_none_sold.html` | **New in v1.4.0:** same sales page with nothing sold — detection must find 0 sales |
| `tests/test_payout.py`, `tests/test_sales.py` | **New in v1.4.0:** payout (10) + sale detection (7) + stealth log-hygiene (1) tests |
| `collector.py` | **New in v1.5.0:** auto-collector background thread — every 6h (configurable 1–24h), stores ONLY live snapshots as ML training data, never crashes the app |
| `market.py` (v1.5.1) | Real-page parsers (`parse_from_price`, `parse_currency`, `parse_scarcity`, `parse_suffix_prices` / `parse_tickets_price` for "Tickets: 1,265.69 USD"), artist-page + empty-page detection, wait-for-content + scroll + post-wait DataDome check, `collect_with_diagnostics` (source `live-empty`), `collect_event_via_artist` click-through, `scan_with_report()` — live failures reported, never downgraded to sample |
| `livecheck.py` | **New in v1.5.1:** shared live-check runner (dashboard + script) — first 3 watchlist events + sell-portal login gate (timeouts + progress), diagnostics, evidence files, in-memory run store |
| `scripts/verify_live.py` | **v1.5.1:** live verification for a real computer — Metallica artist page (control) + click-through to the Metallica Oct 29 single event + click-through to a Real Madrid single event + sell-portal login gate, `--headed` flag, diagnostics on console, evidence file — run on a normal machine, NOT on the dev VM |
| `LIVE_VERIFICATION.md` | **v1.5.1:** structured live evidence — URLs, real numbers, Cloudflare/DataDome, VM proxy block, the 2026-10-28 all-None root cause (§8), what is NOT proven |
| `tests/test_autocollect.py`, `tests/fixtures/real_page_text.txt` | **New in v1.5.0:** 17 auto-collector + honest-live tests; parser fixture built from REAL Viagogo page text observed 2026-10-28 |
| `tests/test_livecheck.py`, `tests/fixtures/real_artist_pages_20261028.txt` | **New in v1.5.1:** 26 live-check tests (suffix parsing, artist-vs-event, DataDome, diagnostics, live-check API with a mock runner, watchlist warning); fixture is verbatim excerpts from the real pages fetched 2026-10-28 |
| `templates/opportunities.html` (v1.5.1) | Training data section (stats, collector controls, CSV/JSON download) + LIVE/SAMPLE badge on every scan + **new section 4 "Live check"** (Run live check button, "Show browser" checkbox, progress/results, evidence note) + artist-page warning on watchlist add |
| `HANDOVER.md` | **New in v1.4.0:** one-page client handover in simple English |
| `market.py`, `scoring.py` | Opportunity Scanner: public market monitor + heuristic scoring (rules R1–R12, no ML) |
| `templates/opportunities.html` | Opportunities page: watchlist + ranked opportunities |
| `watchlist.example.json`, `mock/sample_snapshots.json` | 5-event watchlist template + SAMPLE market data for offline demos |
| `tests/test_scoring.py`, `tests/test_market_parse.py`, `scripts/test_scanner_end_to_end.py` | Scoring (15) + market-parser (5) unit tests + scanner e2e |
| `run.sh` / `run.bat` | One-command launchers (Linux/macOS / Windows) |
| `Dockerfile`, `docker-compose.yml`, `viagogo.service` | Docker + systemd deployment |
| `config.example.json`, `.env.example` | Templates — no real credentials |
| `README.md`, `CHANGELOG.md`, `DELIVERY.md` (this file) | Docs |

Features: bulk posting (1–50 listings per event), generic listings
(section/zone only, no exact seat), above-market pricing with min/max,
volume control, maintain (post / pause / resume / relist / delete /
reprice), Discord sale alerts, dry-run mode by default, **Opportunity
Scanner**: watchlist, market scans, ranked opportunities (market price,
recommended price — not always cheapest, estimated profit + margin,
demand, risk, confidence, best timing), Discord opportunity alerts.

## Opportunity Scanner demo (no Viagogo account, no Discord needed)

1. Start the app and open `http://127.0.0.1:5002/opportunities`.
2. Click **Load example watchlist** (5 events; Metallica is the verified
   sample, the other 4 are placeholders for Fayed's real events).
3. **Price rules matter:** the USD Metallica sample is ~$860 — the
   default Max price is 1500 since v1.4.0, so it is covered. If you
   lower the Max price below a ticket's real cost, the recommendation
   clamps and profit goes negative. In the UI, check price rules first
   (or `POST /api/config`).
4. Click **Run scan (mock/sample)**. The top opportunity should be
   Metallica: market $860 → list $992.99, est. profit $387.38 (27.7%),
   confidence 100/100, timing "list now". The other 4 events have no
   sample data, so they score confidence 0 — that is the honest
   behaviour, not a bug.
5. Click **Send top opportunity to Discord (test)** — the payload is
   built (not sent without a webhook).

Live scan (only when Fayed's real events are in the watchlist): switch
"Live scans" ON in Settings → Scanner, then run a scan. Live scans wait
≥5s between pages and use the proxy from Settings if set (residential
rotating proxies recommended).

## Stealth (v1.2.1) — what changed, what it does NOT do

Both browser flows (seller bot + market scanner) now launch through
`stealth.py`, on by default: a randomised desktop user-agent + viewport
per launch, locale/timezone matching the seller store (`en-US` /
`America/New_York`, changeable in Settings → Stealth), an init
script hiding `navigator.webdriver` / missing `window.chrome` / empty
plugins / headless permissions and languages, character-by-character
typing on the search box and price fields, and a small random mouse move
before clicks. The proxy from Settings keeps working with stealth on.

**Honest limits:** this only removes the most obvious automation tells.
It does NOT defeat Cloudflare and does NOT guarantee invisibility.
By default it **never** bypasses a CAPTCHA or Cloudflare challenge: `detect_challenge()`
checks every page load, and if a challenge appears the bot stops
immediately, logs `CHALLENGE DETECTED (…)`, and raises
`ChallengeDetectedError` (the listing bot does not retry it; the scanner
records that event as `live-challenge`). If challenges appear often, stop
automating and use the portal by hand. Disable stealth for debugging with
`STEALTH_ENABLED=False`.

## NopeCHA setup (v1.2.2) — optional, add the key from the dashboard later

No key is configured in this delivery, and none is needed: the bot
works exactly as before (it stops on a challenge). When the operator
has a key, there are two ways to add it — the dashboard way is the
one Shariful asked for:

1. **Get a key:** sign up at https://nopecha.com and copy the API key
   from the NopeCHA dashboard. Free tier: 100 recognitions/day.
   Starter: $4.99/month (2,000 solves/day). The subscription is the
   operator's to pay for.
2. **Paste it in the dashboard:** open the app (`http://127.0.0.1:5002`),
   go to section **4. CAPTCHA Solver (NopeCHA)**, paste the key into
   the password field, tick **Enable NopeCHA solving**, and click
   **Save CAPTCHA settings**. The key is stored in the local SQLite
   config (`nopecha_api_key`) and shown back only masked
   (first 4 chars + `***`); it is never logged and never appears in
   an API response in full.
3. **Verify it:** click **Check status / balance** — this calls
   `GET https://api.nopecha.com/v1/status` with the key and shows the
   plan / credits. Click **Test (mock solve)** to prove the wiring
   without spending credits: it makes NO real API call.
4. **Alternative (`.env`):** set `NOPECHA_API_KEY=<key>` and
   `NOPECHA_ENABLED=true` in `.env` and restart. An env key wins over
   the dashboard key. Never commit `.env` or a real key.

What changes once it is enabled: when a challenge page appears, the
bot attempts **one** Token-API solve for that page (reCAPTCHA v2/v3
or Cloudflare Turnstile sitekey → token, injected into the page) and
continues only if a token is returned; Recognition is the fallback
for image/audio challenges. If solving fails, or the challenge has
no sitekey (Cloudflare "Just a moment…" interstitial), the bot still
stops exactly as before — never more than one attempt per page.

**Honest limits:** solving a CAPTCHA to bypass anti-bot controls may
violate Viagogo's terms and increases account-ban risk; NopeCHA does
not guarantee a solve. The hCaptcha Token endpoint was discontinued
by NopeCHA in Oct 2026, so hCaptcha solves may fail with 410.

## ⚠️ Warning — speculative listings

**Viagogo prohibits speculative listings** — listings for tickets the
seller does not yet own — and can remove listings, fine the seller, or
**permanently suspend the seller account**. This tool gives **no
guarantee of account safety**. The client must accept that risk in
writing before any live run, and listings should only be posted for
tickets the client can actually buy and deliver. Viagogo also uses
Cloudflare bot protection, so automated access may be blocked or
rate-limited at any time.

## 5-minute setup — follow the README (single source of truth)

The full install guide for a non-technical user lives in
**README.md, Steps 1–3**: install Python 3.11+ from python.org
(tick "Add python to PATH", check with `python --version`), get the
program (GitHub → Code → Download ZIP → Extract All), then start it
(Windows: double-click `run.bat`; Mac/Linux: `./run.sh`) and open
http://127.0.0.1:5002. No `.env` file is needed. Do not duplicate those
steps here — if the README and this file ever disagree, the README wins.

Browser binary (only needed for live / mock-portal mode):

```bat
run.bat install-browser
```

```bash
./run.sh --install-browser
```

Docker alternative:

```bash
docker compose up -d --build
# open http://127.0.0.1:5002 ; logs: docker compose logs -f
```

systemd (VPS, long-running): copy `viagogo.service` to
`/etc/systemd/system/`, edit paths/user, then
`systemctl daemon-reload && systemctl enable --now viagogo`.

## First dry-run demo (no Viagogo account, no Discord needed)

1. Start the app (`run.bat` / `./run.sh`) and open `http://127.0.0.1:5002`.
   The banner shows **DRY-RUN**.
2. Check health: open `http://127.0.0.1:5002/api/health` — expect
   `{"ok": true, "status": "healthy", "version": "1.3.1", "dry_run": true}`.
3. Set price rules (default: +80% markup, min £50, max £1500, round to .99).
4. Bulk-create 3 listings for the sample event (face £100 → listing
   **£179.99**). They appear as **draft**.
5. Click **Post** on one — it returns a fake id like `DRY-0001`.
   **Nothing is posted to Viagogo in dry-run.**
6. Click **Simulate sale** — the Discord payload is built (not sent
   without a webhook) and the listing becomes **sold**.
7. Try **Pause / Resume / Reprice** on the others.

Run the automated checks any time:

```bash
python -m pytest tests/ -q
python scripts/test_end_to_end.py
```

## Live go-live checklist — do NOT skip

Do these in order. Stop at the first failure and fix it before continuing.

- [ ] **1. Session login.** Log in to the client's Viagogo seller account
  once in a browser, save the Playwright session (storage_state), and
  upload it in the dashboard: Settings → Seller session.
  (Never put a username/password in any file in this repo.)
- [ ] **2. One sample event.** Replace the placeholder in
  `config.example.json` with ONE real Viagogo event URL from the client's
  account.
- [ ] **3. Discord webhook.** Paste the real webhook URL in the UI and click the Discord test button —
  confirm the test message actually arrives in Discord.
- [ ] **4. Card on file, face value, payout.** Add a valid credit/debit
  card to the seller account **by hand** (the bot never enters card
  details and refuses without one), have a face value for the listing,
  and set a payout method (PayPal email or Direct deposit). The bot
  pre-flights all three on PriceDetails.
- [ ] **5. One-listing live test — by hand first.** Create exactly 1
  listing on the sample event **by hand** in the portal, so the
  "Create Listing" click and the confirmation are confirmed once.
  Then switch to live in Settings → Mode (tick the box AND type LIVE),
  and post **exactly 1 listing** via the bot. Confirm it appears in the
  seller dashboard. (Live actions are refused without a saved session
  and without the two-step confirmation — that is deliberate.)
- [ ] **6. Small bulk batch.** Only after step 5 works: a batch of 3–5
  listings. Confirm they appear and the prices are right.
- [ ] **7. Written risk acceptance.** The client confirms in writing that
  they accept the speculative-listing suspension risk (see warning above).
- [ ] **8. Sale detection — confirm the first real sale by hand.**
  `/api/sales/check` now drives the seller dashboard (v1.4.0) and is
  proven against the mock sales page, but the real sales-page URL and
  selectors are NOT verified against a real sale yet. After the first
  real sale, open the seller dashboard and check that the listing is
  marked sold here too. If the bot misses it, send Shariful the page
  layout (or a screenshot) so the selectors can be fixed. Until then,
  also watch the seller dashboard / email — the Discord alert from the
  simulate path is the proven channel.

To go back to safe mode at any time: switch Mode back to Dry-run in
Settings — nothing can be posted live in dry-run.

## Verification (done 2026-10-28, this machine)

| Check | Result |
|---|---|
| `pytest tests/ -q` (v1.5.1) | **163 passed** (was 137: +26 live-check tests in new `tests/test_livecheck.py` — suffix parsing, artist-vs-event, DataDome, diagnostics, live-check API with a mock runner, watchlist warning; fixture `tests/fixtures/real_artist_pages_20261028.txt` is verbatim excerpts from the real pages fetched 2026-10-28) |
| Fresh Flask smoke test v1.5.1 (temp DB, port 5099, NO .env file, run from /tmp) | **PASSED** — live-check endpoints through real HTTP: `/api/health` 200, `/opportunities` 200 (Live check card present), live-check with empty watchlist → **400**, watchlist add with artist URL → **201 + warning** ("This looks like an ARTIST page…"), live-check start → **202 + run_id**, second start while running → **409**, status → "running", unknown run → **404**, run list contains the run. The background browser run itself was NOT awaited on this VM (Chromium cannot reach Viagogo here — see `LIVE_VERIFICATION.md` §4). |
| `python scripts/test_end_to_end.py` + `scripts/test_scanner_end_to_end.py` + `scripts/test_mock_portal.py` (v1.5.1) | **PASSED** — both end-to-end scripts green; mock-portal MOCK-0001 + mock sale detection ($992.99) + none-sold (0 sales) + dry-run sale check "not available" (unchanged behaviour) |
| Fresh Flask smoke test v1.5.0 (temp DB, port 5051, NO .env file, run from /tmp) | **PASSED** — all 16 checks: `/api/health` 200 v1.5.0 dry-run, `/` + `/opportunities` 200 (Training data section + Collect now button present), seed 5, sample scan labelled `data_source: "sample"` with SAMPLE DATA warning and empty `live_errors`, live request with toggle off → **400** ("Live scans are OFF…"), training stats (5 total / 0 live / 5 sample, "No live training data yet"), CSV export header + 5 rows labelled mock-sample, JSON live-only export empty, collector status defaults (enabled, 6h, "never run"), run-now starts and records "skipped — live scans are off", **real browser scan over local HTTP against the real Viagogo page text: lowest $813 USD, 3,895 people, 20 tickets left, signals only_1pct_left/selling_fast/top_seller** |
| `pytest tests/ -q` (v1.5.0) | **137 passed** (was 120: +17 auto-collector + honest-live, all mock/offline except 2 real-Chromium tests against the real-page fixture) |
| `python scripts/verify_live.py` (v1.5.0, on this dev VM) | **FAILED — as documented, not hidden.** All 3 real pages → `live-failed` (no prices); sell.viagogo.com → `net::ERR_TUNNEL_CONNECTION_FAILED`. Cause: the VM's egress proxy answers Chromium's CONNECT with 403 `{"detail":"The proxy did not authorize this connection.","error":"policy_denied"}` (net-log `/tmp/netlog.json`); plain HTTP gets a DataDome 403. The script prints exactly this and exits 1. **Run it on a normal computer for the live proof** — see `LIVE_VERIFICATION.md` §6. |
| `python scripts/test_mock_portal.py` (real Chromium, v1.5.0) | **PASSED** — all 6 steps driven against the mock portal, `MOCK-0001`, nothing posted; **plus** mock sale detection: sold listing 1 found via exact-text-match ($992.99), none-sold page finds 0 sales (none faked), dry-run sale check returns "not available" |
| `python scripts/test_end_to_end.py` + `scripts/test_scanner_end_to_end.py` (v1.5.0) | **PASSED** — both end-to-end scripts green (unchanged behaviour) |
| Clean-dir zip verification v1.5.0 (extract to /tmp, fresh venv, pip install) | **PASSED** — pytest 137 passed, dry-run + scanner end-to-end passed, mock-portal (MOCK-0001 + sale detection) passed, full smoke test 16/16 passed from the extracted zip (port 5052, temp DB, NO .env). Zip contains no `venv/` / `*.db` / `.env` / `auth_state.json` / `logs/` / `__pycache__` (47 files). |
| Fresh Flask smoke test v1.4.0 (temp DB, port 5041, NO .env file, run from /tmp) | **PASSED** — all 19 checks: `/api/health` 200 v1.4.0 dry-run, `/` + `/opportunities` 200 with DRY-RUN badge and payout fields in the bulk form, default Max price 1500, settings save (fee 12), bulk 2 drafts WITH payout @ 899.99 (face 500 +80%, masked `sell***`, full email never in the response), bulk without PayPal email rejected 400, listings show payout masked, dry-run post DRY-0001, sales check dry-run returns `available: false` ("not available in dry-run"), Discord test dry-run (not sent), captcha config/test/status with no key ("not configured"), unknown route 404 JSON, log contains no full PayPal email |
| `pytest tests/ -q` (v1.4.0) | **120 passed** (was 102: +10 payout incl. plain-error, +7 sale detection, +1 stealth log-hygiene, all mock/offline except 2 real-Chromium sales tests) |
| `python scripts/test_mock_portal.py` (real Chromium, v1.4.0) | **PASSED** — all 6 steps driven against the mock portal, `MOCK-0001`, nothing posted; **plus** mock sale detection: sold listing 1 found via exact-text-match ($992.99), none-sold page finds 0 sales (none faked), dry-run sale check returns "not available" |
| Clean-dir zip verification v1.4.0 (extract to /tmp, fresh venv, pip install) | **PASSED** — pytest 120 passed, dry-run + scanner end-to-end passed, mock-portal (MOCK-0001 + sale detection) passed, full smoke test passed from the extracted zip (port 5042, temp DB, NO .env). Zip contains no `venv/` / `*.db` / `.env` / `auth_state.json` / `logs/` / `__pycache__` (42 files). |
| README follow-through v1.3.1 (clean zip, /tmp, port 5031, NO .env) | **PASSED** — extracted the delivery zip, `./run.sh` started the app (fresh venv, version 1.3.1, dry-run), `/` showed the DRY-RUN badge, `/opportunities` 200, bulk 3 drafts @ 179.99, dry-run post DRY-0001, simulate sale OK (via `/api/sales/simulate`), seed 5 + mock scan. **One README bug found and fixed by this test:** with default Max price 500, Metallica clamped to 499.99 / profit −$500.02, so the tour now tells the user to set Max price 1500 before scanning — re-ran and confirmed Metallica top $992.99 / profit $387.38 / conf 100 / "list now", placeholders conf 10. Discord test returned the dry-run payload (not sent, no webhook). |
| `pytest tests/ -q` | **102 passed** (was 86: +16 dashboard settings, all mock/offline) |
| Flask smoke test v1.3.0 (temp DB, port 5023, NO .env file) | **PASSED** — app starts with no `.env` at all, `/api/health` 200 v1.3.0 dry-run, `/` + `/opportunities` 200, settings get/save round-trip (fee 12), live toggle without confirmation rejected 400, live toggle with tick + `LIVE` accepted with a session blocker listed, back to dry-run OK, proxy test with no proxy rejected 400, session upload accepted (contents never shown) + clear removes it |
| `pytest tests/ -q` (v1.2.2) | **86 passed** (was 59: +27 NopeCHA, all mock/offline) |
| `python scripts/test_scanner_end_to_end.py` | **ALL SCANNER END-TO-END CHECKS PASSED** — seed 5 watchlist events → mock scan 5 snapshots → top opportunity Metallica market $860 → list $992.99, profit $387.38 (27.7%), confidence 100/100, "list now" → Discord opportunity payload built (not sent) → snapshots history 5 rows → /opportunities page 200 |
| `python scripts/test_end_to_end.py` | **ALL DRY-RUN END-TO-END CHECKS PASSED** (unchanged) |
| Flask smoke test v1.2.2 (temp DB, port 5013) | **PASSED** — `/api/health` 200 v1.2.2 dry-run, captcha config empty → test/status without key return "not configured" (no HTTP call), save fake key → config returns masked only (full key never in response), mock test passes with key, non-boolean enabled rejected 400, main + opportunities pages render the CAPTCHA section |
| Flask smoke test v1.2.1 (temp DB, port 5012) | **PASSED** — `/api/health` 200 v1.2.1 dry-run, seed 5, scan mock-sample, top Metallica profit $387.38 conf 100, snapshots 5, Discord test dry-run, /opportunities page 200 |
| Flask smoke test v1.2.0 (temp DB, port 5011) | **PASSED** — `/api/health` 200 v1.2.0 dry-run, seed 5, scan mock-sample, top Metallica profit $387.38 conf 100, snapshots 5, Discord test dry-run, **live-scan guard: live requested with SCAN_LIVE=False stayed mock-sample**, /opportunities page 200 |
| `python scripts/test_mock_portal.py` (real Chromium) | **PASSED** — all 6 steps driven against the mock portal, `MOCK-0001`, nothing posted. Stealth context + char-by-char typing + mouse-move clicks exercised end-to-end. Chromium install failed once, succeeded on retry (v1.2.0 run). The mock run also proved the card blocker works: the mock's own intro text first tripped it and the bot refused, exactly as designed. |
| Fresh Flask smoke test (temp DB, port 5009) | **PASSED** — `/api/health` 200 v1.1.0 dry-run, `/api/config` 200, bulk 3 drafts @ 179.99 (201), post `DRY-0001` (200, dry-run warning about missing payout info — live would refuse), Discord test dry-run (not sent), simulate sale OK, bad bulk 400, unknown route 404 JSON |
| Live guard test | **CHANGED in v1.3.0 (deliberate)** — the app now always starts so the user can fix blockers in Settings (e.g. upload the session). Live ACTIONS are still refused without a session + the two-step confirmation (verified: live post without a session → 502 "Saved session not found"). Old behaviour (v1.0.0–v1.2.2): `LIVE_MODE=True` + `DRY_RUN=False` with no session refused to start (exit 1). |
| Live "Create Listing" click | **NOT VERIFIED** — needs card on file + face value + payout on the real portal; do step 5 of the checklist by hand first |
| Delivery zip verification | Rebuild the zip after v1.2.1 (see § Zip below) and re-run pytest in the extract |

## Zip

`viagogo-listing-automation-delivery.zip` — v1.5.1, rebuilt 2026-10-28
(195,472 bytes, 50 files), source + docs + scripts only. Excluded: `venv/`, `data/*.db`, `__pycache__`,
`.pytest_cache/`, `.env`, `auth_state.json`, `logs/`. Verified: extracted
to a clean dir, fresh venv, `pytest` 163 passed + both end-to-end
scripts + mock-portal (MOCK-0001 + sale detection) + fresh Flask smoke
test including the new live-check endpoints (see the v1.5.1 verification
rows above). Verify after unzipping with the two commands in
§ First dry-run demo.

## Configuration reference — Settings (dashboard, v1.3.0)

Everything is in the dashboard (main page, section 5 "Settings") and
stored in the local database — **no .env file is needed**:

- **Mode:** Dry-run (safe default) or Live. Live needs the two-step
  confirmation (tick the box AND type `LIVE`); switching back to dry-run
  clears the confirmation.
- **Seller session:** upload / clear the saved `auth_state.json` session;
  status shows file name, size and date — never the contents.
- **Scanner:** Live scans on/off, seconds between live pages (0–30),
  page timeout (5,000–300,000 ms), headless on/off.
- **Proxy:** URL (empty = none) + a Test button (masked in responses).
- **Stealth:** on/off, locale + timezone dropdowns.
- **Seller fee %:** default 10 — used by the Opportunity Scanner profit
  math (confirm the real Viagogo fee %).
- **Server:** host (default 127.0.0.1), port (default 5002), log level —
  these apply after restarting the app.
- Price rules + Discord webhook (sections 1 + 3) and NopeCHA (section 4)
  were already in the UI and still work the same way.

Advanced users only: the same values can be forced with environment
variables (`.env.example` lists them: `DRY_RUN`, `LIVE_MODE`,
`LIVE_CONFIRM`, `FLASK_HOST`, `FLASK_PORT`, `LOG_LEVEL`,
`DATABASE_PATH`, `VIAGOGO_SESSION_FILE`, `VIAGOGO_PROXY`,
`PLAYWRIGHT_HEADLESS`, `VIAGOGO_TIMEOUT_MS`, `DISCORD_WEBHOOK_URL`,
`MOCK_PORTAL_URL`, `SCAN_LIVE`, `SCAN_DELAY_S`, `STEALTH_ENABLED`,
`STEALTH_USER_AGENTS`, `STEALTH_LOCALE`, `STEALTH_TIMEZONE`,
`NOPECHA_API_KEY`, `NOPECHA_ENABLED`). A variable set in the environment
wins over the dashboard value, and the dashboard says so. `DATABASE_PATH`
is intentionally NOT editable in the UI. See `.env.example`.

Logs: `logs/app.log` (plus console). The webhook URL and session
contents are never written to logs.
