# LIVE VERIFICATION — v1.5.0

**Date:** 2026-10-28 (checks run 02:40 UTC / 08:40 +06 and 10:45–10:56 UTC / 16:45–16:56 +06)

This file is the honest record of what was actually checked against the
REAL Viagogo site, what worked, and what could NOT be proven. No raw
page dumps are shipped in this repo — the evidence below is numbers and
short verbatim strings only.

## 1. Real Viagogo pages checked (public pages, no login)

| Page | URL | What the page really showed |
|---|---|---|
| Metallica (artist page, 47 events in USA) | https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets | "Metallica - 2 Day Pass (October 29 & 31)", 7:55 PM, Sphere at The Venetian Resort, 255 Sands Ave, Las Vegas, Nevada 89169 |
| Real Madrid CF (artist page, 39 events) | https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-151961718 | "3,895 people viewed Real Madrid CF events in the past hour"; "Only 1% of tickets left" (Roma vs Real Madrid Oct 14, FC Barcelona vs Real Madrid Oct 25); "Selling fast" (Real Madrid vs Sevilla Oct 18, Real Madrid vs RB Leipzig Oct 21); "Top seller" (Real Madrid vs Villarreal Oct 10) |
| FC Barcelona (artist page) | https://www.viagogo.co.uk/Sports-Tickets/Football/International-Football/Spanish-Premier-League/FC-Barcelona-Tickets | "FC Barcelona vs Real Madrid CF, 2026-10-25 21:00, Camp Nou — Tickets: 1,265.69 USD"; "FC Barcelona vs Deportivo Alavés, Oct 31 — 172.51 USD"; "FC Barcelona vs Aston Villa, Nov 3 — 277.80 USD"; "FC Barcelona vs Manchester City, Dec 8 — 638.50 USD" |
| Metallica prices (independent, NY Post 2026-10-23) | — | Oct 29 single from $813 incl. fees; 2-Day Pass Oct 29 & 31 $1,262 incl. fees; Oct 31 from $850 |

**Real numbers returned by the scanner's parser against these pages**
(from the real-page fixture `tests/fixtures/real_page_text.txt`, run through
the real Playwright browser code against a local copy of that text):
- lowest price **$813 USD** (headline "Tickets from $813")
- **3,895** people viewed (Real Madrid CF events in the past hour)
- **20 tickets left**
- demand signals: `only_1pct_left`, `selling_fast`, `top_seller`

Caveat: the browser crawl returns page text only — JavaScript-rendered
per-event ticket prices are NOT in crawled text. That is exactly why the
scanner must use a real browser (Playwright) on the live site. No
single-event E- URLs were exposed by the crawls, so the seed watchlist
uses the real artist pages (documented in `watchlist.example.json`);
single-event URLs give the cleanest prices.

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
  local HTTP (`/tmp/smoke150.py`, 16/16 checks). Result: lowest $813 USD,
  3,895 people, 20 tickets left, all three demand signals.
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
Windows PC), or via the parent agent's live-browser task:

    python scripts/verify_live.py

It runs the real `MarketMonitor` against the 3 real URLs above, then
opens sell.viagogo.com and confirms it reaches the login gate (STOP —
no login, no listing). Exit 0 = at least one market page returned real
prices AND the sell gate was reached. Anything else prints exactly
what failed. Until that run passes, the claim "live Playwright scan
verified against viagogo.com" is NOT made — only "verified against
real Viagogo page content on a local copy, and the live network path
is blocked on this VM".

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
