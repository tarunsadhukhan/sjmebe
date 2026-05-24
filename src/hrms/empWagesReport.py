"""
HRMS Employee Wages Report endpoints.

Pivoted wages report driven by `daily_attendance` and `employee_rate_table`.

For each (employee, day) the wage is computed as:

    wages = (rate / 8) * working_hours

where `rate` is the most recent `employee_rate_table.rate` for the employee
whose `rate_date` is <= the attendance date (i.e. rate_date is the
effective-from date — the rate stays in force until a newer rate_date
appears).

Three views (modes), all driven from `daily_attendance` joined with
`employee_rate_table`:

  - daily   : one column per calendar date in [from_date, to_date].
              Cell value = SUM(wages_per_row) for that day.
  - fnwise  : one column per fortnight period from `fne_master` whose range
              overlaps [from_date, to_date]. Cell value = SUM(wages).
  - monthly : one column per calendar month in [from_date, to_date]
              (e.g. "Apr'26"). Cell value = SUM(wages).

Filters: from_date, to_date (required), dept_id (optional),
less_than (optional — exclude employees whose total attended days >= N;
0 disables the filter).

Response shape mirrors empAttendanceReport:
    {
      "columns": [{"key": "...", "label": "..."}, ...],
      "data": [
        {
          "emp_code": "0003",
          "emp_name": "NABCD",
          "department": "Bailing",
          "values": {<key>: <number>, ...},
          "total": <number>
        },
        ...
      ]
    }
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── Helpers (copied/reused from empAttendanceReport) ───────────────


def _parse_branch_ids(value: str | None) -> list[int]:
    if not value:
        return []
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _parse_date(value: str | None, label: str) -> date:
    if not value:
        raise HTTPException(status_code=400, detail=f"{label} is required")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {label}: expected YYYY-MM-DD, got {value!r}",
        )


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    last = (end.year, end.month)
    while (y, m) <= last:
        yield y, m
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1


_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _build_columns(mode: str, from_date: date, to_date: date, fn_periods: list[dict]):
    cols: list[dict] = []
    buckets: list[tuple[str, date, date]] = []

    if mode == "daily":
        for d in _daterange(from_date, to_date):
            key = d.isoformat()
            label = d.strftime("%d/%m")
            cols.append({"key": key, "label": label})
            buckets.append((key, d, d))

    elif mode == "fnwise":
        for p in fn_periods:
            ps = p["from_date"]
            pe = p["to_date"]
            s = max(ps, from_date)
            e = min(pe, to_date)
            if s > e:
                continue
            key = f"fn_{p['fne_id']}"
            cols.append({"key": key, "label": p["fne_name"]})
            buckets.append((key, s, e))

    elif mode == "monthly":
        for y, m in _month_iter(from_date, to_date):
            month_start = date(y, m, 1)
            if m == 12:
                month_end = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(y, m + 1, 1) - timedelta(days=1)
            s = max(month_start, from_date)
            e = min(month_end, to_date)
            key = f"{y:04d}-{m:02d}"
            label = f"{_MONTH_NAMES[m - 1]}'{str(y)[-2:]}"
            cols.append({"key": key, "label": label})
            buckets.append((key, s, e))

    else:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    return cols, buckets


# ─── SQL ────────────────────────────────────────────────────────────

from src.hrms.query import (
    get_emp_attendance_dept_list,
    get_emp_attendance_fne_list,
    get_emp_wages_report,
)

_WAGES_SQL = get_emp_wages_report()
_FNE_LIST_SQL = get_emp_attendance_fne_list()
_DEPT_LIST_SQL = get_emp_attendance_dept_list()


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/emp_wages_setup")
async def emp_wages_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown data for the wages report filter popup."""
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")

    branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

    try:
        try:
            depts = [
                dict(r._mapping)
                for r in db.execute(
                    _DEPT_LIST_SQL,
                    {
                        "branch_count": len(branch_ids),
                        "branch_ids": branch_ids or [0],
                    },
                ).fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load departments: %s", exc)
            depts = []

        try:
            fnes = [
                dict(r._mapping)
                for r in db.execute(
                    _FNE_LIST_SQL, {"from_date": None, "to_date": None}
                ).fetchall()
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load fne_master: %s", exc)
            fnes = []

        return {"departments": depts, "fne_periods": fnes}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("emp_wages_setup failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/emp_wages_report")
async def emp_wages_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Pivoted wages report. Mode = daily | fnwise | monthly."""
    qp = request.query_params

    co_id = qp.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")

    mode = (qp.get("mode") or "daily").lower()
    if mode not in {"daily", "fnwise", "monthly"}:
        raise HTTPException(
            status_code=400,
            detail="mode must be one of: daily, fnwise, monthly",
        )

    from_date = _parse_date(qp.get("from_date"), "from_date")
    to_date = _parse_date(qp.get("to_date"), "to_date")
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    dept_id_raw = qp.get("dept_id")
    try:
        dept_id = int(dept_id_raw) if dept_id_raw not in (None, "", "0") else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dept_id")

    less_than_raw = qp.get("less_than")
    try:
        less_than = int(less_than_raw) if less_than_raw not in (None, "") else 0
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid less_than")

    branch_ids = _parse_branch_ids(qp.get("branch_id"))
    if not branch_ids:
        raise HTTPException(status_code=400, detail="At least one branch_id is required")

    scope = (qp.get("scope") or "all").lower()
    if scope not in {"all", "working"}:
        scope = "all"

    att_type_raw = (qp.get("att_type") or "all").lower()
    if att_type_raw == "regular":
        att_type: str | None = "P"
    elif att_type_raw == "ot":
        att_type = "O"
    else:
        att_type = None

    try:
        # Fetch FN periods if needed for fnwise mode.
        fn_periods: list[dict] = []
        if mode == "fnwise":
            try:
                fn_rows = db.execute(
                    _FNE_LIST_SQL, {"from_date": from_date, "to_date": to_date}
                ).fetchall()
                fn_periods = [dict(r._mapping) for r in fn_rows]
            except Exception as exc:  # noqa: BLE001
                logger.warning("fne_master not available: %s", exc)
                fn_periods = []

        columns, buckets = _build_columns(mode, from_date, to_date, fn_periods)

        try:
            rows = db.execute(
                _WAGES_SQL,
                {
                    "from_date": from_date,
                    "to_date": to_date,
                    "dept_id": dept_id,
                    "branch_ids": branch_ids,
                    "att_type": att_type,
                    "scope": scope,
                    "less_than": less_than,
                },
            ).fetchall()
            logger.info(
                "emp_wages_report: %d rows for %s..%s branches=%s dept=%s att_type=%s scope=%s",
                len(rows), from_date, to_date, branch_ids, dept_id, att_type, scope,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("emp_wages_report query failed: %s", exc)
            rows = []

        # Pre-index buckets by date for O(1) lookup.
        if mode == "daily":
            date_to_key: dict[date, str] = {b[1]: b[0] for b in buckets}
        else:
            date_to_key = {}
            for key, s, e in buckets:
                d = s
                while d <= e:
                    date_to_key[d] = key
                    d += timedelta(days=1)

        # Aggregate wages per (eb_id, bucket key).
        emp_meta: dict[int, dict] = {}
        emp_totals_wages: dict[int, dict[str, float]] = {}
        emp_sub_dept_code: dict[int, str] = {}

        for r in rows:
            m = r._mapping
            eb_id = m["eb_id"]
            if eb_id not in emp_meta:
                emp_meta[eb_id] = {
                    "emp_code": m["emp_code"] or "",
                    "emp_name": m["emp_name"] or "",
                    "status": (m["status_name"] if m["status_name"] is not None else "") or "",
                    "department": (m["sub_dept_name"] if m["sub_dept_name"] is not None else "") or "",
                }
                emp_totals_wages[eb_id] = {}
                emp_sub_dept_code[eb_id] = (
                    m["sub_dept_code"] if m["sub_dept_code"] is not None else ""
                ) or ""

            att_date = m["attendance_date"]
            if att_date is None:
                continue
            if isinstance(att_date, datetime):
                att_date = att_date.date()
            key = date_to_key.get(att_date)
            if key is None:
                continue
            hrs = float(m["working_hours"] or 0)
            rate = float(m["rate"] or 0)
            wages = (rate / 8.0) * hrs
            emp_totals_wages[eb_id][key] = (
                emp_totals_wages[eb_id].get(key, 0.0) + wages
            )

        # Build output rows. All buckets show wage amounts (rounded to 2 dp).
        out: list[dict] = []
        for eb_id, meta in emp_meta.items():
            bucket_wages = emp_totals_wages[eb_id]
            values: dict[str, float] = {}
            total = 0.0
            for col in columns:
                k = col["key"]
                w = bucket_wages.get(k, 0.0)
                val = round(w, 2)
                values[k] = val
                total += val

            out.append(
                (
                    emp_sub_dept_code.get(eb_id, ""),
                    {
                        **meta,
                        "values": values,
                        "total": round(total, 2),
                    },
                )
            )

        out.sort(key=lambda x: (x[0], x[1]["emp_code"]))
        final_out = [o[1] for o in out]

        return {"columns": columns, "data": final_out}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("emp_wages_report failed")
        raise HTTPException(status_code=500, detail=str(e))
