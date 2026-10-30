# Viagogo Listing Automation — Live Test Bugs

## Context

- **Version tested:** v1.5.1
- **Test date:** 2026-10-30
- **OS:** Windows 11 Pro, version 10.0.26200
- **Browser:** Integrated Chromium 150.0.7871.250
- **Repository:** `pythonicshariful/viagogo-listing-automation`
- **Safety constraints:** Dry-run only. No Viagogo login, credentials, payment data, listing creation, or live posting was performed.

This report is based on an actual browser test against public Viagogo pages. The observed ground-truth prices below are evidence that the pages were accessible in the integrated browser; they are not claims that the values remain current.

## Executive summary

The application dashboard loads and shows `DRY-RUN`, but the live-check feature cannot launch its Playwright browser because the required Chromium executable is missing. As a result, all three event checks fail before navigation and return no market data.

The standalone `verify_live.py --headed` command has a separate code bug: it reaches the artist-page control, then crashes with a missing required argument before checking the single-event page.

Training-data collection is also blocked because live scans are disabled. `Collect now` reports that it skipped collection and leaves the dataset empty.

The dashboard additionally defaults the watchlist entries to the wrong category/currency for the test data: all three events were shown as `football` and `GBP`, including the Metallica concert whose observed prices were in USD.

## Reproduction setup

The app was already running at:

`http://127.0.0.1:5002`

The dashboard and Opportunities page both loaded successfully, and the top badge showed `DRY-RUN`.

The following single-event URLs were added to the watchlist:

1. Metallica — Oct 31, Sphere at The Venetian Resort  
   `https://www.viagogo.com/Concert-Tickets/Hard-Rock-and-Metal-Music/Metallica-Tickets/E-160569462`
2. Real Madrid CF vs RC Celta de Vigo — Nov 21  
   `https://www.viagogo.com/Sports-Tickets/Soccer/Real-Madrid-CF-Tickets/E-161344545`
3. FC Barcelona vs Deportivo Alavés — Oct 31  
   `https://www.viagogo.com/Sports-Tickets/Soccer/FC-Barcelona-Tickets/E-161307545`

The actual saved watchlist URLs included query parameters, but the event IDs above identify the same single-event pages.

## Bug 1 — Dashboard live check cannot launch Playwright Chromium

### Severity

**Critical:** the main live-check feature cannot perform any live check.

### Steps to reproduce

1. Start the app.
2. Open `/opportunities`.
3. Add the three single-event URLs listed above.
4. Tick **Show browser**.
5. Click **Run live check**.
6. Wait for the run to finish.

### Expected behavior

The app should launch the configured browser, open each event URL, collect the lowest price, average price, listing count, people/demand data, and signals, then save evidence.

### Actual behavior

All three events returned `live-failed`:

```text
BrowserType.launch: Executable doesn't exist at
C:\Users\pytho\AppData\Local\ms-playwright\chromium-1140\chrome-win\chrome.exe
```

The dashboard displayed:

```text
Live check FAILED — see the reason for each event below and the evidence file:
C:\Users\pytho\Downloads\viagogo-listing-automation\logs\live-check-a54c5cad.txt
```

Each result had:

```text
source: live-failed
lowest: GBP —
avg: —
listings: —
people: —
signals: —
```

The failed check did not reach the event pages or the sell portal.

### Likely root cause

The live-check implementation launches a separate Playwright-managed Chromium installation at a hard-coded/expected revision (`chromium-1140`), but that executable is not installed on the machine. The integrated browser used for manual verification is available, but the application does not reuse it.

### Fix requirements

- Make browser startup use the repository's supported Playwright installation/configuration.
- Do not silently convert missing-browser setup into a misleading market-data result.
- If the executable is missing, show an actionable setup error identifying the exact installation command or supported setup path.
- Keep the dry-run/live-mode safety boundary intact.
- Add a regression test for missing browser executable handling.
- Verify that a successful run produces real per-event results and evidence files.

## Bug 2 — `verify_live.py --headed` crashes before the single-event check

### Severity

**High:** the required verification command cannot complete.

### Steps to reproduce

From the repository root, run:

```powershell
python scripts/verify_live.py --headed
```

### Expected behavior

The script should:

1. Open the artist page as a control.
2. Select one event link.
3. Open and inspect the single-event page.
4. Report title, final URL, HTTP status, page-text length, first 500 characters, challenge status, and screenshot/evidence paths.
5. Continue or stop cleanly with an explicit result if a challenge or browser error occurs.

### Actual behavior

The artist-page control ran, then the script terminated with an uncaught exception:

```text
TypeError: collect_event_via_artist() missing 1 required positional argument: 'event_link_text'
```

Traceback location:

```text
scripts\verify_live.py", line 98, in main
    snap, diag = monitor.collect_event_via_artist(
scripts\verify_live.py", line 152, in <module>
```

The script did not complete the single-event check.

### Additional observed control result

The artist page correctly showed that it is not a single-event page:

```text
page kind: artist (38 events)
lowest: USD None
avg: None
listings: None
people: 8211
signals: []
HTTP status: 403
```

The saved screenshot was:

`logs/live-Metallica-artist-page-control-1793357734.png`

The screenshot visibly showed the Metallica artist page with 38 events and 8,211 people viewing Metallica events. It did not show event ticket prices.

### Fix requirements

- Inspect the `collect_event_via_artist` signature and update the caller to pass `event_link_text`.
- Add a focused test that exercises the artist-page-to-single-event click-through path.
- Catch and report expected browser/navigation failures in the script rather than leaving an uncaught traceback.
- Preserve the explicit distinction between artist pages and single-event pages.
- Ensure evidence and screenshot paths are reported for every attempted check.

## Bug 3 — Auto-collector cannot collect live training data in the tested configuration

### Severity

**High:** the advertised training-data workflow produces no data.

### Steps to reproduce

1. Add the three events to the watchlist.
2. Open the **Training data** section.
3. Record the counters.
4. Click **Collect now**.
5. Wait and refresh the section.

### Expected behavior

`Collect now` should scan the watchlist and store live snapshots, or clearly prevent the action until live scans are enabled.

### Actual behavior

Before collection:

```text
TOTAL SNAPSHOTS: 0
LIVE (TRAINING DATA): 0
SAMPLE (DEMO ONLY): 0
EVENTS TRACKED: 0
FIRST → LAST: — → —
Auto-collect: ON — every 6h
last run: never run
```

After clicking **Collect now**, the UI first displayed:

```text
Collection is running in the background — refresh Training data in a moment to see the result.
```

The final status was:

```text
last run: skipped — live scans are off — turn on Live scans in Settings (Scanner) to collect real training data
```

The counters remained zero.

### Fix requirements

Choose and implement one clear product behavior:

- Either make `Collect now` validate the live-scan setting before starting and display the blocking requirement immediately, or
- Allow the user to enable live scans and then successfully collect snapshots.

In either case:

- Do not claim collection is running if it will immediately be skipped.
- Make the required Settings change discoverable from the Training data section.
- Add tests for live scans disabled and enabled.
- Ensure only live snapshots enter the live training-data export; sample data must remain clearly labelled and excluded where intended.

## Bug 4 — Watchlist defaults category and currency incorrectly

### Severity

**Medium:** this can produce incorrect interpretation, ranking, and exported metadata.

### Steps to reproduce

1. Add the Metallica single-event page using the default form values.
2. Inspect the watchlist table.

### Expected behavior

The event metadata should use the selected category and the currency appropriate to the event/page, or require the user to choose currency explicitly without presenting a misleading default.

### Actual behavior

The watchlist table showed the Metallica concert as:

```text
football · ...Metallica... 
General
GBP 100
2
```

The two football events also showed `GBP 100`, although the observed Viagogo event pages displayed USD prices.

The observed ground truth was:

| Event | Lowest observed price | Currency |
|---|---:|---|
| Metallica Oct 31 | $385 | USD |
| Real Madrid CF vs RC Celta de Vigo | $113 | USD |
| FC Barcelona vs Deportivo Alavés | $78 | USD |

### Fix requirements

- Do not silently default a concert to `football`.
- Make category selection persist correctly for each event.
- Make currency handling explicit and consistent with the live page/parser.
- Avoid converting or labelling prices as GBP unless the user selected GBP and conversion is actually implemented.
- Add form and persistence tests for concert and football entries.

## Bug 5 — Dashboard evidence is incomplete when browser startup fails

### Severity

**Medium:** failures are recorded, but the evidence shape is not useful enough for diagnosis.

### Actual evidence

The dashboard evidence file was:

`logs/live-check-a54c5cad.txt`

For each event it recorded:

```text
page kind: unknown
page title: (no title)
HTTP status: None
readable text: 0 chars
page text (first 500 chars): (empty)
```

No event screenshots were saved for the failed live-check run.

### Fix requirements

- Record the browser startup failure as a distinct infrastructure/setup failure.
- Do not report empty page content as if a page was inspected.
- Include a clear failure phase such as `browser-launch`.
- Save an evidence record even when the browser cannot be created.
- If no screenshot is possible, explicitly state `screenshot: unavailable — browser did not launch`.

## Sell portal result

The manual sell-portal flow worked without login:

1. Opened `https://sell.viagogo.com`.
2. Selected **Sell Tickets**.
3. Searched for `Metallica`.
4. Selected the Metallica Las Vegas event.
5. Reached:

   `https://sell.viagogo.com/secure/Pipeline/Sell/Authenticate/Login?EventID=160569462`

The login gate showed:

- `Sign in to viagogo`
- `Email`
- `Sign In`
- `Create Account`
- `Sign in with Facebook`
- `protected by reCAPTCHA`

No credentials were entered. No listing was created.

This manual result also shows that the sell portal can reach a login gate in a real browser, while the dashboard live check incorrectly reported `Sell portal login gate: Not reached` only because its own browser failed to launch.

## Acceptance criteria for the fix

The bugs should be considered fixed only when all of the following are true:

1. `http://127.0.0.1:5002/` loads and remains `DRY-RUN`.
2. `/opportunities` accepts the three single-event URLs without classifying them as artist pages.
3. The dashboard live check launches its supported browser without requiring an unavailable hard-coded executable.
4. The live check returns a truthful result for each event, including source, lowest price, average price, listing count, people, signals, and status.
5. Browser-launch failures are explicit infrastructure failures, not empty market results.
6. `python scripts/verify_live.py --headed` completes its intended control and single-event flow, or reports a clean, actionable challenge/browser failure without an uncaught `TypeError`.
7. The evidence file includes title, final URL, HTTP status, text length, first 500 characters, challenge detection, and screenshot paths where available.
8. Training-data collection does not claim to be running when live scans are disabled.
9. With live scans enabled and a working browser, `Collect now` creates live snapshots or reports the exact per-event failure.
10. CSV export contains the expected columns and accurately reports the number of data rows.
11. Category and currency metadata are not silently wrong.
12. No test requires logging in, entering credentials, posting a listing, or bypassing CAPTCHA/Cloudflare/DataDome.

## Relevant evidence files

- [Dashboard live-check evidence](./logs/live-check-a54c5cad.txt)
- [Artist-page control screenshot](./logs/live-Metallica-artist-page-control-1793357734.png)
- [Application log](./logs/app.log)

