"""bio_att_scheduler.py — Scheduled bio-attendance sync and full pipeline.

Fetches new punch records from the Etrack SQL Server starting from the last
synced bio_att_log_id in bio_attendance_table, then runs the full 3-step
pipeline for every new date discovered:

  Step 1 – Etrack Data   : Transfer new rows from SQL Server DeviceLogs_* tables
                           into bio_attendance_table. Back-fills eb_id, device_id,
                           dept_id, desig_id via link master + daily_attendance.
  Step 2 – Etrack Process: Resolve remaining unlinked rows; build
                           daily_attendance_process_table rows for each date.
  Step 3 – Final Process : Delete existing daily_attendance rows by bio_id,
                           insert fresh rows from the process table.

Example usage
-------------
  # Run interactively
  python -m src.hrms.bio_att_scheduler --tenant dev3 --branch 1

  # As a cron / Windows Task Scheduler entry
  python -m src.hrms.bio_att_scheduler --tenant dev3 --branch 1 --company_id 2

  # Dry-run (fetch & print only, no MySQL writes)
  python -m src.hrms.bio_att_scheduler --tenant dev3 --branch 1 --dry-run

CLI flags
---------
  --tenant      Tenant/subdomain name = MySQL database name (REQUIRED)
  --branch      branch_id for daily_attendance.branch_id (REQUIRED)
  --company_id  Etrack CompanyId filter (default: 2)
  --dry-run     Print actions without writing to MySQL
  --log-level   DEBUG | INFO | WARNING (default: INFO)

The script reads the same env files as the main app:
  env/database.env       (MySQL credentials)
  .env.sqlserver         (Etrack SQL Server credentials)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

# ── Bootstrap paths so `src.*` imports work when run as a script ─────────────
_ROOT = Path(__file__).resolve().parents[2]  # project root (contains src/)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Load env files early ─────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / "env" / "database.env", override=False)
    # .env.sqlserver is loaded later by etrack_conn
except Exception:
    pass

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ── Import helpers from bioAttUpdation ──────────────────────────────────────
from src.hrms.bioAttUpdation import (
    # Step 1 helpers
    ETRACK_INSERT_SQL,
    _backfill_links,
    _resolve_dept_desig,
    # Step 2 SQL / helpers
    _ETRACK_PROC_UNRESOLVED_SQL,
    _ETRACK_PROC_LAST_DAILY_ATT_SQL,
    _ETRACK_PROC_OFFICIAL_SQL,
    _ETRACK_PROC_UPDATE_SQL,
    IS_OFF_DAY_SQL,
    DELETE_DAY_ROWS_SQL,
    _process_etrack_day,
    _bucket_hours,
    # Step 3 SQL / helpers
    FINAL_FETCH_SQL,
    FINAL_INSERT_SQL,
    FINAL_MARK_PROCESSED_SQL,
    FINAL_DELETE_EXISTING_SQL,
    FINAL_LAST_EBMC_SQL,
    FINAL_INSERT_EBMC_SQL,
    _resolve_spell_by_time,
)

log = logging.getLogger("bio_att_scheduler")


# ── MySQL session factory ────────────────────────────────────────────────────

def make_session(tenant: str) -> Session:
    """Create a SQLAlchemy session bound to the tenant MySQL database."""
    user = os.environ["DATABASE_USER"]
    pwd  = os.environ["DATABASE_PASSWORD"]
    host = os.environ["DATABASE_HOST"]
    port = os.environ.get("DATABASE_PORT", "3306")
    url  = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{tenant}"
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET SESSION time_zone='+05:30'"},
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── SQL Server table-range helpers ───────────────────────────────────────────

def _monthly_tables(from_date: date, to_date: date) -> list[tuple[str, date, date]]:
    """Return list of (table_name, month_start, month_end) from from_date to to_date.

    Each entry covers one calendar month.  The list is ordered oldest-first.
    """
    tables: list[tuple[str, date, date]] = []
    cur = from_date.replace(day=1)
    end = to_date.replace(day=1)
    while cur <= end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        month_end = nxt - timedelta(days=1)
        tables.append((
            f"DeviceLogs_{cur.month}_{cur.year}",
            cur,
            month_end,
        ))
        cur = nxt
    return tables


def _table_exists(sconn, table_name: str) -> bool:
    """Check if table exists in the SQL Server database (quick OBJECT_ID test)."""
    try:
        cur = sconn.cursor()
        cur.execute(
            "SELECT OBJECT_ID(?, 'U')",
            f"dbo.{table_name}",
        )
        row = cur.fetchone()
        return row is not None and row[0] is not None
    except Exception:
        return False


# ── Step 1 – Etrack Data ─────────────────────────────────────────────────────

def step1_etrack_data(
    db: Session,
    *,
    last_log_id: int,
    last_log_date: date,
    company_id: int,
    dry_run: bool,
) -> tuple[int, set[date]]:
    """Fetch new rows from SQL Server, insert into bio_attendance_table.

    Returns (inserted_count, set_of_new_dates).
    """
    from src.hrms.etrack_conn import get_etrack_connection  # lazy import

    today = date.today()
    tables = _monthly_tables(last_log_date, today)
    log.info(
        "Step 1 | last bio_att_log_id=%s (log_date=%s), "
        "tables to query: %s",
        last_log_id, last_log_date,
        [t[0] for t in tables],
    )

    try:
        sconn = get_etrack_connection()
    except Exception as exc:
        log.error("Cannot connect to Etrack SQL Server: %s", exc)
        raise

    inserted_total = 0
    new_dates: set[date] = set()

    try:
        for idx, (table_name, _m_start, _m_end) in enumerate(tables):
            is_first_table = (idx == 0)

            if not _table_exists(sconn, table_name):
                log.warning("Step 1 | table %s does not exist — skipping", table_name)
                continue

            # For the first (oldest) table filter by DeviceLogId > last_log_id.
            # For subsequent tables fetch everything.
            if is_first_table:
                sql = (
                    f"SELECT dl.DeviceLogId, dl.DeviceId, dl.UserId, dl.LogDate, "
                    f"       dl.Direction, em.EmployeeId, em.EmployeeCode, "
                    f"       em.EmployeeName, em.CompanyId "
                    f"FROM dbo.{table_name} dl "
                    f"LEFT JOIN dbo.Employees em "
                    f"  ON em.EmployeeCodeInDevice = dl.UserId "
                    f"WHERE dl.DeviceLogId > ? "
                    f"  AND em.CompanyId = ? "
                    f"ORDER BY dl.DeviceLogId"
                )
                params = (last_log_id, company_id)
            else:
                sql = (
                    f"SELECT dl.DeviceLogId, dl.DeviceId, dl.UserId, dl.LogDate, "
                    f"       dl.Direction, em.EmployeeId, em.EmployeeCode, "
                    f"       em.EmployeeName, em.CompanyId "
                    f"FROM dbo.{table_name} dl "
                    f"LEFT JOIN dbo.Employees em "
                    f"  ON em.EmployeeCodeInDevice = dl.UserId "
                    f"WHERE em.CompanyId = ? "
                    f"ORDER BY dl.DeviceLogId"
                )
                params = (company_id,)

            try:
                cur = sconn.cursor()
                cur.execute(sql, *params)
                src_rows = cur.fetchall()
            except Exception as exc:
                log.error("Step 1 | query failed on %s: %s", table_name, exc)
                continue

            log.info("Step 1 | %s -> %d row(s) fetched", table_name, len(src_rows))
            inserted = 0

            for r in src_rows:
                direction = (str(r.Direction).strip().lower() if r.Direction is not None else None)
                if direction and len(direction) > 10:
                    direction = direction[:10]

                log_date = r.LogDate  # pyodbc returns datetime
                params_ins = {
                    "bio_att_log_id": int(r.DeviceLogId) if r.DeviceLogId is not None else None,
                    "emp_code":       str(r.EmployeeCode) if r.EmployeeCode is not None else None,
                    "emp_anme":       str(r.EmployeeName) if r.EmployeeName is not None else None,
                    "bio_id":         int(r.UserId) if r.UserId is not None else None,
                    "log_date":       log_date,
                    "device_direction": direction,
                    "device_id":      int(r.DeviceId) if r.DeviceId is not None else None,
                }
                if params_ins["bio_att_log_id"] is None:
                    continue

                if dry_run:
                    inserted += 1
                    if log_date is not None:
                        d = log_date.date() if isinstance(log_date, datetime) else log_date
                        new_dates.add(d)
                    continue

                try:
                    res = db.execute(ETRACK_INSERT_SQL, params_ins)
                    rows_affected = int(res.rowcount or 0)
                    inserted += rows_affected
                    if rows_affected and log_date is not None:
                        d = log_date.date() if isinstance(log_date, datetime) else log_date
                        new_dates.add(d)
                except Exception as exc:
                    log.warning(
                        "Step 1 | insert failed DeviceLogId=%s: %s",
                        params_ins["bio_att_log_id"], exc,
                    )

            if not dry_run:
                db.commit()
            inserted_total += inserted
            log.info("Step 1 | %s -> %d new row(s) inserted", table_name, inserted)

    finally:
        try:
            sconn.close()
        except Exception:
            pass

    if not dry_run and inserted_total > 0:
        # Back-fill eb_id / device_id from link master
        log.info("Step 1 | back-filling link master (eb_id / device_id) …")
        try:
            link_counts = _backfill_links(db)
            db.commit()
            log.info("Step 1 | back-fill done: %s", link_counts)
        except Exception as exc:
            log.warning("Step 1 | back-fill failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

        # Resolve dept_id / desig_id for newly linked rows
        log.info("Step 1 | resolving dept/desig …")
        try:
            dept_desig = _resolve_dept_desig(db)
            db.commit()
            log.info("Step 1 | dept/desig resolved: %s", dept_desig)
        except Exception as exc:
            log.warning("Step 1 | dept/desig resolve failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass

    log.info(
        "Step 1 | total inserted=%d across %d new date(s): %s",
        inserted_total, len(new_dates), sorted(new_dates),
    )
    return inserted_total, new_dates


# ── Step 2 – Etrack Process ──────────────────────────────────────────────────

def step2_etrack_process(
    db: Session,
    *,
    tran_date: str,
    branch_id: int,
    dry_run: bool,
) -> dict:
    """Resolve unlinked bio_attendance rows then build daily_attendance_process_table rows."""

    log.info("Step 2 | etrack_process for %s …", tran_date)

    if dry_run:
        log.info("Step 2 | dry-run: skipping DB writes for %s", tran_date)
        return {"resolved": 0, "updated": 0, "inserted": 0}

    # Resolve eb_id for rows where eb_id IS NULL
    unresolved_rows = db.execute(_ETRACK_PROC_UNRESOLVED_SQL).fetchall()
    resolve_result = {
        "resolved": 0, "updated": 0,
        "from_daily_attendance": 0, "fallback_official": 0, "no_source": 0,
    }

    if unresolved_rows:
        emp_eb_map: dict[str, int] = {
            str(r.emp_code): int(r.eb_id)
            for r in unresolved_rows
            if r.eb_id is not None
        }
        if emp_eb_map:
            unique_eb_ids = list(set(emp_eb_map.values()))

            da_rows = db.execute(
                _ETRACK_PROC_LAST_DAILY_ATT_SQL,
                {"eb_ids": tuple(unique_eb_ids)},
            ).fetchall()
            da_map: dict[int, tuple] = {
                int(r.eb_id): (r.worked_department_id, r.worked_designation_id)
                for r in da_rows
                if r.worked_department_id is not None
            }

            missing_eb_ids = [eid for eid in unique_eb_ids if eid not in da_map]
            official_map: dict[int, tuple] = {}
            if missing_eb_ids:
                off_rows = db.execute(
                    _ETRACK_PROC_OFFICIAL_SQL,
                    {"eb_ids": tuple(missing_eb_ids)},
                ).fetchall()
                official_map = {int(r.eb_id): (r.dept_id, r.desig_id) for r in off_rows}

            updated = 0
            fallback_official = 0
            no_source = 0

            for emp_code, eb_id in emp_eb_map.items():
                if eb_id in da_map:
                    dept_id, desig_id = da_map[eb_id]
                elif eb_id in official_map:
                    dept_id, desig_id = official_map[eb_id]
                    fallback_official += 1
                else:
                    no_source += 1
                    continue
                res = db.execute(
                    _ETRACK_PROC_UPDATE_SQL,
                    {"eb_id": eb_id, "dept_id": dept_id,
                     "desig_id": desig_id, "emp_code": emp_code},
                )
                updated += int(res.rowcount or 0)

            db.commit()
            resolve_result = {
                "resolved": len(emp_eb_map), "updated": updated,
                "from_daily_attendance": len(da_map),
                "fallback_official": fallback_official, "no_source": no_source,
            }

    # Check off-day
    is_off_row = db.execute(IS_OFF_DAY_SQL, {"tran_date": tran_date}).fetchone()
    is_off_day = bool(is_off_row and int(is_off_row.cnt) > 0)

    # Delete existing process-table rows for the date (re-run safe)
    db.execute(DELETE_DAY_ROWS_SQL, {"tran_date": tran_date})
    db.commit()

    inserted = _process_etrack_day(
        db, tran_date=tran_date, is_off_day=is_off_day,
    )
    db.commit()

    result = {
        **resolve_result,
        "is_off_day": is_off_day,
        "inserted": inserted,
    }
    log.info("Step 2 | %s result: %s", tran_date, result)
    return result


# ── Step 3 – Final Process ───────────────────────────────────────────────────

def step3_final_process(
    db: Session,
    *,
    tran_date: str,
    branch_id: int,
    dry_run: bool,
) -> dict:
    """Copy processed=1 rows into daily_attendance (delete by bio_id first)."""

    log.info("Step 3 | final_process for %s …", tran_date)

    rows = db.execute(FINAL_FETCH_SQL, {"tran_date": tran_date}).fetchall()
    log.info("Step 3 | %s -> %d processed row(s) to finalise", tran_date, len(rows))

    if dry_run:
        log.info("Step 3 | dry-run: skipping DB writes for %s", tran_date)
        return {"inserted": 0, "skipped": 0, "deleted_existing": 0}

    # Delete existing daily_attendance rows by bio_id
    bio_ids = [r._mapping["bio_id"] for r in rows if r._mapping.get("bio_id") is not None]
    deleted_existing = 0
    if bio_ids:
        del_res = db.execute(FINAL_DELETE_EXISTING_SQL, {"bio_ids": tuple(bio_ids)})
        deleted_existing = del_res.rowcount
        log.info(
            "Step 3 | %s -> deleted %d existing daily_attendance row(s) "
            "for %d bio_id(s)",
            tran_date, deleted_existing, len(bio_ids),
        )

    inserted = 0
    skipped = 0

    for r in rows:
        m = r._mapping
        spell = _resolve_spell_by_time(
            m.get("check_in"), m.get("check_out"), m.get("Ot_hours")
        )
        if spell is None:
            skipped += 1
            continue

        try:
            wh = float(m.get("Working_hours") or 0)
        except Exception:
            wh = 0.0
        try:
            ot = float(m.get("Ot_hours") or 0)
        except Exception:
            ot = 0.0

        # Bucket hours: >=7 -> 8, [3, 7) -> 4, <3 -> 0.
        wh = _bucket_hours(wh)
        ot = _bucket_hours(ot)

        inserts: list[tuple[str, float]] = []
        if wh > 0 and ot > 0:
            inserts.append(("P", wh))
            inserts.append(("O", ot))
        elif wh > 0:
            inserts.append(("P", wh))
        elif ot > 0:
            inserts.append(("O", ot))
        else:
            skipped += 1
            continue

        base = {
            "attendance_date":   m.get("attendance_date"),
            "attendance_source": m.get("attendance_source") or "BIO",
            "eb_id":             m.get("eb_id"),
            "bio_id":            m.get("bio_id"),
            "branch_id":         branch_id,
            "worked_department_id": m.get("dept_id"),
            "worked_designation_id": m.get("desig_id"),
            "entry_time":        m.get("check_in"),
            "exit_time":         m.get("check_out"),
            "spell":             spell,
            "spell_hours":       m.get("spell_hours"),
        }

        for att_type, hours in inserts:
            ins_res = db.execute(FINAL_INSERT_SQL, {
                **base,
                "attendance_type": att_type,
                "working_hours": hours,
            })
            inserted += 1

            # Insert daily_ebmc_attendance if last mc matches dept/desig
            new_daily_atten_id = ins_res.lastrowid
            eb_id_val  = m.get("eb_id")
            curr_dept  = m.get("dept_id")
            curr_desig = m.get("desig_id")
            if new_daily_atten_id and eb_id_val and curr_dept and curr_desig:
                last_ebmc = db.execute(
                    FINAL_LAST_EBMC_SQL, {"eb_id": eb_id_val}
                ).fetchone()
                if (
                    last_ebmc is not None
                    and last_ebmc.dept_id  is not None
                    and last_ebmc.desig_id is not None
                    and int(last_ebmc.dept_id)  == int(curr_dept)
                    and int(last_ebmc.desig_id) == int(curr_desig)
                ):
                    db.execute(FINAL_INSERT_EBMC_SQL, {
                        "daily_atten_id": new_daily_atten_id,
                        "eb_id": eb_id_val,
                        "mc_id": last_ebmc.mc_id,
                    })
                    log.debug(
                        "Step 3 | ebmc inserted eb_id=%s mc_id=%s daily_atten_id=%s",
                        eb_id_val, last_ebmc.mc_id, new_daily_atten_id,
                    )

    db.execute(FINAL_MARK_PROCESSED_SQL, {"tran_date": tran_date})
    db.commit()

    result = {
        "inserted": inserted,
        "skipped": skipped,
        "deleted_existing": deleted_existing,
    }
    log.info("Step 3 | %s result: %s", tran_date, result)
    return result


# ── Last-sync lookup ─────────────────────────────────────────────────────────

_LAST_LOG_SQL = text(
    """
    SELECT bio_att_log_id, DATE(log_date) AS log_date
    FROM bio_attendance_table
    WHERE bio_att_log_id = (SELECT MAX(bio_att_log_id) FROM bio_attendance_table)
    LIMIT 1
    """
)

_ALL_PENDING_DATES_SQL = text(
    """
    SELECT DISTINCT DATE(log_date) AS log_date
    FROM bio_attendance_table
    WHERE log_date IS NOT NULL
    ORDER BY log_date
    """
)


def get_last_log_state(db: Session) -> tuple[int, date]:
    """Return (last_bio_att_log_id, log_date_of_that_record).

    Returns (0, first-day-of-current-month) if the table is empty.
    """
    row = db.execute(_LAST_LOG_SQL).fetchone()
    if row is None:
        fallback_date = date.today().replace(day=1)
        log.info("bio_attendance_table is empty — starting from %s", fallback_date)
        return 0, fallback_date
    log_id   = int(row.bio_att_log_id)
    log_date = row.log_date if isinstance(row.log_date, date) else row.log_date.date()
    return log_id, log_date


def get_all_pending_dates(db: Session) -> list[date]:
    """All distinct dates present in bio_attendance_table (for full reprocess)."""
    rows = db.execute(_ALL_PENDING_DATES_SQL).fetchall()
    result = []
    for r in rows:
        d = r.log_date if isinstance(r.log_date, date) else r.log_date.date()
        result.append(d)
    return result


# ── Main entry-point ─────────────────────────────────────────────────────────

def run(
    *,
    tenant: str,
    branch_id: int,
    company_id: int = 2,
    dry_run: bool = False,
    reprocess_all: bool = False,
) -> None:
    """Full sync + process pipeline."""
    log.info(
        "=== bio_att_scheduler START | tenant=%s branch=%d company_id=%d dry_run=%s ===",
        tenant, branch_id, company_id, dry_run,
    )

    db = make_session(tenant)
    try:
        # ── Step 1: get last sync state & fetch new records ──────────────────
        last_log_id, last_log_date = get_last_log_state(db)
        log.info("Last sync state: bio_att_log_id=%d  log_date=%s", last_log_id, last_log_date)

        inserted, new_dates = step1_etrack_data(
            db,
            last_log_id=last_log_id,
            last_log_date=last_log_date,
            company_id=company_id,
            dry_run=dry_run,
        )
        log.info("Step 1 complete: inserted=%d  new_dates=%d", inserted, len(new_dates))

        # ── Determine which dates to run steps 2 & 3 for ────────────────────
        if reprocess_all:
            dates_to_process = get_all_pending_dates(db)
            log.info("reprocess_all=True: %d date(s) in bio_attendance_table", len(dates_to_process))
        else:
            dates_to_process = sorted(new_dates)

        if not dates_to_process:
            log.info("No new dates to process — nothing more to do.")
            return

        # ── Steps 2 & 3 for each date ────────────────────────────────────────
        for d in dates_to_process:
            tran_date = d.isoformat() if isinstance(d, date) else str(d)
            log.info("─── Processing date %s ───────────────────────────────", tran_date)

            try:
                step2_etrack_process(
                    db,
                    tran_date=tran_date,
                    branch_id=branch_id,
                    dry_run=dry_run,
                )
            except Exception:
                log.error(
                    "Step 2 failed for %s — skipping final process for this date.\n%s",
                    tran_date, traceback.format_exc(),
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

            try:
                step3_final_process(
                    db,
                    tran_date=tran_date,
                    branch_id=branch_id,
                    dry_run=dry_run,
                )
            except Exception:
                log.error(
                    "Step 3 failed for %s.\n%s",
                    tran_date, traceback.format_exc(),
                )
                try:
                    db.rollback()
                except Exception:
                    pass

    finally:
        try:
            db.close()
        except Exception:
            pass

    log.info("=== bio_att_scheduler DONE ===")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bio-attendance scheduled sync + process pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--tenant",     required=True, help="MySQL tenant/subdomain DB name (e.g. dev3)")
    p.add_argument("--branch",     required=True, type=int, help="branch_id for daily_attendance")
    p.add_argument("--company_id", default=2,     type=int, help="Etrack CompanyId (default: 2)")
    p.add_argument("--dry-run",    action="store_true",     help="Fetch only, no MySQL writes")
    p.add_argument(
        "--reprocess-all",
        action="store_true",
        help="Run steps 2+3 for ALL dates in bio_attendance_table (not just new ones)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    run(
        tenant=args.tenant,
        branch_id=args.branch,
        company_id=args.company_id,
        dry_run=args.dry_run,
        reprocess_all=args.reprocess_all,
    )


if __name__ == "__main__":
    main()
