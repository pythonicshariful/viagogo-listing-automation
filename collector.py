"""Automatic ML training-data collection (v1.5.0).

Shariful's complaint was fair: ML training data does not collect itself.
This module is the answer — a background scheduler thread that runs
inside the Flask app and automatically scans every watchlist event on
a schedule (default every 6 hours, changeable in the dashboard), with
no clicks needed from the user. Every successful LIVE scan stores one
row per event in the `price_snapshots` table, which IS the ML training
dataset (see README § ML training data).

Honesty rules (non-negotiable):
- ONLY real live snapshots become training data. A snapshot is stored
  by the collector only when its source is "live" AND it has a real
  lowest_price. Sample/mock numbers are NEVER stored as training data.
- When live scans are OFF, the scheduled run does nothing except record
  "skipped — live scans are off" in its status, so the dashboard says
  so plainly instead of pretending to collect.
- A failed scan never crashes the app and never stops the schedule:
  the failure is logged + recorded in the status, the old snapshots
  stay untouched, and the next run happens on time.
- The thread is a daemon: it never blocks app shutdown.

The collector knows nothing about Flask or the database layout: the app
injects a `collect_fn` (scan the watchlist + store the snapshots, return
a result dict) and a `status_fn` pair for reading/writing its persisted
state. Pure scheduling logic here, so it is unit-testable offline.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("viagogo-listing-automation.collector")

DEFAULT_INTERVAL_HOURS = 6.0
MIN_INTERVAL_HOURS = 1.0
MAX_INTERVAL_HOURS = 24.0


def validate_interval_hours(value) -> tuple[float | None, str | None]:
    """Collector interval in hours: 1–24. Returns (hours, None) or
    (None, plain-English error)."""
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return None, "collection interval must be a number of hours"
    if not MIN_INTERVAL_HOURS <= hours <= MAX_INTERVAL_HOURS:
        return None, "collection interval must be between 1 and 24 hours"
    return hours, None


def next_run_at(last_run_at: str | None, interval_hours: float,
                now: datetime | None = None) -> str:
    """ISO timestamp of the next scheduled run. When nothing ever ran,
    the next run is one interval from now (unless run-on-start fires)."""
    now = now or datetime.now(timezone.utc)
    if last_run_at:
        try:
            last = datetime.fromisoformat(last_run_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (last + timedelta(hours=interval_hours)).isoformat()
        except ValueError:
            pass
    return (now + timedelta(hours=interval_hours)).isoformat()


def is_live_training_snapshot(snap: dict) -> bool:
    """Only a REAL live snapshot with a real price is training data.
    Sample numbers, challenge blocks and failed loads are not."""
    return snap.get("source") == "live" and snap.get("lowest_price") is not None


class AutoCollector:
    """Background scheduler: call `start()` once, it runs until `stop()`.

    `collect_fn` is called with no arguments on every run and must return
    a dict like {"stored": n, "scanned": m, "skipped": bool,
    "skip_reason": str|None, "errors": [...]}. It may raise — the
    scheduler catches everything, records the failure in the status,
    and keeps the schedule. `status_reader` / `status_writer` persist
    the status dict (the app stores it in the SQLite config).
    """

    def __init__(self, collect_fn, status_reader=None, status_writer=None,
                 interval_hours: float = DEFAULT_INTERVAL_HOURS,
                 run_on_start: bool = False):
        self._collect_fn = collect_fn
        self._status_reader = status_reader or (lambda: {})
        self._status_writer = status_writer or (lambda status: None)
        self.interval_hours = interval_hours
        self.run_on_start = run_on_start
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = threading.Event()
        self._lock = threading.Lock()

    # -- status ---------------------------------------------------------------
    def status(self) -> dict:
        """Persisted status + live fields (next run, currently running)."""
        saved = dict(self._status_reader() or {})
        saved.setdefault("enabled", True)
        saved.setdefault("interval_hours", self.interval_hours)
        saved.setdefault("run_on_start", self.run_on_start)
        saved.setdefault("last_run_at", None)
        saved.setdefault("last_run_status", "never run")
        saved.setdefault("total_runs", 0)
        saved.setdefault("total_snapshots", 0)
        saved["running"] = self._running.is_set()
        saved["next_run_at"] = next_run_at(saved.get("last_run_at"),
                                           float(saved.get("interval_hours", self.interval_hours)))
        return saved

    def _save(self, patch: dict) -> dict:
        with self._lock:
            saved = dict(self._status_reader() or {})
            saved.update(patch)
            self._status_writer(saved)
            return saved

    # -- one run ----------------------------------------------------------------
    def run_once(self) -> dict:
        """One collection run, right now, in the calling thread.

        Returns the result dict. Never raises: failures are recorded
        in the status and returned as {"ok": False, ...}."""
        self._running.set()
        try:
            result = self._collect_fn()
        except Exception as exc:  # noqa: BLE001 — a failed run must not kill the schedule
            logger.exception("Auto-collect run failed")
            result = {"ok": False, "stored": 0, "scanned": 0,
                      "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        finally:
            self._running.clear()
        status = self.status()
        total_runs = int(status.get("total_runs", 0)) + 1
        total_snapshots = int(status.get("total_snapshots", 0)) + int(result.get("stored", 0))
        if result.get("skipped"):
            last_status = f"skipped — {result.get('skip_reason') or 'live scans are off'}"
        elif result.get("ok") is False:
            last_status = f"failed — {result.get('error') or 'unknown error'}"
        else:
            last_status = (f"ok — {result.get('stored', 0)} live snapshots stored "
                           f"from {result.get('scanned', 0)} events")
            if result.get("errors"):
                last_status += f" ({len(result['errors'])} events failed — see logs)"
        self._save({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_run_status": last_status,
            "total_runs": total_runs,
            "total_snapshots": total_snapshots,
        })
        logger.info("Auto-collect run: %s", last_status)
        return result

    def run_in_background(self) -> bool:
        """Start one run in a background thread. False when a run is
        already in progress — never stack two live scans on top of each
        other (the check + start are atomic under the lock)."""
        with self._lock:
            if self._running.is_set():
                return False
            self._running.set()
        threading.Thread(target=self.run_once, name="auto-collector-now",
                         daemon=True).start()
        return True

    # -- scheduler thread -------------------------------------------------------
    def start(self) -> bool:
        """Start the background thread. False if already running."""
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="auto-collector",
                                        daemon=True)
        self._thread.start()
        logger.info("Auto-collector started (interval %.1fh, run_on_start=%s)",
                    self.interval_hours, self.run_on_start)
        return True

    def _loop(self) -> None:
        if self.run_on_start:
            self.run_once()
        while not self._stop.wait(timeout=self.interval_hours * 3600):
            self.run_once()

    def stop(self) -> None:
        """Stop the background thread (the daemon flag means the app can
        also just exit — this is for clean shutdowns and tests)."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
