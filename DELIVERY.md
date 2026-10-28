# Delivery — Viagogo Listing Automation v1.3.1

**Listing-only. The bot never buys tickets.** After a sale, the client buys
the ticket manually and delivers it.

> **Honest status — read this first.** This is a **production-ready
> package**: hardened app, logging, validation, packaging, tests green.
> The 6-step Sell pipeline is now **verified to PriceDetails** against
> the real portal (observed live 2026-10-28, logged in, Metallica sample,
> no listing created). **Still unverified: the "Create Listing" click itself.**
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
> snapshots first.

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
| `db.py` | SQLite storage (`data/listings.db`) |
| `templates/index.html` | Single-page UI: price rules, bulk form, listings table |
| `mock/mock_seller_portal.html` | Fake 6-step seller flow — proves the browser flow with no Viagogo |
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
3. **Price rules matter:** the USD Metallica sample is ~$860, above the
   GBP default max of 500 — set Max price to 1500 (or per-currency rules)
   or the recommendation clamps and profit goes negative. In the UI,
   set price rules first (or `POST /api/config`).
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
3. Set price rules (default: +80% markup, min £50, max £500, round to .99).
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
- [ ] **8. Sale detection.** Until the live sales-page selectors are
  verified, `/api/sales/check` returns no sales (stub). After step 4,
  implement it against the live sales section — or watch the seller
  dashboard / email and use the Discord alert from the simulate path as
  the proven channel.

To go back to safe mode at any time: switch Mode back to Dry-run in
Settings — nothing can be posted live in dry-run.

## Verification (done 2026-10-28, this machine)

| Check | Result |
|---|---|
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

`viagogo-listing-automation-delivery.zip` — v1.3.1, rebuilt 2026-10-28
(113,907 bytes, 37 files), source + docs + scripts only. Excluded: `venv/`, `data/*.db`, `__pycache__`,
`.pytest_cache/`, `.env`, `auth_state.json`, `logs/`. Verified: extracted
to a clean dir, fresh venv, `pytest` 102 passed + scanner end-to-end
script passed there, and the new README steps 3–6 were followed
exactly from the zip (run.sh start, DRY-RUN badge, bulk 3 drafts @
179.99, dry-run post DRY-0001, simulate sale, seed + mock scan with Max
price 1500 → Metallica top $992.99 / profit $387.38 / conf 100). See the
v1.3.1 verification row below. Verify after unzipping with the two commands in
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
