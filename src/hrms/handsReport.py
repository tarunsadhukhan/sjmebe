"""
HRMS Hands Report endpoint.

Renders the SJM "Hands Report" grid from the `vw_hands_report` view: one row
per (tran_date, branch, designation), with machine count (M/H) and actual
hands (SUM(working_hours)/8) pivoted across Shift {A, B1, B2, C} x Shed
{Old, New}. See dbqueries/migrations/create_vw_hands_report.sql.

GET /hands_report?co_id=&branch_id=&tran_date=
    branch_id : comma-separated ints (from sidebar), optional
    tran_date : YYYY-MM-DD; if omitted, the latest date with data is used.

Response:
    {
      "tran_date": "2026-06-23",
      "data": [ { dept_desc, particular, mh_a_os, hands_a_os, ... total_hands }, ... ]
    }
Rows are ordered by section (dept_order) then machine order then particular.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()

# Measure columns returned to the FE, in display order.
_MEASURES = [
    "mh_a_os", "hands_a_os", "mh_a_ns", "hands_a_ns",
    "mh_b1_os", "hands_b1_os", "mh_b1_ns", "hands_b1_ns",
    "mh_b2_os", "hands_b2_os", "mh_b2_ns", "hands_b2_ns",
    "mh_c_os", "hands_c_os", "mh_c_ns", "hands_c_ns",
    "total_hands",
]


def _parse_branch_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for tok in str(raw).split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid branch_id: {tok}")
    return out


@router.get("/hands_report")
async def hands_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))
        params: dict = {}
        branch_clause = ""
        if branch_ids:
            placeholders = ", ".join(f":b{i}" for i in range(len(branch_ids)))
            branch_clause = f" AND branch_id IN ({placeholders})"
            for i, b in enumerate(branch_ids):
                params[f"b{i}"] = b

        tran_date = (request.query_params.get("tran_date") or "").strip()
        if not tran_date:
            row = db.execute(
                text(f"SELECT MAX(tran_date) FROM vw_hands_report WHERE 1=1{branch_clause}"),
                params,
            ).fetchone()
            tran_date = row[0].isoformat() if row and row[0] else date.today().isoformat()
        params["d"] = tran_date

        sql = f"""
            SELECT dept_desc, dept_code, particular, desig_code, {", ".join(_MEASURES)}
            FROM vw_hands_report
            WHERE tran_date = :d{branch_clause}
            ORDER BY CAST(dept_code AS UNSIGNED),
                     desig_code IS NULL, CAST(desig_code AS UNSIGNED), particular
        """
        rows = db.execute(text(sql), params).fetchall()

        data = []
        for r in rows:
            m = dict(r._mapping)
            for k in _MEASURES:
                m[k] = float(m[k]) if m[k] is not None else 0.0
            data.append(m)

        return {"tran_date": tran_date, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_STD_MEASURES = ["act_a", "std_a", "act_b", "std_b", "act_c", "std_c"]


@router.get("/hands_std_report")
async def hands_std_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Actual-vs-Std hands grid from vw_hands_std_report (Shift A/B/C x act/std per designation)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))
        params: dict = {}
        branch_clause = ""
        if branch_ids:
            placeholders = ", ".join(f":b{i}" for i in range(len(branch_ids)))
            branch_clause = f" AND branch_id IN ({placeholders})"
            for i, b in enumerate(branch_ids):
                params[f"b{i}"] = b

        tran_date = (request.query_params.get("tran_date") or "").strip()
        if not tran_date:
            row = db.execute(
                text(f"SELECT MAX(tran_date) FROM vw_hands_std_report WHERE 1=1{branch_clause}"),
                params,
            ).fetchone()
            tran_date = row[0].isoformat() if row and row[0] else date.today().isoformat()
        params["d"] = tran_date

        sql = f"""
            SELECT dept_desc, dept_code, particular, desig_code, {", ".join(_STD_MEASURES)}
            FROM vw_hands_std_report
            WHERE tran_date = :d{branch_clause}
            ORDER BY CAST(dept_code AS UNSIGNED),
                     desig_code IS NULL, CAST(desig_code AS UNSIGNED), particular
        """
        rows = db.execute(text(sql), params).fetchall()
        data = []
        for r in rows:
            m = dict(r._mapping)
            for k in _STD_MEASURES:
                m[k] = float(m[k]) if m[k] is not None else 0.0
            data.append(m)

        return {"tran_date": tran_date, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
