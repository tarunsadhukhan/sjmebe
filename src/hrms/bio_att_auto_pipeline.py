"""bio_att_auto_pipeline.py — In-app automated bio-attendance pipeline.

Runs the Bprocess chain automatically on a schedule for a single configured
tenant/branch:

    Etrack Process (D)  ->  Bprocess  ->  B Atten  ->  Final Process

The biometric device punches are assumed to be written into
``bio_attendance_table`` by an EXTERNAL process (roughly hourly). This job does
NOT fetch from the device — it only processes whatever rows are present, then
posts results into ``daily_attendance``.

Key behaviours
--------------
* Fires every hour (interval configurable). Started/stopped from the FastAPI
  app lifecycle (see src/main.py), behind the BIO_ATT_AUTO_ENABLED flag.
* Skips a run when no new punches have arrived since the last run, detected via
  a high-water mark on ``bio_att_id`` (the auto-increment PK — reliable even
  when ``bio_att_log_id`` arrives blank/0 and is filled later by Etrack (D)).
* When new punches exist it re-processes the affected date(s) AND each prior
  day. The prior-day term closes a night shift whose OUT punch arrives the next
  morning; a same-day late OUT punch is caught because it is itself a new row on
  the same date. Every step deletes-then-rebuilds the date, so re-processing an
  unchanged date is harmless.

Configuration (environment variables)
-------------------------------------
  BIO_ATT_AUTO_ENABLED       master on/off (default "false")
  BIO_ATT_AUTO_TENANT        tenant/subdomain = MySQL DB name (e.g. dev3)
  BIO_ATT_AUTO_BRANCH        branch_id for daily_attendance
  BIO_ATT_AUTO_COMPANY_ID    company id (default 2)
  BIO_ATT_AUTO_INTERVAL_MIN  minutes between runs (default 60)

Manual one-shot run (for verification)
--------------------------------------
  python -m src.hrms.bio_att_auto_pipeline --tenant dev3 --branch 1
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from src.hrms.bioAttUpdation import (
    etrack_process_d_core,
    etrack_process_d_prepare,
    bprocess_core,
    b_atten_core,
)
from src.hrms.bio_att_scheduler import make_session, step3_final_process

log = logging.getLogger("bio_att_auto")

# Module-level scheduler handle (set by start_scheduler).
_scheduler = None


# ── Config ───────────────────────────────────────────────────────────────────

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _read_config() -> dict | None:
    """Read pipeline config from env. Returns None if disabled or misconfigured."""
    if not _env_bool("BIO_ATT_AUTO_ENABLED", False):
        log.info("BIO_ATT_AUTO_ENABLED is not set — automated pipeline disabled.")
        return None

    tenant = (os.environ.get("BIO_ATT_AUTO_TENANT") or "").strip()
    branch_raw = (os.environ.get("BIO_ATT_AUTO_BRANCH") or "").strip()
    if not tenant or not branch_raw:
        log.error(
            "BIO_ATT_AUTO_ENABLED is true but BIO_ATT_AUTO_TENANT / "
            "BIO_ATT_AUTO_BRANCH are missing — pipeline NOT started."
        )
        return None
    try:
        branch_id = int(branch_raw)
    except ValueError:
        log.error("BIO_ATT_AUTO_BRANCH=%r is not an integer — pipeline NOT started.", branch_raw)
        return None

    try:
        company_id = int(os.environ.get("BIO_ATT_AUTO_COMPANY_ID", "2"))
    except ValueError:
        company_id = 2
    try:
        interval_min = max(1, int(os.environ.get("BIO_ATT_AUTO_INTERVAL_MIN", "60")))
    except ValueError:
        interval_min = 60

    return {
        "tenant": tenant,
        "branch_id": branch_id,
        "company_id": company_id,
        "interval_min": interval_min,
    }


# ── Pure helpers (unit-tested) ───────────────────────────────────────────────

def compute_dates_to_process(new_dates) -> list[date]:
    """Given the distinct dates of newly-arrived punches, return the dates whose
    daily attendance must be (re)built: each new date plus the day before it.

    The prior-day term ensures a night shift whose OUT punch lands the following
    morning still gets closed. Result is sorted, de-duplicated.
    """
    out: set[date] = set()
    for d in new_dates:
        out.add(d)
        out.add(d - timedelta(days=1))
    return sorted(out)


def should_skip(current_max, last_processed_id: int) -> bool:
    """True when there is no new data to process."""
    return current_max is None or int(current_max) <= int(last_processed_id)


def compute_high_water_mark(
    current_max: int, last_id: int, failed_min_new_id: int | None
) -> int:
    """Decide the new high-water mark after a pipeline pass.

    The mark is advanced ONLY across dates whose chain completed all the way
    through final process. ``failed_min_new_id`` is the smallest ``bio_att_id``
    (strictly greater than ``last_id``) belonging to any date that did NOT fully
    complete — e.g. one where the connection dropped after ``daily_attendance_basic``
    but before ``daily_attendance``. It is ``None`` when every date succeeded (or
    the failed dates carried no new punches), in which case we advance to
    ``current_max``.

    When a date failed, we stop the mark just below its earliest new punch so
    that punch — and everything after it — is re-detected and retried on the next
    tick (the chain is idempotent: each step deletes-then-rebuilds the date). The
    result never moves backward (>= last_id) and never exceeds current_max.
    """
    if failed_min_new_id is None:
        return int(current_max)
    return max(int(last_id), min(int(current_max), int(failed_min_new_id) - 1))


# ── State table (high-water mark) ────────────────────────────────────────────

_CREATE_STATE_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS bio_att_auto_state (
        branch_id        INT       NOT NULL PRIMARY KEY,
        last_bio_att_id  BIGINT    NOT NULL DEFAULT 0,
        last_run_at      DATETIME  NULL
    )
    """
)

_GET_LAST_ID_SQL = text(
    "SELECT last_bio_att_id FROM bio_att_auto_state WHERE branch_id = :branch_id"
)

_UPSERT_LAST_ID_SQL = text(
    """
    INSERT INTO bio_att_auto_state (branch_id, last_bio_att_id, last_run_at)
    VALUES (:branch_id, :last_id, NOW())
    ON DUPLICATE KEY UPDATE
        last_bio_att_id = VALUES(last_bio_att_id),
        last_run_at     = VALUES(last_run_at)
    """
)

# Heartbeat: bump last_run_at on every tick (even skipped ones) WITHOUT moving
# the high-water mark, so last_run_at reliably reports "the job is alive" rather
# than "the last time new data was processed".
_TOUCH_RUN_AT_SQL = text(
    """
    INSERT INTO bio_att_auto_state (branch_id, last_bio_att_id, last_run_at)
    VALUES (:branch_id, 0, NOW())
    ON DUPLICATE KEY UPDATE last_run_at = NOW()
    """
)

_MAX_BIO_ATT_ID_SQL = text("SELECT MAX(bio_att_id) AS max_id FROM bio_attendance_table")

# MySQL named lock — guarantees a single concurrent run even when the app is
# launched with multiple uvicorn workers (each starts its own scheduler).
_LOCK_NAME = "bio_att_auto"
_GET_LOCK_SQL = text("SELECT GET_LOCK(:name, 0) AS got")
_RELEASE_LOCK_SQL = text("SELECT RELEASE_LOCK(:name)")

# ── Self-healing lock ─────────────────────────────────────────────────────────
# GET_LOCK is connection-scoped: it releases when the holding connection closes.
# A run that is KILLED mid-flight leaves its connection lingering server-side as
# an idle "Sleep", holding the lock for hours (until the default 8h wait_timeout)
# and blocking every later run. To self-heal:
#   1) shrink the lock connection's idle wait_timeout to LOCK_WAIT_TIMEOUT_SEC, and
#   2) keep a LIVE run's connection fresh with a heartbeat every LOCK_HEARTBEAT_SEC.
# A live run keeps pinging, so it never times out. A killed run stops pinging, so
# the server reaps its connection within ~LOCK_WAIT_TIMEOUT_SEC and the lock frees
# itself — no manual KILL, no extra privilege, no lock table.
LOCK_HEARTBEAT_SEC = 30      # ping the lock connection this often during a run
LOCK_WAIT_TIMEOUT_SEC = 120  # server closes the idle lock conn after this (> heartbeat)
_LOCK_HEARTBEAT_SQL = text("SELECT 1")
_SET_LOCK_WAIT_TIMEOUT_SQL = text("SET SESSION wait_timeout = :w")


def _lock_heartbeat(lock_db: Session, stop: threading.Event) -> None:
    """Ping the lock connection every LOCK_HEARTBEAT_SEC until ``stop`` is set.

    Runs in a daemon thread that owns ``lock_db`` exclusively while a run is in
    progress (the main thread works on its own ``db`` session and never touches
    ``lock_db`` until this thread has stopped). Each ping resets the connection's
    idle timer so a live run never hits wait_timeout. If a ping fails (connection
    already gone), the heartbeat exits — the lock is effectively released anyway.
    """
    while not stop.wait(LOCK_HEARTBEAT_SEC):
        try:
            lock_db.execute(_LOCK_HEARTBEAT_SQL)
        except Exception:
            log.warning("bio_att_auto lock heartbeat failed — stopping heartbeat.")
            break

_NEW_DATES_SQL = text(
    """
    SELECT DISTINCT DATE(log_date) AS d
    FROM bio_attendance_table
    WHERE bio_att_id > :last_id AND log_date IS NOT NULL
    ORDER BY d
    """
)

_DATES_SINCE_SQL = text(
    """
    SELECT DISTINCT DATE(log_date) AS d
    FROM bio_attendance_table
    WHERE log_date IS NOT NULL AND DATE(log_date) >= :since
    ORDER BY d
    """
)

# Smallest new (id > last_id) bio_att_id among a set of dates. Used to hold the
# high-water mark below dates whose chain did not complete, so they retry.
_MIN_NEW_ID_FOR_DATES_SQL = text(
    """
    SELECT MIN(bio_att_id) AS min_id
    FROM bio_attendance_table
    WHERE bio_att_id > :last_id
      AND log_date IS NOT NULL
      AND DATE(log_date) IN :dates
    """
).bindparams(bindparam("dates", expanding=True))


def _ensure_state_table(db: Session) -> None:
    db.execute(_CREATE_STATE_SQL)
    db.commit()


def _get_last_bio_att_id(db: Session, branch_id: int) -> int:
    row = db.execute(_GET_LAST_ID_SQL, {"branch_id": branch_id}).first()
    return int(row[0]) if row and row[0] is not None else 0


def _get_max_bio_att_id(db: Session):
    row = db.execute(_MAX_BIO_ATT_ID_SQL).mappings().first()
    return row["max_id"] if row else None


def _rows_to_dates(rows) -> list[date]:
    out: list[date] = []
    for r in rows:
        d = r[0]
        out.append(d if isinstance(d, date) else date.fromisoformat(str(d)))
    return out


def _get_new_dates(db: Session, last_id: int) -> list[date]:
    return _rows_to_dates(db.execute(_NEW_DATES_SQL, {"last_id": last_id}).fetchall())


def _get_dates_since(db: Session, since: date) -> list[date]:
    return _rows_to_dates(
        db.execute(_DATES_SINCE_SQL, {"since": since.isoformat()}).fetchall()
    )


def _get_min_new_id_for_dates(db: Session, last_id: int, dates) -> int | None:
    """Smallest new (bio_att_id > last_id) punch id among ``dates`` (ISO strings),
    or None when those dates carry no new punches."""
    if not dates:
        return None
    row = db.execute(
        _MIN_NEW_ID_FOR_DATES_SQL,
        {"last_id": int(last_id), "dates": list(dates)},
    ).first()
    return int(row[0]) if row and row[0] is not None else None


def _set_last_bio_att_id(db: Session, branch_id: int, last_id: int) -> None:
    db.execute(_UPSERT_LAST_ID_SQL, {"branch_id": branch_id, "last_id": int(last_id)})
    db.commit()


def _touch_last_run_at(db: Session, branch_id: int) -> None:
    """Heartbeat — record that the job ran now, without advancing the
    high-water mark. Best-effort: never let a heartbeat failure abort a run."""
    try:
        db.execute(_TOUCH_RUN_AT_SQL, {"branch_id": branch_id})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


# ── Pipeline core ────────────────────────────────────────────────────────────

def _run_chain_for_date(db: Session, tran_date: str, branch_id: int) -> None:
    """Run the four-step chain for a single date. Each step commits internally
    and is idempotent (delete-then-rebuild).

    The table-global Etrack pre-steps (emp_code / bio_att_log_id / device_id
    back-fill) are NOT run here — run_once runs them once per pass via
    etrack_process_d_prepare, so we pass run_prepare=False to avoid repeating
    three full-table UPDATEs for every date."""
    etrack_process_d_core(db, tran_date, run_prepare=False)
    bprocess_core(db, tran_date)
    b_atten_core(db, tran_date)
    step3_final_process(db, tran_date=tran_date, branch_id=branch_id, dry_run=False)


def run_once(
    tenant: str,
    branch_id: int,
    company_id: int = 2,
    since: date | None = None,
) -> dict:
    """One pipeline pass for the given tenant/branch.

    Normal mode (since=None): detects new punches via the bio_att_id high-water
    mark, processes the affected dates (+ prior day each), then advances the
    high-water mark.

    Seeding mode (since set): ignores the high-water mark and processes every
    distinct date on/after `since`, then advances the high-water mark to the
    current max so subsequent runs are incremental. Use for a bounded first run.

    Returns a summary dict.
    """
    db = make_session(tenant)
    # Dedicated session for the named lock: GET_LOCK is connection-scoped, so we
    # keep this session on a single connection (never commit on it) for the whole
    # run while `db` commits freely across the chain.
    lock_db = make_session(tenant)
    locked = False
    hb_stop = threading.Event()
    hb_thread = None
    try:
        # Shrink the lock connection's idle timeout so a run that is killed
        # mid-flight does not hold the lock for hours — the server reaps the now
        # un-heartbeated connection within ~LOCK_WAIT_TIMEOUT_SEC, freeing the lock.
        try:
            lock_db.execute(_SET_LOCK_WAIT_TIMEOUT_SQL, {"w": LOCK_WAIT_TIMEOUT_SEC})
        except Exception:
            log.warning("Could not set wait_timeout on lock connection (continuing).")

        # Single-run guard across workers/instances. If another run holds the
        # lock, skip immediately rather than queueing.
        got = lock_db.execute(_GET_LOCK_SQL, {"name": _LOCK_NAME}).scalar()
        if not got:
            log.info(
                "Another bio_att_auto run holds the lock — skipping this tick "
                "(tenant=%s branch=%s).", tenant, branch_id,
            )
            return {"skipped": True, "reason": "locked"}
        locked = True

        # Keep the lock connection alive for as long as THIS run is working, so a
        # live run is never mistaken for a dead one and reaped. A daemon thread
        # owns lock_db exclusively from here until the finally block stops it.
        hb_thread = threading.Thread(
            target=_lock_heartbeat, args=(lock_db, hb_stop),
            name="bio_att_lock_hb", daemon=True,
        )
        hb_thread.start()

        _ensure_state_table(db)
        # Heartbeat first thing inside the lock: even a no-op tick updates
        # last_run_at so it reflects "job is alive", not "last data processed".
        _touch_last_run_at(db, branch_id)
        current_max = _get_max_bio_att_id(db)
        if current_max is None:
            log.info("bio_attendance_table is empty for tenant=%s — nothing to do.", tenant)
            return {"skipped": True, "reason": "empty"}
        current_max = int(current_max)

        # Baseline mark — used in both modes as the floor when advancing the
        # high-water mark after the run (it must never move backward).
        last_id = _get_last_bio_att_id(db, branch_id)

        if since is not None:
            dates = sorted(set(_get_dates_since(db, since)))
            log.info(
                "tenant=%s branch=%s: SEEDING from %s -> processing %d date(s): %s",
                tenant, branch_id, since.isoformat(), len(dates),
                [d.isoformat() for d in dates],
            )
        else:
            if should_skip(current_max, last_id):
                log.info(
                    "No new data for tenant=%s branch=%s (max=%s, last=%s) — skipping.",
                    tenant, branch_id, current_max, last_id,
                )
                return {"skipped": True, "max_id": current_max, "last_id": last_id}

            new_dates = _get_new_dates(db, last_id)
            dates = compute_dates_to_process(new_dates)
            log.info(
                "tenant=%s branch=%s: %d new-date(s) -> processing %d date(s): %s",
                tenant, branch_id, len(new_dates), len(dates),
                [d.isoformat() for d in dates],
            )

        # Run the table-global Etrack pre-steps ONCE for the whole pass (rather
        # than once per date). If they fail (e.g. connection drop), abort this
        # tick without advancing the high-water mark so everything retries.
        try:
            etrack_process_d_prepare(db)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            log.error(
                "tenant=%s branch=%s: etrack prepare FAILED — aborting tick, "
                "high-water left at %d (retry next tick)\n%s",
                tenant, branch_id, last_id, traceback.format_exc(),
            )
            return {
                "skipped": False,
                "max_id": current_max,
                "high_water": last_id,
                "processed": [],
                "failed": [d.isoformat() for d in dates],
            }

        processed: list[str] = []
        failed: list[str] = []
        for d in dates:
            tran_date = d.isoformat()
            try:
                _run_chain_for_date(db, tran_date, branch_id)
                processed.append(tran_date)
                log.info("tenant=%s branch=%s: %s OK", tenant, branch_id, tran_date)
            except Exception:
                log.error(
                    "tenant=%s branch=%s: pipeline FAILED for %s\n%s",
                    tenant, branch_id, tran_date, traceback.format_exc(),
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                failed.append(tran_date)
                # The connection may be dead (e.g. lost connection mid-query):
                # a poisoned session would fail every remaining date. Replace it
                # with a fresh session so one failure doesn't cascade.
                try:
                    db.close()
                except Exception:
                    pass
                db = make_session(tenant)

        # Advance the high-water mark ONLY across dates that completed the WHOLE
        # chain through final process. A date that failed part-way (e.g. the
        # connection dropped after daily_attendance_basic but before
        # daily_attendance) must keep its punches above the mark so the next tick
        # re-detects and retries them — the chain is idempotent. If we cannot
        # safely compute/store the new mark, leave it untouched so nothing is
        # skipped (everything retries next tick).
        new_high = current_max
        try:
            if failed:
                failed_min_new_id = _get_min_new_id_for_dates(db, last_id, failed)
                new_high = compute_high_water_mark(
                    current_max, last_id, failed_min_new_id
                )
            _set_last_bio_att_id(db, branch_id, new_high)
            log.info(
                "tenant=%s branch=%s: high-water -> %d (processed=%d, failed=%d)",
                tenant, branch_id, new_high, len(processed), len(failed),
            )
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            log.error(
                "tenant=%s branch=%s: could NOT advance high-water mark safely "
                "(left at %d so failed/unprocessed dates retry next tick)\n%s",
                tenant, branch_id, last_id, traceback.format_exc(),
            )
            new_high = last_id
        return {
            "skipped": False,
            "max_id": current_max,
            "high_water": new_high,
            "processed": processed,
            "failed": failed,
        }
    finally:
        # Stop the heartbeat and wait for it to release lock_db before this thread
        # touches that connection again (release / close).
        hb_stop.set()
        if hb_thread is not None:
            hb_thread.join(timeout=LOCK_HEARTBEAT_SEC + 5)
        if locked:
            try:
                lock_db.execute(_RELEASE_LOCK_SQL, {"name": _LOCK_NAME})
            except Exception:
                pass
        try:
            lock_db.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


# ── Scheduler wiring ─────────────────────────────────────────────────────────

def _scheduled_job() -> None:
    """Job body invoked by APScheduler. Reads config fresh each run so env
    changes are picked up without a restart; never raises (logs instead)."""
    cfg = _read_config()
    if cfg is None:
        return
    try:
        run_once(cfg["tenant"], cfg["branch_id"], cfg["company_id"])
    except Exception:
        log.error("bio_att_auto scheduled run crashed:\n%s", traceback.format_exc())


def start_scheduler():
    """Create and start the APScheduler job if enabled. Idempotent.

    NOTE: this runs in-process. If the app is ever launched with multiple
    uvicorn workers, each worker starts its own scheduler and the job fires once
    per worker. Current deployment is single-worker. For multi-worker, gate with
    a DB lock or move to the CLI + OS scheduler.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cfg = _read_config()
    if cfg is None:
        return None

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception as exc:
        import sys
        log.error(
            "Cannot import APScheduler with interpreter %s — automated "
            "bio-attendance pipeline cannot start. Real error: %r. Install it "
            "into THIS interpreter:  %s -m pip install -r requirements.txt",
            sys.executable, exc, sys.executable,
        )
        return None

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_job,
        trigger=IntervalTrigger(minutes=cfg["interval_min"]),
        id="bio_att_auto",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        # Fire once right after startup instead of waiting a full interval.
        # IntervalTrigger otherwise schedules the first run at start+interval, so
        # every app restart (e.g. dev reload) would lose up to interval_min of
        # processing. Seeding next_run_time=now closes that gap.
        next_run_time=datetime.now(),
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "bio_att_auto scheduler started: tenant=%s branch=%s every %d min.",
        cfg["tenant"], cfg["branch_id"], cfg["interval_min"],
    )
    return scheduler



def stop_scheduler() -> None:
    """Shut the scheduler down (called on app shutdown)."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            log.info("bio_att_auto scheduler stopped.")
        except Exception:
            log.warning("bio_att_auto scheduler shutdown error:\n%s", traceback.format_exc())
        finally:
            _scheduler = None


# ── CLI (manual one-shot run) ────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="One-shot automated bio-attendance pipeline run.")
    p.add_argument("--tenant", required=True, help="MySQL tenant/subdomain DB name")
    p.add_argument("--branch", required=True, type=int, help="branch_id")
    p.add_argument("--company_id", default=2, type=int)
    p.add_argument(
        "--since",
        default=None,
        help="YYYY-MM-DD: bounded first run — process every date on/after this "
             "date, then seed the high-water mark so later runs are incremental.",
    )
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    since = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            p.error(f"--since {args.since!r} is not a valid YYYY-MM-DD date")

    result = run_once(args.tenant, args.branch, args.company_id, since=since)
    log.info("run_once result: %s", result)


if __name__ == "__main__":
    main()
