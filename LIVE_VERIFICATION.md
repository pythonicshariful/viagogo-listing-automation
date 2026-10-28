# LIVE VERIFICATION — v1.5.1

**Date:** 2026-10-28 (checks run 02:40 UTC / 08:40 +06 and 10:45–10:56 UTC / 16:45–16:56 +06; Shariful's real-PC run ~17:36 +06; v1.5.1 fix same day)

This file is the honest record of what was actually checked against the
REAL Viagogo site, what worked, and what could NOT be proven. No raw
page dumps are shipped in this repo — the evidence below is numbers and
short verbatim strings only.

## 1. Real Viagogo pages checked (public pages, no login)

| Page | URL | What the page really showed |
|---|---|---|
| Metallica (artist page) | https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets | "Metallica - 2 Day Pass (October 29 & 31)", 7:55 PM, Sphere at The Venetian Resort, 255 Sands Ave, Las Vegas, Nevada 89169 |
| Real Madrid CF (artist page, 39 events) | https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-151961718 | "3,895 people viewed Real Madrid CF events in the past hour"; "Only 1% of tickets left" (Roma vs Real Madrid Oct 14, FC Barcelona vs Real Madrid Oct 25); "Selling fast" (Real Madrid vs Sevilla Oct 18, Real Madrid vs RB Leipzig Oct 21); "Top seller" (Real Madrid vs Villarreal Oct 10) |
| FC Barcelona (artist page) | https://www.viagogo.co.uk/Sports-Tickets/Football/International-Football/Spanish-Premier-League/FC-Barcelona-Tickets | Event names, dates and venues ONLY — **no prices at all** on the artist page. The per-event prices live in structured per-event data / single-event pages: "FC Barcelona vs Real Madrid CF, 2026-10-25 21:00 — Tickets: 1,265.69 USD"; "FC Barcelona vs Deportivo Alavés, Oct 31 — 172.51 USD"; "FC Barcelona vs Aston Villa, Nov 3 — 277.80 USD"; "FC Barcelona vs Manchester City, Dec 8 — 638.50 USD" (viagogo.com.tr structured data, same day). **Corrected in v1.5.1:** the v1.5.0 table listed those "Tickets:" lines as if they were on the artist page — they are not. |
| Metallica prices (independent, NY Post 2026-10-23) | — | Oct 29 single from $813 incl. fees; 2-Day Pass Oct 29 & 31 $1,262 incl. fees; Oct 31 from $850 |

**Real numbers returned by the scanner's parser against these pages**
(from the real-page fixture `tests/fixtures/real_page_text.txt`, run through
the real Playwright browser code against a local copy of that text):
- lowest price **$172.51 USD** — the cheapest real price in the mashed
  fixture text (Alavés, "Tickets: 172.51 USD"); the headline
  "Tickets from $813" is recorded separately as `from_price`
  (v1.5.0's parser returned $813 because it could not read the
  "Tickets: N USD" format at all — see §8, root cause 1)
- **3,895** people viewed (Real Madrid CF events in the past hour)
- **20 tickets left**
- demand signals: `only_1pct_left`, `selling_fast`, `top_seller`
- page kind: **artist** ("39 events in all locations") — the fixture
  mashes three artist pages together, so its prices are per-event
  prices across all of them, not one event's prices

Caveat: the browser crawl returns page text only — JavaScript-rendered
per-event ticket prices are NOT in crawled text. That is exactly why the
scanner must use a real browser (Playwright) on the live site. No
single-event E- URLs were exposed by the crawls, so the seed watchlist
uses the real artist pages (documented in `watchlist.example.json`) —
**replace each artist-page URL with the single event page URL** (open
the artist page, click one event, paste that URL) before relying on
live prices; the dashboard warns you when you paste an artist page
(v1.5.1). Single-event URLs give the cleanest prices.

## 2. What the parser was changed to handle (v1.5.0, market.py)

Real Viagogo pages do not look like the old mock text. Added:
- `parse_from_price`: "Tickets from $813" → (813.0, "USD"); "From £120" → GBP.
- `parse_currency`: first $/£/€ on the page → USD/GBP/EUR (the page's
  currency now wins over the watchlist entry's currency).
- `parse_scarcity`: "Only 1% of tickets left" → `only_1pct_left`;
  "Selling fast" → `selling_fast`; "Top seller" → `top_seller`.
- `parse_people_searching` extended: "3,895 people viewed … in the past
  hour" → 3895.
- `parse_snapshot_text`: headline "From $X" is the lowest price when
  present, else the minimum price; snapshot now also carries `from_price`
  and `demand_signals`.
- `MarketMonitor.scan_with_report()` returns (snapshots, live_errors).
  A failed live check NEVER falls back to sample data — the snapshot keeps
  source "live-challenge" / "live-failed" with prices None, and the caller
  must surface the error.

## 3. The Cloudflare / DataDome encounter

Plain HTTP cannot read Viagogo at all — this validates the design
(real browser required):
- `curl https://www.viagogo.com/` with a real Chrome User-Agent →
  **HTTP 403, 772 bytes**, a DataDome challenge page ("Please enable JS
  and disable any ad blocker", `geo.captcha-delivery.com`).

## 4. Why a live Playwright run could NOT be done on the dev VM

This is a limitation of THIS dev VM, not of the product. Proven, not assumed:
- Playwright Chromium 1.48.0 (chromium-1140), direct `page.goto` to
  viagogo.com and to example.com: `net::ERR_TUNNEL_CONNECTION_FAILED`.
- The VM reaches the internet only through the egress proxy
  `hatch-egress-proxy:3128` (env `https_proxy`/`HTTP_PROXY`).
  Chromium with the proxy (Playwright `proxy` option with/without auth,
  `--proxy-server`, IPv4 `198.19.0.1:3128`, IPv6, minimal flags) fails
  the same way.
- Net-log proof (`/tmp/netlog.json`): Chromium's CONNECT got
  `HTTP/1.1 403 Forbidden`, body (base64-decoded)
  `{"detail":"The proxy did not authorize this connection.","error":"policy_denied"}`.
  A byte-identical raw-socket CONNECT (same Host / Proxy-Connection /
  HeadlessChrome User-Agent) got `200 Connection Established` — so the
  block is not the request bytes; it is the VM egress policy for
  Chromium processes.
- Direct (no proxy) Chromium: `ERR_SSL_PROTOCOL_ERROR` (TLS-intercepting
  gateway). Direct curl: 000 (blocked).
- Firefox download via Playwright also failed — same egress policy.

**Run of `scripts/verify_live.py` on this VM (2026-10-28 ~16:50 +06):**
- Metallica artist page → `live-failed`, no prices.
- Real Madrid CF artist page → `live-failed`, no prices.
- FC Barcelona artist page → `live-failed`, no prices.
- sell.viagogo.com → `Error: Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED`.
- Result: "LIVE VERIFICATION FAILED" — reported as-is, nothing faked.

## 5. What WAS proven, and how

- The full browser code path on REAL page content: the real
  `MarketMonitor` Playwright code (stealth context, challenge check,
  `inner_text`, parse) was run against a local page built from the real
  Viagogo text — file:// (pytest, `tests/test_autocollect.py`) and over
  local HTTP (`/tmp/smoke150.py`, 16/16 checks). Result: lowest $172.51
  USD (cheapest real price in the mashed fixture; headline from_price
  $813), 3,895 people, 20 tickets left, all three demand signals.
  The only unproven link is this VM's network path to viagogo.com.
- Honest-live rules proven by tests + smoke: an explicit live request
  with Live scans OFF → **400** ("Live scans are OFF… Nothing was
  scanned, and no sample data was substituted."); a live scan where every
  check fails → **502** with `live_errors`, no sample substitution;
  sample scans are always labelled `data_source: "sample"` with a
  `SAMPLE DATA` warning (dashboard badge, `/api/opportunities`,
  `/api/scan`).
- Auto-collector proven by tests + smoke: runs in a background thread,
  every 6h by default, stores ONLY live snapshots as training data,
  a failed run is logged and the schedule keeps going, "Collect now"
  works, export CSV/JSON works.

## 6. The exact remaining step

Run on a normal machine with normal internet (Fayed's / Shariful's
Windows PC) — from the dashboard, no terminal needed:

1. Start the app (`run.bat`) and open `http://127.0.0.1:5002/opportunities`.
2. Watchlist (section 1): make sure the first 3 entries are
   **single-event page URLs** (open the artist page in your browser,
   click one event, paste THAT page's URL). The dashboard warns you
   if you paste an artist page.
3. Section 4 "Live check": tick **Show browser** if you want to watch
   the browser open on your screen, then click **Run live check**.
   It takes about 2–3 minutes. The page shows live progress and, for
   each event, source / lowest price / listings / people / signals /
   FAILED + reason, plus the page title, final URL, text length, the
   first 500 chars of page text, any challenge, and the screenshot path.
4. Evidence is written to `logs/live-check-<run>.txt` (same details
   as on screen) and screenshots to `logs/live-check-<run>-<n>.png`.

Or from the terminal on the same machine:

    python scripts/verify_live.py --headed

`--headed` shows the browser on screen; without it the browser runs
hidden. The script prints the same diagnostics to the console and
writes the same evidence file. Exit 0 = at least one market check
returned real prices AND the sell gate was reached. Until a run passes,
the claim "live Playwright scan verified against viagogo.com" is NOT
made — only "verified against real Viagogo page content on a local
copy, and the live network path is blocked on this VM".

## 7. What is NOT proven live (plain statement)

- No live Playwright page-load of viagogo.com from this VM (egress
  proxy block, §4). The live run is pending on a real machine.
- No live Create Listing click (still needs a card on file + face value
  + payout; the bot refuses without them). Never clicked, no listing created.
- No live sale detection (proven only against the mock sales page).
- No live NopeCHA solve (no key configured; no real call made).
- The scanner is heuristic — NO ML model yet. ML is Phase 2; the
  auto-collector now builds the training data automatically (see
  README § "Training data & ML (Phase 2)").
- The v1.5.1 live check itself is still unproven on a real PC — see §8.

## 8. The 2026-10-28 all-None run — root cause (v1.5.1)

Shariful ran `python scripts/verify_live.py` on his real Windows PC
(~17:36 +06) and ALL THREE checks failed with empty results. His
exact output:

- Metallica artist page: `source=live, lowest USD None, avg None,
  listings None, people None, signals []` — FAILED
- Real Madrid CF artist page: `source=live, lowest EUR None,
  everything None` — FAILED
- FC Barcelona artist page: same, all None — FAILED
- `Sell portal login gate:` — output cut off after this line
- He also said: "i am not seeing any browser" and "i want run it from
  dashboard".

### What his logs/app.log showed (and did not show)

The pasted log is the **Flask app log only** (v1.4.0 → v1.4.1 → v1.5.0
starts, page loads, settings calls). It contains **zero entries from
verify_live.py** — that script logged to the console/stdout only, not
to `logs/app.log`, so the reason was never findable in app.log.
Two facts from the log matter:

- At **17:32:12** a `POST /api/settings` returned **400** (validation
  rejected), then at **17:32:14** the same save succeeded with **200**
  (settings updated: fee_pct, headless, host, log_level, mode,
  page_timeout_ms, port, scan_delay_s, scan_live, stealth_enabled,
  stealth_locale, stealth_timezone; restart needed True). He changed
  settings — including `scan_live` and `headless` — around the time of
  the live check. The dashboard UI **does** show settings errors
  (`'Error: ' + JSON.stringify(...)` in `templates/index.html`), so
  the 400 was not a silent failure; it was most likely the
  live-confirmation guard or a validation error he corrected 2 seconds
  later. Not a bug — noted here so nobody chases it again.
- **v1.5.0 is confirmed running on his PC** (auto-collector started,
  interval 6.0h, run_on_start=False). The verify run happened against
  this setup.

### Root cause 1 — the parser was blind to "Tickets: N USD"

The v1.5.0 parser only matched a currency symbol BEFORE the number
(`$860`). The per-event prices Viagogo actually shows in structured
data are written the other way round: `Tickets: 1,265.69 USD`,
`Tickets: 172.51 USD`. **Proven by experiment:** the FC Barcelona
artist-page text alone, run through the v1.5.0 parser, returns
`parse_prices` = `[]` — and the v1.5.0 "proof" was misleading because
its fixture mashed all three pages together and the $813 came from
the Metallica "Tickets from $813" line. The parser never saw the
Barcelona prices at all.

**Fix (v1.5.1):** `parse_suffix_prices` / `parse_tickets_price` read
the amount+code format, wired into `parse_prices` and
`parse_snapshot_text`. A bare year ("2026 USD") is rejected — the
number must have a decimal part, a thousands comma, or be introduced
by "Tickets:". The Barcelona excerpt alone now returns lowest
**$172.51 USD**.

### Root cause 2 — artist pages are the wrong target (2 of 3 checks)

The real pages fetched 2026-10-28 contain:

| Page | Prices on the page? |
|---|---|
| Real Madrid artist page | **NONE** — only "3,895 people viewed … in the past hour", "Top seller", "Only 1% of tickets left", "Selling fast" |
| FC Barcelona artist page | **NONE** — only event names, dates and venues |
| Metallica artist page | YES — per-event "From $463 / $599 / $895" |

The real per-event prices ("Tickets: 1,351.24 USD" etc.) live in
structured per-event data / single-event pages. The Metallica artist
page DOES have prices and the parser reads them fine (lowest $463,
not $895 — the first "From" is only the first event's price, not the
cheapest). So two of the three checks could never return prices, no
matter how good the browser was.

**Fix (v1.5.1):** the check now uses **single-event pages** — the
dashboard live check runs the watchlist's first 3 entries and the
watchlist warns (plain English) when you paste an artist-page URL;
`verify_live.py` clicks through from the artist page to a single
event (`collect_event_via_artist`); the parser reports
`page_kind: "artist"` + `events_count` + a `page_note` explaining the
page is an artist page whenever it sees one. Fixture:
`tests/fixtures/real_artist_pages_20261028.txt` (verbatim excerpts
from the 2026-10-28 fetches).

### Root cause 3 — Playwright saw different content than the crawl

Shariful's run returned `people None / signals []` even for Real
Madrid, where the parser WOULD find people=3895 + signals from the
crawled text — so his browser never got the rendered event list
(React XHR not finished in the 2–4s sleep, or a DataDome / consent /
geo page, or lazy loading). Two gaps made this silent:

- The challenge detector missed DataDome wording (its page says
  "Please enable JS and disable any ad blocker",
  `geo.captcha-delivery.com`).
- The check ran BEFORE the wait, so a late-appearing challenge was
  missed — the page was then silently parsed as "live" with all None.

**Fix (v1.5.1):** `_read_page` waits for real content (event rows or
prices, up to the page timeout), scrolls, then checks for a challenge
**after** the wait; `detect_challenge_text` knows DataDome markers
("datadome", "captcha-delivery", "please enable js",
"disable any ad blocker", "verify your browser", titles "datadome" /
"access denied"); an empty page is reported as source `"live-empty"`,
never silently "live" all-None.

### Root cause 4 — the sell-gate step hung / cut off the output

`check_sell_gate` launched a second browser; the whole script took
minutes with no progress output, so a copied paste looks like a hang.
Also `headless=True` was hardcoded/default — hence "not seeing any
browser".

**Fix (v1.5.1):** the sell gate has timeouts (goto 30s, read 15s)
and prints progress BEFORE each slow step; `--headed` shows the
browser on screen; the dashboard live check has a "Show browser"
checkbox. Every run writes an evidence file
(`logs/live-check-<run>.txt` + screenshots) — the script never exits
silently with all-None; every failure says WHY in plain words.

### What v1.5.1 changed, in one list

- `market.py`: suffix-code prices, `detect_page_kind` /
  `is_empty_page` / `looks_like_artist_page_url`, `_read_page`
  (wait-for-content + scroll + post-wait challenge check +
  diagnostics), `collect_with_diagnostics` (source `"live-empty"`),
  `collect_event_via_artist` (click-through), `scan_with_report`
  reports `"live-empty"` as a live error with a plain reason.
- `stealth.py`: DataDome challenge markers.
- `livecheck.py` (new): shared runner for the dashboard + the script
  — `run_live_check`, `check_sell_gate` (timeouts + progress),
  `format_diag` / `format_result`, `write_evidence`,
  `LiveCheckStore`.
- `app.py`: `POST /api/live-check` (background run, 409 if one is
  running, 400 if the watchlist is empty), `GET /api/live-check/<id>`,
  `GET /api/live-check`; watchlist POST warns on artist-page URLs.
- `templates/opportunities.html`: section 4 "Live check" — Run live
  check button + "Show browser" checkbox + progress/results +
  evidence note; `addWatch()` shows the artist-page warning.
- `scripts/verify_live.py`: `--headed` flag, diagnostics on console
  with flush, evidence file + screenshots, progress lines before
  slow steps; checks = Metallica artist (control) + click-through to
  the Metallica Oct 29 single event + click-through to a Real Madrid
  single event + sell gate.
- Tests: `tests/test_livecheck.py` (26 cases) + fixture
  `tests/fixtures/real_artist_pages_20261028.txt`; full suite 163
  passed; e2e scripts + mock portal + fresh Flask smoke test
  (temp port + temp DB, no .env) all pass.

### Still unproven after v1.5.1

The v1.5.1 live check has **not yet been run against the real site
on a real PC** — this dev VM's Chromium still cannot reach Viagogo
(egress proxy 403, §4). The re-run on Shariful's PC (dashboard
section 4, or `python scripts/verify_live.py --headed`) is the exact
remaining step (§6).
