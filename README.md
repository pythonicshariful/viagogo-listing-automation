# Viagogo Listing Automation — v1.5.0

**A program that lists tickets for sale on Viagogo, and finds the most
profitable ones to list. You do NOT need to know how to code. You do NOT
need to edit any files. If you can use a web browser, you can use this.**

This guide starts from zero. It shows you how to install Python, start
the program, and try it safely — before anything real happens.

---

## What this does

This program helps you sell tickets on Viagogo. It creates many listings
at once, sets their prices, and keeps them up to date. It also watches
the market and tells you which events are likely to make the most money.

Three things are important to know:

1. **The program never buys tickets.** When a ticket sells, you buy the
   ticket yourself and send it to the buyer.
2. **It starts in safe mode (dry-run).** In safe mode it only pretends
   to post listings. Nothing goes to Viagogo. You can try everything
   without any risk.
3. **It never asks for your card details.** It never types your card
   number anywhere. You add your card to Viagogo yourself, by hand.

> ## ⚠️ Warning — read this first
>
> Viagogo does **not** allow "speculative listings". That means listings
> for tickets you do not own yet. If Viagogo finds such listings, it can
> remove them, fine you, or **close your seller account for good**.
> This program cannot protect your account from that. Only list tickets
> you can actually buy and deliver. Before you switch the program to
> live mode, you must accept this risk in writing (see "Going live").

---

## What you need

- **A Windows computer** (Windows 10 or 11). It also works on Mac and
  Linux — the steps for those are in Step 3.
- **Internet.**
- **A Viagogo seller account** — only needed later, when you go live.
  You do not need it to try the program.
- **A Discord webhook address** (a special link from Discord) — optional,
  only for sale alerts. You can add it later. The program works without it.

---

## Step 1 — Install Python

Python is the language this program is written in. Your computer needs
it installed before the program can run. It is free.

1. Open your web browser and go to **https://www.python.org/downloads/**
2. The site shows a big yellow button like **"Download Python 3.13"**.
   Click it. (Any version **3.11 or newer** works. The button always
   gives you the newest version, which is fine.)
3. Run the file you downloaded. A setup window opens.
4. **Very important:** on the first screen, at the bottom, tick the box
   that says **"Add python.exe to PATH"**. This box is easy to miss.
   It tells Windows where Python lives. If you forget it, the program
   will not start later, and you will see an error saying Python was
   not found. If that happens, just run the installer again and tick
   the box.
5. Click **"Install Now"** and wait until it finishes. Then click
   **"Close"**.

**Check that it worked:**

1. Press the **Windows key** on your keyboard, type `cmd`, and press
   Enter. A black window opens. This is called the Command Prompt.
2. Type this and press Enter:

   ```
   python --version
   ```

3. You should see something like `Python 3.13.1`. The exact numbers do
   not matter, as long as the first number after "Python" is **3.11 or
   higher**. If you see an error instead, Python was not added to PATH —
   run the installer again and tick the box in step 4.

> **On a Mac:** open the Terminal app and type `python3 --version`
> instead of `python --version`. The program's Mac starter uses
> `python3`.

---

## Step 2 — Get the program

There are two ways. Use the first one if you are not sure.

### Way A — Download the ZIP file (easiest)

1. Go to **https://github.com/pythonicshariful/viagogo-listing-automation**
2. Click the green **"Code"** button, then click **"Download ZIP"**.
3. A file called `viagogo-listing-automation-main.zip` downloads.
4. Find it in your Downloads folder. Right-click it and choose
   **"Extract All..."**, then click **"Extract"**.
5. You get a folder called `viagogo-listing-automation-main`. Open it.
   Inside you will see files like `run.bat`, `README.md`, and `app.py`.

(If Shariful sent you a ZIP file directly, just extract that file
instead — it contains the same folder.)

### Way B — With git (only if you already have git)

If you know what git is, you can use this command instead:

```
git clone https://github.com/pythonicshariful/viagogo-listing-automation.git
```

Then open the `viagogo-listing-automation` folder. If you do not know
what git is, ignore this and use Way A.

---

## Step 3 — Start it

### On Windows

1. Open the program folder from Step 2.
2. **Double-click `run.bat`.**
3. A black window opens. The first time, it prepares everything: it
   creates a private copy of Python for this program (called a
   "virtual environment", a folder named `venv`) and downloads the
   parts the program needs (Flask, Playwright, and a few others).
   **This takes a few minutes and needs internet.** Just wait.
4. When it is ready, the black window shows a message like:

   ```
   Starting Viagogo Listing Automation (dry-run is the safe default)...
   ```

   **Leave this black window open.** It is the program running. If you
   close it, the program stops.
5. Open your web browser (Chrome, Edge, or Firefox) and go to:

   **http://127.0.0.1:5002**

   The dashboard opens. That address is your own computer — the number
   `127.0.0.1` always means "this computer", and `5002` is the door
   (called a "port") the program listens on. Nothing leaves your
   computer unless you switch to live mode.

### On Mac or Linux

1. Open the Terminal app.
2. Go into the program folder. For example, if it is in Downloads:

   ```
   cd ~/Downloads/viagogo-listing-automation-main
   ```

3. Run:

   ```
   ./run.sh
   ```

   If you see "permission denied", run `chmod +x run.sh` first, then
   try `./run.sh` again.
4. Wait for the first-time setup to finish, then open
   **http://127.0.0.1:5002** in your browser — same as on Windows.

### Do you need a web browser inside the program?

Only for live mode (posting real listings) or for the mock-portal test.
If you only want to try the dry-run demo, you do not need it. To
install it later, close the program and run:

- Windows: `run.bat install-browser`
- Mac/Linux: `./run.sh --install-browser`

### How to stop the program

Click inside the black window and press **Ctrl + C**, or just close the
black window. To start it again later, double-click `run.bat` again
(or `./run.sh`). Starting again is fast — the setup only happens the
first time.

---

## Your first 5 minutes — a guided tour

Do this in order. Everything here is safe: the program is in dry-run,
so nothing is posted to Viagogo.

### 1. Check the badge at the top

At the top of the dashboard you will see a yellow badge that says:

> **DRY-RUN — nothing is posted to Viagogo**

That means safe mode is on. As long as you see this badge, nothing you
do can create a real listing. If you ever see a red **LIVE MODE** badge
instead, stop and read the "Settings" section below before you click
anything.

Below the badge is the warning about speculative listings. Read it once.

### 2. Set the price rules (section 1. Price rules)

A "price rule" tells the program how to price a listing from the
ticket's face value (the price printed on the ticket).

- **Markup % over face value: 80** — the listing price is the face
  value plus 80%. Example: a ticket that costs £100 is listed at £180.
- **Min price: 50** — a listing is never cheaper than this.
- **Max price: 1500** — a listing is never more expensive than this.
  (It used to be 500, but US events like Metallica at about $860 need
  a higher cap — v1.4.0 raised the default to 1500.)
- **Currency: GBP** — the money the price is in (GBP = British pounds).

The final price is always rounded down to end in .99, so £180 becomes
£179.99. Click **"Save price rules"** when you change anything.

> **Tip:** if a ticket costs more than the Max price (for example a
> US event above $1500), the Max price will cut the recommended price
> down and the profit will look negative. That is the Max price doing
> its job, not a bug — raise it if the real ticket really costs that
> much.

### 3. Try the dry-run demo (section 2. Bulk create listings)

"Bulk" just means "many at once". A "draft" is a listing that is saved
in the program but not posted anywhere yet.

1. Leave the example values as they are: Event category **football**,
   Event name empty or any name you like, Section **General Admission**,
   Face price **100**, Listings per event **3**, Quantity per listing **2**.
   (Section means the area of the stadium, not an exact seat. Quantity
   means how many tickets are in each listing.) Set **Payout method**
   to PayPal and type your **PayPal email** — that is where Viagogo
   sends the money when a ticket sells. (If you choose Direct deposit
   instead, no email is needed.)
2. Click **"Create drafts"**. You should see "Created 3 drafts @ 179.99".
   The price is £100 + 80% = £180, rounded to £179.99.
3. Scroll down to **section 6. Listings**. Your 3 drafts are in the table.
4. Click **"Post"** on one of them. It shows a fake ID like `DRY-0001`.
   **Nothing was posted to Viagogo.** In dry-run, "Post" only pretends.
5. Click **"Simulate sale"** on the same listing. This pretends a buyer
   bought it, so you can see what a sale looks like. If you set up
   Discord (section 3), a test message is prepared — but nothing is
   sent unless you added a real webhook address.
6. Try **"Pause"**, **"Resume"**, and **"Reprice"** on the other drafts.
   These are the buttons you will use to manage real listings later.

### 4. Open the Opportunities page

At the top of the dashboard, click the link to
**http://127.0.0.1:5002/opportunities**. This is the Opportunity
Scanner. It looks at events and ranks them by how much money they
might make.

1. Click **"Load example watchlist"**. This adds 5 example events to
   your watchlist (a watchlist is just a list of events you want to
   watch). Metallica is a real example from a live check; the other 4
   are placeholders for your real events.
2. Check the Max price in section 1. Price rules — it should already
   be **1500** (the default since v1.4.0). That matters because the
   Metallica tickets cost about $860: with the old default of 500 the
   program would have cut Metallica's recommended price down to 499.99
   and its profit would look like minus $500. If you ever lower the
   Max price below a ticket's real cost, that is what happens — it is
   the Max price doing its job, not a bug.
3. Click **"Run scan (mock/sample unless Live scans are on in Settings)"**.
   "Mock" means it uses built-in sample numbers, not the real internet.
   It is safe and instant. Every scan is labelled: a green **LIVE DATA**
   badge means real numbers from Viagogo, an amber **SAMPLE DATA** badge
   means built-in examples. Sample numbers are never shown as real.
4. The top result should be Metallica: market price $860, recommended
   price $992.99, estimated profit **$387.38 (27.7%)**, confidence
   100/100, timing "list now". The Coldplay example also gets a score.
   The last two events (Champions League final and Taylor Swift) are
   placeholders with no sample data, so they show confidence 10 and no
   price — that is correct, because there is no sample data for them.
   It is not a bug.
5. Click **"Send top opportunity to Discord (test)"** to see what an
   alert looks like. Again, nothing is sent without a real webhook.

You have now tried everything the program does in safe mode. Well done.

---

## Settings — everything is here

All settings live in the dashboard, on the main page in **section 5.
Settings — everything is here, no .env file needed**. You do not need
to edit any file. Click **"Save settings"** after changing anything.
Each group is explained below, in plain words.

### Mode — dry-run or live

This is the most important setting. It is a choice between two radio
buttons:

- **Dry-run (safe)** — nothing is posted to Viagogo. Listings are only
  simulated. This is the default. Leave it here until you have finished
  the whole "Going live" checklist.
- **⚠️ LIVE — posts REAL listings on Viagogo** — only choose this when
  you are ready to sell for real.

Switching to live needs **two steps on purpose**, so it cannot happen
by accident: (1) tick the box "I understand — live posts real listings
on Viagogo", and (2) type the word **LIVE** in the box. Even then, the
program still refuses live actions until a session is uploaded (below)
and the card / face-value / payout checks pass. To go back to safety
at any time, choose Dry-run again and save — nothing can be posted live
in dry-run.

### Seller session (Viagogo login)

A "session" is a file that proves you are logged in to Viagogo. The
program uses it instead of your username and password — your password
is never stored anywhere.

- **Upload session** — click it, choose your `auth_state.json` session
  file, and it is saved. The dashboard shows only the file name, size,
  and date — never what is inside it.
- **Clear session (log out)** — deletes the saved session. Live actions
  stop working until you upload a new one.

You do not have this file yet if you have never logged in through the
browser the way Shariful shows you. Leave this alone until the "Going
live" checklist.

### Opportunity Scanner

- **Live scans** — tick this to make the scanner look at real Viagogo
  pages. Off means it only uses the built-in sample numbers. Leave it
  off until your real events are in the watchlist. Two honest rules:
  if you ask for a live scan while this is off, you get an **error**,
  not sample numbers in disguise; and if every live page fails (for
  example Viagogo shows a challenge), you get an **error** listing what
  failed — never sample numbers. (See `LIVE_VERIFICATION.md` for what
  was actually checked live on 2026-10-28 and what could not be run
  on the dev computer.)
- **Seconds between live pages: 5** — how long the scanner waits
  between pages. Waiting is polite and makes blocking less likely.
  Do not set it below 5.
- **Page timeout** — how long to wait for a page to load before giving
  up. Leave it as it is.
- **Headless** — when on, the browser runs invisibly in the background.
  Leave it on.

### Training data & ML (Phase 2) — the auto-collector (new in v1.5.0)

The scanner's scoring today is rules only — no ML. ML comes later
(Phase 2), and it needs training data: many real price snapshots, taken
over weeks. The program now **collects that data by itself**:

- On the Opportunities page, section **"Training data"** shows how many
  snapshots exist, how many are real (LIVE) vs sample, which events are
  tracked, the first and last snapshot dates, and the next scheduled
  collection.
- **Auto-collect is ON by default, every 6 hours**, as long as the
  program is running. You can change the interval (1–24 hours), turn it
  on/off, turn on "collect when the program starts", and press
  **"Collect now"**. You never have to click anything for it to work —
  it runs in the background while the program runs.
- **Only real (live) snapshots become training data.** Sample numbers
  are stored too, but they are labelled SAMPLE and are never used as
  training data. If a collection fails (for example Viagogo shows a
  challenge), it is logged and the schedule keeps going — the program
  never crashes and old snapshots are never lost.
- **Download the data:** "Download training data (CSV)" or "(JSON)"
  on the Opportunities page, or `GET /api/snapshots/export?format=csv|json&source=live|sample|all`.
  Each row is one snapshot: when it was taken, which event, the event
  URL, category, section, currency, lowest price, average price, how
  many listings there were, how many people were looking, days until
  the event, and the source (live/sample).
- **How much data does ML need?** Weeks of daily snapshots — roughly
  20+ live snapshots per event over several weeks is a usable starting
  dataset (the Training data section says this in plain words too).
  ML itself is a separate Phase 2 step and is not in this version.

### Proxy

A proxy is a middleman server your internet traffic goes through. Most
people do not need one — leave this empty. If Shariful gives you a
proxy address, paste it here and click **"Test proxy"** to check it
works. The address is shown back only partly hidden, and its password
(if it has one) is never shown or written to the logs.

### Stealth (anti-detection)

"Stealth" means the program tries to look like a normal person using a
browser, not a robot. It is **on by default** — leave it on. It changes
small details like the browser type and screen size each time it starts,
and types slowly like a person. It does **not** make the program
invisible: Viagogo can still detect it, slow it down, or block it.

- **Language and time zone** — these should match the country of the
  seller account (the default is English, New York time). Only change
  them if Shariful tells you to.

### Seller fee % (for profit estimates)

This is the fee Viagogo takes from each sale, as a percent. The default
is **10%**. The scanner uses it to work out your profit: profit =
recommended price × (1 − fee%) − what you paid for the ticket. Change
it to the real Viagogo fee when you know it. If you do not know it yet,
leave it at 10.

### Server (needs a restart after changing)

- **Host: 127.0.0.1** — means "only this computer can open the
  dashboard". Leave it.
- **Port: 5002** — the number in the address
  http://127.0.0.1:**5002**. If another program already uses 5002, you
  can change it here — but then the address changes too, and you must
  restart the program for it to work.
- **Log level** — how much detail the program writes to its log file.
  Leave it at INFO.

After changing anything here, restart the program (close the black
window and double-click `run.bat` again).

### Discord (section 3)

Paste your Discord webhook address here (you get one from Discord:
Server Settings → Integrations → Webhooks → New Webhook → Copy
Webhook URL) and click **"Send test message"**. If the test message
arrives in your Discord channel, sale alerts will arrive there too.
You can leave this empty — the program works without Discord.

### CAPTCHA Solver — NopeCHA (section 4, optional, off by default)

A CAPTCHA is one of those "prove you are human" puzzles on websites.
Sometimes Viagogo shows one. When it does, the program normally
**stops** — it never tries to solve the puzzle by itself.

NopeCHA is an optional paid service that can try to solve the puzzle
for you. You do not need it to use the program. If you want it:

1. Sign up at **https://nopecha.com** and copy your API key. The free
   plan allows 100 solves per day. The Starter plan is $4.99/month.
   You pay for it, not Shariful.
2. In the dashboard, paste the key into the password box, tick
   **"Enable NopeCHA solving"**, and click **"Save CAPTCHA settings"**.
3. Click **"Check status / balance"** to make sure the key works.
4. Click **"Test (mock solve — no real API call)"** to test the wiring
   without spending any solves.

Honest warning: solving a CAPTCHA to get past Viagogo's checks **may
break Viagogo's rules and can get the seller account flagged or
suspended**. NopeCHA also does not guarantee a solve. And if Viagogo
shows a "Just a moment…" waiting page (with no puzzle to solve), no
service can solve that — the program stops, as it should.

---

## Going live — checklist

Do these in order. Stop at the first step that fails and fix it before
you go on. Do not skip steps.

- [ ] **1. Viagogo login (session).** Log in to the seller's Viagogo
  account once in a browser, save the login session, and upload it in
  the dashboard: Settings → Seller session. Never put a username or
  password in any file.
- [ ] **2. One sample event.** Pick ONE real Viagogo event from the
  seller's account. Use its real Viagogo link for the first live test.
  Do not start with a big batch.
- [ ] **3. Discord webhook.** Paste the real webhook address in the
  dashboard (section 3. Discord) and click the test button. Check the
  test message really arrives in Discord.
- [ ] **4. Card on file, face value, payout — done by hand in Viagogo.**
  Add a valid credit or debit card to the seller account yourself, in
  the Viagogo website. Have a face value for every listing. Set a
  payout method (PayPal email or Direct deposit). The program checks
  all three before it posts anything, and refuses if any is missing.
  **The program never types card details.**
- [ ] **5. One listing by hand first.** Create exactly 1 listing on the
  sample event **by hand** in the Viagogo website, so you know the
  "Create Listing" button and the confirmation work.
- [ ] **6. One listing with the program.** Now switch to live in
  Settings → Mode (tick the box AND type LIVE), and post **exactly 1
  listing** with the program. Check that it appears in the seller
  dashboard on Viagogo.
- [ ] **7. Small batch.** Only after step 6 works: a batch of 3–5
  listings. Check they appear and the prices are right. Only then
  think about more.
- [ ] **8. Written risk acceptance.** The client confirms in writing
  that they accept the speculative-listing risk (see the warning at the
  top of this guide). Do this before step 6.

To go back to safe mode at any time: switch Mode back to Dry-run in
Settings and save. Nothing can be posted live in dry-run.

---

## If something goes wrong

Find your problem in the table. Try the fix. If it still does not work,
see "Asking Shariful for help" at the bottom.

| Problem | What it means | What to do |
|---|---|---|
| `'python' is not recognized` when you double-click `run.bat` | Python is not installed, or the "Add to PATH" box was not ticked | Install Python again (Step 1) and tick **"Add python.exe to PATH"**. Then double-click `run.bat` again. |
| `python --version` shows an old version (below 3.11) | An old Python is installed | Install a newer Python from python.org. If two Pythons are installed, the new one may need `py --version` on Windows — ask Shariful. |
| The black window opens and closes at once | The program crashed at startup | Open the black window quickly and read the last lines, or open `logs/app.log` in the program folder and read the last lines. Send them to Shariful (see below). |
| `Address already in use` / port 5002 is busy | Another program already uses port 5002 | Close the other copy of this program if one is running. Or change the port in Settings → Server, restart, and use the new address. |
| The browser says "can't reach this site" for http://127.0.0.1:5002 | The program is not running | Check the black window is still open. If it is closed, double-click `run.bat` again and wait for the "Starting..." message. |
| The page loads but shows an old version / old numbers | The browser cached the old page | Press Ctrl + F5 in the browser to reload fully. |
| First start takes a long time | Normal on the first run | The program is downloading its parts. Wait a few minutes. Do not close the black window. |
| `pip install` fails / no internet errors | The download failed | Check your internet, close the black window, and run `run.bat` again. |
| The "Create Listing" button is greyed out / disabled on Viagogo | Viagogo wants a card on file, a face value, and a payout method first | Add a card, a face value, and a payout method in the Viagogo website by hand (checklist step 4). The program cannot do this for you and will refuse until it is done. |
| The program stops and says a challenge / Cloudflare page appeared | Viagogo showed a "prove you are human" page | This is normal protection. The program stops on purpose and never tries to get past it by itself. Wait a while and try again, or use the Viagogo website by hand. NopeCHA (section 4) can try to solve some puzzles, but not the "Just a moment…" waiting page. |
| NopeCHA says "not configured" | No API key has been added | That is fine — the program works without it. If you want it, follow the NopeCHA steps in the Settings section. |
| A scan shows profit as a negative number | The Max price is too low for that event | Raise Max price in section 1. Price rules (the default is 1500 since v1.4.0 — raise it above the ticket's real cost) and save, then run the scan again. |
| Discord test message never arrives | The webhook address is wrong or empty | Copy the webhook URL again from Discord and paste it in section 3. Discord, then click "Send test message" again. |
| You closed the black window by mistake | The program stopped | Just double-click `run.bat` again. Your listings and settings are saved in the program's database — nothing is lost. |
| A listing shows an error when you click Post in live mode | A live check failed (no session, no card, no face value, no payout) | Read the error message — it says which one is missing. Fix that one thing and try again. In dry-run, Post always works. |

### Asking Shariful for help

If you are stuck, send Shariful these two things:

1. What you were trying to do, and what happened, in your own words.
2. The last 20 lines of the file **`logs/app.log`** in the program
   folder. Open it with Notepad, copy the last lines, and paste them.

**Never send** your Viagogo password, your NopeCHA key, your Discord
webhook address, or the session file (`auth_state.json`). Shariful does
not need them, and they must stay private.

---

## For developers

This section is for people who write code. You can stop reading here
if you only use the program.

### Quick checks

```bash
python -m pytest tests/ -q
python scripts/test_end_to_end.py
python scripts/test_scanner_end_to_end.py
python scripts/test_mock_portal.py   # needs Chromium: python -m playwright install chromium
```

Expected: all tests pass, and the end-to-end scripts print
`ALL DRY-RUN END-TO-END CHECKS PASSED` and
`ALL SCANNER END-TO-END CHECKS PASSED`. The mock-portal test drives
`mock/mock_seller_portal.html` (the same 6 steps as the real seller
flow, with the same labels) and expects `MOCK-0001`.

### API (short version — full behaviour is in `app.py`)

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Health check: ok, version, dry_run, live_mode |
| GET | `/` | Main dashboard (listings) |
| GET | `/opportunities` | Opportunities page (watchlist + ranked list) |
| GET/POST | `/api/settings` | All dashboard settings. POST to `"live"` needs `confirm_live: true` + `confirm_text: "LIVE"` |
| POST | `/api/session/upload` | Upload a saved session file (multipart, field `file`) |
| POST | `/api/session/clear` | Delete the saved session file |
| POST | `/api/proxy/test` | Test the proxy (URL returned only masked) |
| GET/POST | `/api/config` | Price rules + Discord webhook |
| GET/POST | `/api/listings` | List / create one draft |
| POST | `/api/bulk` | Create N drafts for one event |
| POST | `/api/listings/<id>/post` | Post via bot (simulated in dry-run) |
| POST | `/api/listings/<id>/pause\|resume\|relist\|delete` | Maintain a listing |
| POST | `/api/listings/<id>/reprice` | Reprice (face_price or listing_price) |
| POST | `/api/discord/test` | Send Discord test message |
| POST | `/api/sales/check` | Poll seller dashboard for new sales |
| POST | `/api/sales/simulate` | Test-only: mark sold + fire Discord alert |
| GET | `/api/opportunities` | Ranked opportunities (heuristic scoring) |
| POST | `/api/scan` | Run a market scan (mock/sample by default; live only when "Live scans" is on in Settings). Response has `data_source` ("live" or "sample"). An explicit live request with Live scans off → 400; every live check failing → 502 with `live_errors`. Never substitutes sample for live. |
| GET | `/api/training` | Training-data stats + auto-collector status + plain-English `ml_readiness` (v1.5.0) |
| GET | `/api/snapshots/export?format=csv\|json&source=live\|sample\|all` | Download the full training dataset (CSV default, live rows only) (v1.5.0) |
| GET/POST | `/api/collector` | Auto-collector status / settings: enabled, interval hours (1–24), run-on-start (v1.5.0) |
| POST | `/api/collector/run-now` | Start a collection run now in the background (409 if one is already running) (v1.5.0) |
| GET/POST | `/api/watchlist` | List / add a watched event |
| DELETE | `/api/watchlist/<id>` | Remove a watched event |
| POST | `/api/watchlist/seed` | Load `watchlist.example.json` (5 events, skips duplicates) |
| GET | `/api/snapshots` | Price-snapshot history (`?event_url=…&limit=50`) |
| POST | `/api/opportunities/test-discord` | Send top opportunity to Discord (dry-run payload if no webhook) |
| GET/POST | `/api/captcha/config` | NopeCHA settings (key returned only masked) |
| POST | `/api/captcha/status` | Check the NopeCHA key (`GET https://api.nopecha.com/v1/status`) |
| POST | `/api/captcha/test` | Mock solve — no real API call, no credits spent |
| GET | `/api/events/search?q=…` | Event search (fake match in dry-run) |

### How it works, in short

- **Web UI** (`http://127.0.0.1:5002`): Flask app (`app.py`), SQLite
  database (`data/listings.db`), settings stored in the database.
- **Seller bot** (`viagogo_bot.py`): Playwright browser bot, verified
  6-step Sell pipeline against the real portal to PriceDetails
  (observed live 2026-10-28, logged in, Metallica sample, no listing
  created): search → Quantity → ListingNotes → DeliveryDetails →
  SeatDetails → PriceDetails → "Create Listing". Card-blocker
  pre-flight refuses without card on file / face value / payout, and
  never enters card details.
- **Stealth** (`stealth.py`, v1.2.1): randomised desktop user-agent and
  viewport per launch, locale/timezone matching the seller store
  (`en-US` / `America/New_York`), an init script hiding the usual
  automation tells (`navigator.webdriver`, `window.chrome`, plugins,
  languages), character-by-character typing and small random mouse
  moves. Challenge detection stops the bot (or attempts one NopeCHA
  solve when enabled and configured).
- **NopeCHA** (`captcha.py`, v1.2.2): optional Token API (reCAPTCHA
  v2/v3, Cloudflare Turnstile) + Recognition API. One attempt per
  challenge page, max 2 attempts per solve call. Key from the dashboard
  or `NOPECHA_API_KEY`; never logged, shown only masked. Works without
  a key (stop-on-challenge) and without the `nopecha` package.
- **Opportunity Scanner** (`market.py`, `scoring.py`, v1.2.0):
  heuristic scoring, rules R1–R12 in `scoring.py` (the code is the
  spec). Market price = lowest listing (else average); recommended =
  market + demand premium (High +10%, Medium +5%, Low +0%) + scarcity
  premium (≤5 listings +5%, >20 listings −5%) + urgency premium
  (event ≤7 days and High demand +5%), clamped to min/max, rounded to
  .99; profit = recommended × (1 − fee%) − buy cost (fee% default 10%,
  an estimate); confidence starts at 100 and loses points for missing
  fields; risk is High when margin <10% or confidence <40 or the market
  is crowded or the event is <3 days away; ranking is profit ×
  confidence. Every scan stores a row in `price_snapshots`, so price
  history builds up for a future ML model. Mock/sample scans use
  `mock/sample_snapshots.json` (every number labelled SAMPLE).
- **Settings** (`settings.py`, v1.3.0): defaults, validation (unknown
  keys fail loudly), storage_state validation, proxy masking + probing.
  All settings in the dashboard; environment variables are only an
  optional override for advanced users (a set variable wins, and the
  dashboard says so). `DATABASE_PATH` is intentionally not editable in
  the UI.
- **Safety model:** dry-run is the default; posting is simulated and
  returns a fake id like `DRY-0001`. A live run needs live mode on in
  Settings (tick + type `LIVE`), a saved session file, and the card /
  face-value / payout pre-flight. The app always starts, so blockers
  can be fixed in the dashboard; live actions are refused until every
  check passes. No Viagogo credentials are in this repo; `.env`,
  `*.db`, `auth_state.json`, `logs/` are gitignored; webhook URLs and
  session contents are never logged.

### Files

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
settings.py             Dashboard settings (v1.3.0): defaults, validation,
                        session-file + proxy checks — no .env needed
market.py               Public market monitor (Playwright, no login) + parsers
                        — v1.5.0: reads real Viagogo page text ("Tickets from
                        $X", "3,895 people viewed …", "Only 1% of tickets
                        left") and reports live errors honestly, never
                        substituting sample data
collector.py            Auto-collector (v1.5.0): background scheduler that
                        scans the watchlist every 6h (configurable) and
                        stores ONLY live snapshots as ML training data
scoring.py              Heuristic opportunity scoring, rules R1–R12 (pure, tested)
pricing.py              Markup / clamp / round rules (pure functions)
discord_notify.py       Discord webhook (sale + opportunity alerts + test)
db.py                   SQLite: listings, sales, config, price_snapshots, watchlist
templates/index.html    Main dashboard (sections 1–6)
templates/opportunities.html  Opportunities page (watchlist + ranked list)
mock/mock_seller_portal.html   Fake 6-step seller flow for browser testing
mock/mock_sales_portal.html    Fake seller sales page (1 sold listing) for sale-detection tests
mock/mock_sales_portal_none_sold.html   Same sales page with nothing sold (must find 0 sales)
tests/test_payout.py, tests/test_sales.py   Payout per listing + sale detection tests (v1.4.0)
tests/test_autocollect.py, tests/fixtures/real_page_text.txt   Auto-collector + honest-live tests (v1.5.0, 17 cases — parser tests use REAL Viagogo page text observed 2026-10-28)
scripts/verify_live.py  Live verification for a REAL computer (v1.5.0): runs the real scanner against the real Viagogo pages + checks the sell-portal login gate — run this on a normal machine, NOT on the dev VM (see LIVE_VERIFICATION.md)
LIVE_VERIFICATION.md    Evidence note (v1.5.0): real URLs checked, real numbers, what failed, and what is still not proven live
HANDOVER.md                  One-page client handover (v1.5.0)
mock/sample_snapshots.json     SAMPLE market data for offline scanner demos
watchlist.example.json  5-event watchlist template (Metallica + Real Madrid CF artist pages verified live 2026-10-28, plus placeholders)
tests/                  Unit tests (pricing, bot steps, stealth, captcha,
                        scoring, market parsing, settings)
scripts/test_end_to_end.py     Full dry-run flow, no browser/Viagogo
scripts/test_scanner_end_to_end.py  Scanner flow: seed -> mock scan -> ranked -> Discord
scripts/test_mock_portal.py    Mock-portal browser test (needs Chromium)
config.example.json / .env.example   Templates — no real credentials
run.bat / run.sh        One-command launchers (Windows / Mac & Linux)
Dockerfile, docker-compose.yml, viagogo.service   Docker + systemd deployment
```

### Honest limits

- No official Viagogo seller API was found; the bot drives the seller
  portal in a browser, so portal changes or Cloudflare challenges can
  break it. No Cloudflare/CAPTCHA was seen in the logged-in pipeline
  on 2026-10-28, but pages load blank for a few seconds — the bot waits
  generously. **Stealth only reduces detection risk; it does not
  guarantee invisibility and never bypasses a challenge — if one
  appears the bot stops.**
- The **"Create Listing" click is unverified live** (needs card on file
  + face value + payout); the bot refuses without them.
- Sale detection (`/api/sales/check`) is **implemented** (v1.4.0): it
  drives the logged-in seller dashboard and matches sold rows to your
  listings (exact text → partial text → page-text scan), then fires
  the Discord sale alert. It is proven against the mock sales page
  only — the real sales-page URL and selectors are **not yet verified
  against a real sale**, so confirm the first real sale by hand in the
  seller dashboard. In dry-run, or live without a session, it returns
  "not available" and never fakes a sale.
- Every listing now carries its own payout info (v1.4.0): payout
  method (PayPal / Direct deposit) + PayPal email, set in the bulk
  form (one payout for the whole batch) and shown in the listings
  table. The email is shown only masked (first 4 characters + `***`)
  and never written to the logs. The bot's live pre-flight uses the
  listing's own payout info and refuses a live post without it.
- No automatic ticket buying, no e-ticket upload, no multi-account support.
- Prices are per-listing rules only; no competitor-price scraping yet.
- The scanner scores the LATEST snapshot only; it does not predict
  future prices (no ML). **New in v1.5.0: the auto-collector builds the
  ML training data automatically** (every 6h by default, only live
  snapshots count — see "Training data & ML (Phase 2)" above). Live
  market data needs the "Live scans" toggle in Settings and Fayed's
  real event list — sample numbers must never be acted on. A live
  Playwright run against viagogo.com itself could NOT be done from the
  dev VM: its egress proxy answers Chromium's CONNECT with 403
  `policy_denied` (proven with a net-log, see `LIVE_VERIFICATION.md`).
  The same browser code was proven against the real Viagogo page text
  on a local copy (lowest $813 USD, 3,895 people, 20 tickets left).
  Run `scripts/verify_live.py` on a normal computer for the live proof.
- NopeCHA (v1.2.2) is optional and OFF by default. It attempts at most
  ONE solve per challenge page and never retries a page; a Cloudflare
  interstitial (no sitekey) cannot be solved by the Token API, and
  solving a CAPTCHA may violate Viagogo's terms and increases
  account-ban risk. NopeCHA does not guarantee a solve. The hCaptcha
  Token endpoint was discontinued by NopeCHA in Oct 2026, so hCaptcha
  solves may fail with 410 — handled as a normal solve failure.
