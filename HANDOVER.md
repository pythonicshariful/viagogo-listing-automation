# Handover — Viagogo Listing Automation v1.5.0

**For Fayed. One page, simple English. If you can use a web browser,
you can use this program.**

---

## What you get

A program that lists tickets for sale on Viagogo, and finds the most
profitable events to list. It never buys tickets — when a ticket sells,
**you** buy the ticket and send it to the buyer.

- **Bulk listings:** create 1–50 listings for one event at once.
  Prices are set from the face value (+80% by default, never below
  £50 / $50, never above 1500).
- **Payout per listing (new in v1.4.0):** every listing has its own
  payout method — PayPal (with your PayPal email) or Direct deposit.
  You set it once in the bulk form and it applies to the whole batch.
  Your email is shown only partly hidden (first 4 letters + `***`)
  and is never written to the logs.
- **Training data, collected automatically (new in v1.5.0):** the program
  now collects real market prices by itself, every 6 hours, while it is
  running — no clicking needed. On the Opportunities page, section
  "Training data" shows how many real snapshots exist and when the next
  collection is. You can download the data as a CSV file. This data is
  what the future ML step (Phase 2) will learn from — it needs weeks of
  daily snapshots first, and this is what builds them.
- **Live or sample — always labelled (new in v1.5.0):** every scan shows
  a green LIVE DATA badge (real numbers from Viagogo) or an amber
  SAMPLE DATA badge (built-in examples). Sample numbers are never shown
  as real. If you ask for a live scan and it fails, you get a clear
  error — never fake numbers.
- **Sale detection (new in v1.4.0):** the program checks your seller
  dashboard for sold listings and sends you a Discord alert when one
  sells, so you know to buy and deliver the ticket. In safe mode it
  says "not available" and never pretends a sale happened.
- **Opportunity Scanner:** watches events and ranks them by estimated
  profit × confidence, so you list the best ones first. (Heuristic
  scoring only — no ML yet. ML is a later, separate step.)
- **Safe mode first:** the program starts in dry-run. In dry-run
  nothing is posted to Viagogo. You can try everything with no risk.

---

## How to start — 3 steps

1. **Install Python** (free, from python.org, version 3.11 or newer).
   Tick **"Add python.exe to PATH"** during install. Check it with
   `python --version` in the black Command Prompt window.
2. **Get the program** — download the ZIP from GitHub
   (or use the ZIP Shariful sent you), right-click → **Extract All**.
3. **Start it** — double-click `run.bat` (Windows) or run `./run.sh`
   (Mac/Linux). Wait for the first setup to finish, then open
   **http://127.0.0.1:5002** in your browser.

The full guide with pictures in words is in **README.md** (Steps 1–3
+ a 5-minute tour). Follow it in order.

---

## What YOU still have to provide before live use

The program cannot do these for you. Nothing goes live until all of
them are done (the checklist is also in README.md, "Going live").

1. **Your Viagogo login (session).** Log in to your Viagogo seller
   account once in a browser, save the login session file
   (`auth_state.json`), and upload it in the dashboard:
   Settings → Seller session. Never put your username or password in
   any file.
2. **A card on file — added by hand in Viagogo.** Add a valid credit
   or debit card to your seller account yourself, on the Viagogo
   website. The program never types card details and will refuse to
   post until a card is on file.
3. **Payout method.** PayPal email or Direct deposit, set in the
   dashboard when you create listings (bulk form, section 2).
4. **Your 10–20 event list, with face values.** Real Viagogo event
   links + the face value (ticket price) for each. The program ships
   with 5 example events only — Metallica is real, the rest are
   placeholders. Do not act on the sample numbers.
5. **Confirmed seller fee %.** The program uses 10% as an estimate.
   Tell Shariful the real Viagogo seller fee % so the profit numbers
   are right (Settings → Seller fee %).
6. **Discord webhook (for sale alerts).** From Discord: Server
   Settings → Integrations → Webhooks → New Webhook → Copy Webhook
   URL. Paste it in the dashboard (section 3. Discord) and click
   "Send test message". The program works without it, but then you
   get no sale alerts.
7. **Optional: NopeCHA key.** Only if you want the program to try to
   solve CAPTCHA puzzles. Get a key at nopecha.com, paste it in the
   dashboard (section 4). Off by default, and the program works
   without it. Solving a CAPTCHA may break Viagogo's rules and can
   get the account flagged — your choice.
8. **Written risk acceptance.** See the warning below. Confirm in
   writing that you accept the risk before anything goes live.

---

## What is proven — and what is NOT

**Proven (tested on this machine, 2026-10-28):**

- 120 automated tests pass, plus the dry-run and scanner end-to-end
  checks, plus the mock-portal browser test (all 6 Sell steps,
  `MOCK-0001`, nothing posted).
- Sale detection works against the **mock** sales page: it finds the
  one sold listing (via exact-text match, $992.99) and finds zero
  sales on the no-sales page — it never fakes a sale.
- The 6-step Sell pipeline was verified against the **real portal**
  on 2026-10-28, logged in, up to the PriceDetails page (Metallica
  sample). **No listing was ever created.**

**NOT proven — needs your real account to confirm:**

- **The final "Create Listing" click, live.** It was never clicked on
  the real portal. Create ONE listing by hand first, then ONE with the
  program, and check it appears in your seller dashboard.
- **Live sale detection against the real sales page.** The real
  sales-page layout has not been seen yet. After your first real sale,
  check by hand that the program marks it sold too. If it misses it,
  send Shariful a screenshot of the sales page so the matching can be
  fixed.
- **Speculative-listing risk.** Viagogo forbids listings for tickets
  you do not own yet. It can remove listings, fine you, or **close
  your seller account for good**. This program gives **no guarantee of
  account safety**. Only list tickets you can actually buy and deliver.
- **Cloudflare / bot blocking.** Viagogo can block automated access at
  any time. The program stops (never bypasses) when a challenge page
  appears. Stealth only reduces detection risk — it does not make the
  program invisible.

---

## If something goes wrong

Read **README.md → "If something goes wrong"** (table of problems +
fixes). If you are stuck, send Shariful: (1) what you were trying to
do and what happened, in your own words; (2) the last 20 lines of
`logs/app.log`. **Never send** your Viagogo password, your NopeCHA
key, your Discord webhook address, or the session file
(`auth_state.json`).
