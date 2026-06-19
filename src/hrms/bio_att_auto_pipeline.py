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
import traceback
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.hrms.bioAttUpdation import (
    etrack_process_d_core,
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
    and is idempotent (delete-then-rebuild)."""
    etrack_process_d_core(db, tran_date)
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
    try:
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

        _ensure_state_table(db)
        # Heartbeat first thing inside the lock: even a no-op tick updates
        # last_run_at so it reflects "job is alive", not "last data processed".
        _touch_last_run_at(db, branch_id)
        current_max = _get_max_bio_att_id(db)
        if current_max is None:
            log.info("bio_attendance_table is empty for tenant=%s — nothing to do.", tenant)
            return {"skipped": True, "reason": "empty"}
        current_max = int(current_max)

        if since is not None:
            dates = sorted(set(_get_dates_since(db, since)))
            log.info(
                "tenant=%s branch=%s: SEEDING from %s -> processing %d date(s): %s",
                tenant, branch_id, since.isoformat(), len(dates),
                [d.isoformat() for d in dates],
            )
        else:
            last_id = _get_last_bio_att_id(db, branch_id)
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

        _set_last_bio_att_id(db, branch_id, current_max)
        log.info(
            "tenant=%s branch=%s: high-water -> %d (processed=%d, failed=%d)",
            tenant, branch_id, current_max, len(processed), len(failed),
        )
        return {
            "skipped": False,
            "max_id": current_max,
            "processed": processed,
            "failed": failed,
        }
    finally:
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
    except Exception:
        log.error(
            "APScheduler is not installed — automated bio-attendance pipeline "
            "cannot start. Add 'APScheduler' to requirements and install it."
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
