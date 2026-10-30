# Viagogo bot — bug-fix report (v1.5.2)
Date/time: 2026-10-30
Tests before: Python 3.9 collection failed because the repository uses Python 3.10+ union syntax (`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`) → Tests after: 166 passed under Python 3.12

## Bug 1 — browser launch
- Root cause found: the expected Playwright Chromium revision was not installed on this PC.
- What I changed (files/functions): `market.py` now tries bundled Chromium, then system Chrome, then Edge, and raises an actionable infrastructure error recommending `python -m playwright install chromium` or `run.bat install-browser`. Live checks expose the failure instead of returning an empty market result.
- New tests: browser-launch failure and actionable-message regression coverage in `tests/test_livecheck.py`.
- Live verification: the dashboard checked all three re-added URLs. Each returned `live-empty`, lowest `—`, listings `—`, people `—`, signals `—`, and HTTP 403 with zero readable characters. This is **NO MATCH** with the fresh ground truth ($385 USD Metallica, $113 USD Real Madrid, $78 USD Barcelona) because Viagogo blocked the browser response; no market number was claimed.

## Bug 2 — verify_live.py crash
- Root cause found: `collect_event_via_artist` requires `event_link_text`; the script omitted it and also imported `event_link_hint` from the wrong module.
- What I changed: `scripts/verify_live.py` now imports `event_link_hint` from `livecheck` and passes it for the Metallica and Real Madrid click-through checks. The script prints clean per-check diagnostics and returns non-zero on blocked/failed verification.
- New tests: event-link hint and artist click-through call coverage in `tests/test_livecheck.py`.
- Live verification: the script completed without a traceback. Artist control: FAILED, HTTP 403, 0 readable chars, screenshot saved under `logs/live-Metallica-artist-page-control-*.png`. Metallica click-through: FAILED because the artist page was blocked, screenshot under `logs/live-artist-Metallica-*.png`. Real Madrid click-through: FAILED for the same reason, screenshot under `logs/live-artist-Real-Madrid-*.png`. Sell gate: reached at `https://sell.viagogo.com/selltickets`, HTTP 200, 3823 page-text characters, screenshot under `logs/live-sell-gate-*.png`. Evidence: `logs/live-check-68a9b606.txt`.

## Bug 3 — Collect now
- Behavior implemented: with Live scans off, Collect now returns immediately with HTTP 409 and a settings link; it does not claim that a background run started. With Live scans on, it starts a real scan and stores only successful `source=live` snapshots.
- What I changed: preflight was added to `/api/collector/run-now`; the Training data section displays the blocked state and links to `/#scanner`. Live snapshots remain the only training-data rows.
- New tests: live-scans-off blocking, live scanner storage, and CSV export shape in `tests/test_autocollect.py`.
- Live verification: off state showed immediately: “Live scans are off. Turn them on to collect real training data in Settings → Opportunity Scanner.” After enabling Live scans, the run completed with `0` snapshots from `3` events and `3 events failed` because all three Viagogo pages returned HTTP 403. CSV download succeeded with the expected columns and `0` data rows (header only); no blocked or sample snapshot was stored.

## Bug 4 — category / currency
- Root cause found: the watchlist form did not preserve a currency choice and defaulted displayed rows to GBP; category handling also ignored the selected/inferred concert category.
- What I changed: added explicit currency selection, preserved the selected category, and inferred `concert` from `/Concert-Tickets/` and `football` from `/Sports-Tickets/`. Live prices retain the currency returned by the page.
- New tests: concert category inference, explicit currency persistence, and live currency display coverage in `tests/test_autocollect.py`.
- Live verification: after deleting and re-adding the three rows, the dashboard displayed:
  - Metallica Oct 31 — `concert` — `USD 100`
  - Real Madrid Nov 21 — `football` — `USD 100`
  - FC Barcelona Oct 31 — `football` — `USD 100`

## Bug 5 — evidence on infrastructure failure
- What I changed: every live diagnostic now has a phase (`browser-launch`, `navigation`, `challenge`, `parse`, or `ok`). Browser-launch failures include the launch error, `screenshot: unavailable — browser did not launch`, and an infrastructure-failure result. HTTP 403/empty responses retain their screenshot and are reported as blocked page evidence rather than market data.
- New tests: launch-failure evidence shape and phase assertions in `tests/test_livecheck.py`.
- Evidence sample: the real run recorded `HTTP status: 403`, `readable text: 0 chars`, `page text (first 500 chars): (empty)`, and a concrete screenshot path for each blocked market page. The screenshot is evidence of the blocked response, not an empty successful page.

## Remaining problems (anything still failing, with exact error text)

1. Viagogo market pages returned HTTP 403 with no readable text in this verification environment. Exact reason shown: “The page loaded but contained almost no readable text (0 chars) — it may be a bot-check page, a blank page, or a redirect.”
2. The real market checks therefore produced no prices and cannot be called live-verified on this run.
3. The sell portal was reachable and the login gate was detected; no credentials were entered.

## Safety statement
- App mode after all work: DRY-RUN (confirm)
- Real listing posted: NO
- Logged in anywhere: NO
