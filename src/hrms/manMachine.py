"""
HRMS Daily Man-Machine endpoints.

Reads from the `vw_man_machine` view in the tenant DB.

Tabs:
    - dept_summary : GROUP BY tran_date, dept_desc; columns:
                     date, dept_desc, total_hands, total_target_hands, diff_hands
    - summary      : designation/spell-level rollup (auto-derived columns)
    - details      : raw rows from the view (auto-derived columns)
"""

from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()

VALID_TABS = {"dept_summary", "summary", "details"}


def _normalize_row(row_mapping) -> dict:
    d = dict(row_mapping)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(v, date):
            d[k] = v.isoformat()
    return d


def _infer_columns(sample_row: dict) -> list[dict]:
    return [
        {"field": k, "headerName": k.replace("_", " ").strip().title()}
        for k in sample_row.keys()
    ]


def _list_view_columns(db: Session) -> list[str]:
    rows = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'vw_man_machine'
            ORDER BY ORDINAL_POSITION
            """
        )
    ).fetchall()
    return [r[0] for r in rows]


@router.get("/man_machine_list")
async def man_machine_list(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated listing from `vw_man_machine` for a given tab."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        tab = (request.query_params.get("tab") or "details").strip().lower()
        if tab not in VALID_TABS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tab '{tab}'. Must be one of {sorted(VALID_TABS)}",
            )

        try:
            page = int(request.query_params.get("page", 1))
            limit = int(request.query_params.get("limit", 10))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid page/limit")

        search = (request.query_params.get("search") or "").strip()
        branch_raw = (request.query_params.get("branch_id") or "").strip()
        branch_ids: list[int] = []
        if branch_raw:
            try:
                branch_ids = [int(b) for b in branch_raw.split(",") if b.strip()]
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid branch_id")

        offset = max(page - 1, 0) * limit
        params: dict = {"limit": limit, "offset": offset}
        for i, b in enumerate(branch_ids):
            params[f"b{i}"] = b
        branch_clause = (
            f"branch_id IN ({', '.join(f':b{i}' for i in range(len(branch_ids)))})"
            if branch_ids else ""
        )

        # ── Dept-wise summary tab — hard-coded per spec ─────────────────────
        # vw_man_machine actual columns: dept_desc, attendance_date,
        # hands_a/b/c (actual), thands_a/b/c (target), extra_short_a/b/c.
        if tab == "dept_summary":
            conds: list[str] = []
            if branch_clause:
                conds.append(branch_clause)
            if search:
                conds.append(
                    "(dept_desc LIKE :s OR DATE_FORMAT(attendance_date, '%Y-%m-%d') LIKE :s)"
                )
                params["s"] = f"%{search}%"
            where = (" WHERE " + " AND ".join(conds)) if conds else ""

            sql = f"""
                SELECT
                    dept_desc                                            AS dept_desc,
                    attendance_date                                      AS tran_date,
                    SUM(COALESCE(hands_a, 0))                            AS shift_a,
                    SUM(COALESCE(hands_b, 0))                            AS shift_b,
                    SUM(COALESCE(hands_c, 0))                            AS shift_c,
                    SUM(COALESCE(hands_a, 0) + COALESCE(hands_b, 0)
                        + COALESCE(hands_c, 0))                          AS total_hands,
                    SUM(COALESCE(thands_a, 0))                           AS thands_a,
                    SUM(COALESCE(thands_b, 0))                           AS thands_b,
                    SUM(COALESCE(thands_c, 0))                           AS thands_c,
                    SUM(COALESCE(thands_a, 0) + COALESCE(thands_b, 0)
                        + COALESCE(thands_c, 0))                         AS total_target,
                    SUM(COALESCE(extra_short_a, 0)
                        + COALESCE(extra_short_b, 0)
                        + COALESCE(extra_short_c, 0))                    AS total_excess_short
                FROM vw_man_machine
                {where}
                GROUP BY dept_desc, attendance_date
                ORDER BY attendance_date DESC, dept_desc
                LIMIT :limit OFFSET :offset
            """
            rows = db.execute(text(sql), params).fetchall()
            data = [_normalize_row(r._mapping) for r in rows]

            count_sql = (
                f"SELECT COUNT(*) AS cnt FROM ("
                f"SELECT 1 FROM vw_man_machine{where} "
                f"GROUP BY dept_desc, attendance_date"
                f") t"
            )
            total_row = db.execute(
                text(count_sql),
                {k: v for k, v in params.items() if k == "s" or k.startswith("b")},
            ).fetchone()
            total = int(total_row[0]) if total_row else 0

            columns = [
                {"field": "dept_desc", "headerName": "Department"},
                {"field": "tran_date", "headerName": "Date"},
                {"field": "shift_a", "headerName": "Shift A"},
                {"field": "shift_b", "headerName": "Shift B"},
                {"field": "shift_c", "headerName": "Shift C"},
                {"field": "total_hands", "headerName": "Total Hands"},
                {"field": "thands_a", "headerName": "T Hands A"},
                {"field": "thands_b", "headerName": "T Hands B"},
                {"field": "thands_c", "headerName": "T Hands C"},
                {"field": "total_target", "headerName": "Total Target"},
                {"field": "total_excess_short", "headerName": "Total Excess/Short"},
            ]
            return {"data": data, "total": total, "columns": columns}

        # ── Details tab — designation-level summary (FE renders 3-level tree) ──
        if tab == "details":
            conds: list[str] = []
            if branch_clause:
                conds.append(branch_clause)
            if search:
                conds.append(
                    "(dept_desc LIKE :s OR desig LIKE :s "
                    "OR DATE_FORMAT(attendance_date, '%Y-%m-%d') LIKE :s)"
                )
                params["s"] = f"%{search}%"
            where = (" WHERE " + " AND ".join(conds)) if conds else ""

            sql = f"""
                SELECT
                    dept_desc                                            AS dept_desc,
                    desig                                                AS desig,
                    attendance_date                                      AS tran_date,
                    SUM(COALESCE(hands_a, 0))                            AS shift_a,
                    SUM(COALESCE(hands_b, 0))                            AS shift_b,
                    SUM(COALESCE(hands_c, 0))                            AS shift_c,
                    SUM(COALESCE(hands_a, 0) + COALESCE(hands_b, 0)
                        + COALESCE(hands_c, 0))                          AS total_hands,
                    SUM(COALESCE(thands_a, 0))                           AS thands_a,
                    SUM(COALESCE(thands_b, 0))                           AS thands_b,
                    SUM(COALESCE(thands_c, 0))                           AS thands_c,
                    SUM(COALESCE(thands_a, 0) + COALESCE(thands_b, 0)
                        + COALESCE(thands_c, 0))                         AS total_target,
                    SUM(COALESCE(extra_short_a, 0)
                        + COALESCE(extra_short_b, 0)
                        + COALESCE(extra_short_c, 0))                    AS total_excess_short
                FROM vw_man_machine
                {where}
                GROUP BY dept_desc, desig, attendance_date
                ORDER BY attendance_date DESC, dept_desc, desig
                LIMIT :limit OFFSET :offset
            """
            rows = db.execute(text(sql), params).fetchall()
            data = [_normalize_row(r._mapping) for r in rows]

            count_sql = (
                f"SELECT COUNT(*) AS cnt FROM ("
                f"SELECT 1 FROM vw_man_machine{where} "
                f"GROUP BY dept_desc, desig, attendance_date"
                f") t"
            )
            total_row = db.execute(
                text(count_sql),
                {k: v for k, v in params.items() if k == "s" or k.startswith("b")},
            ).fetchone()
            total = int(total_row[0]) if total_row else 0

            columns = [
                {"field": "tran_date", "headerName": "Date"},
                {"field": "dept_desc", "headerName": "Department"},
                {"field": "desig", "headerName": "Designation"},
                {"field": "shift_a", "headerName": "Shift A"},
                {"field": "shift_b", "headerName": "Shift B"},
                {"field": "shift_c", "headerName": "Shift C"},
                {"field": "total_hands", "headerName": "Total Hands"},
                {"field": "thands_a", "headerName": "T Hands A"},
                {"field": "thands_b", "headerName": "T Hands B"},
                {"field": "thands_c", "headerName": "T Hands C"},
                {"field": "total_target", "headerName": "Total Target"},
                {"field": "total_excess_short", "headerName": "Total Excess/Short"},
            ]
            return {"data": data, "total": total, "columns": columns}

        # ── Summary tab — auto-derive from view columns ─────────────────────
        all_cols = _list_view_columns(db)
        if not all_cols:
            raise HTTPException(
                status_code=500,
                detail="View `vw_man_machine` not found in tenant DB.",
            )

        text_cols = [
            c for c in all_cols
            if c.lower() in {
                "department", "dept", "dept_desc", "designation", "spell",
                "shift", "tran_date", "attendance_date", "emp_code", "emp_name",
            }
        ]
        date_col = next(
            (c for c in all_cols if c.lower() in {"tran_date", "attendance_date"}),
            None,
        )

        if tab == "summary":
            group_cols = [
                c for c in all_cols
                if c.lower() in {
                    "tran_date", "attendance_date", "department", "dept", "dept_desc",
                    "designation", "spell", "shift", "branch_id",
                }
            ]
            num_cols = [c for c in all_cols if c not in group_cols]
            select_parts = [f"`{c}`" for c in group_cols] + [
                f"SUM(`{c}`) AS `{c}`"
                for c in num_cols if c.lower() not in {"is_active", "id"}
            ]
            base_select = f"SELECT {', '.join(select_parts) or '*'} FROM vw_man_machine"
            group_clause = (
                f" GROUP BY {', '.join(f'`{c}`' for c in group_cols)}"
                if group_cols else ""
            )
        else:  # details
            base_select = "SELECT * FROM vw_man_machine"
            group_clause = ""

        conds: list[str] = []
        if branch_clause and "branch_id" in [c.lower() for c in all_cols]:
            conds.append(branch_clause)
        if search and text_cols:
            ors = " OR ".join(f"`{c}` LIKE :s" for c in text_cols)
            conds.append(f"({ors})")
            params["s"] = f"%{search}%"
        where = (" WHERE " + " AND ".join(conds)) if conds else ""

        order_clause = f" ORDER BY `{date_col}` DESC" if date_col else ""

        sql = f"{base_select}{where}{group_clause}{order_clause} LIMIT :limit OFFSET :offset"
        rows = db.execute(text(sql), params).fetchall()
        data = [_normalize_row(r._mapping) for r in rows]

        if group_clause:
            count_sql = (
                f"SELECT COUNT(*) AS cnt FROM (SELECT 1 FROM vw_man_machine{where}{group_clause}) t"
            )
        else:
            count_sql = f"SELECT COUNT(*) AS cnt FROM vw_man_machine{where}"
        total_row = db.execute(
            text(count_sql),
            {k: v for k, v in params.items() if k == "s" or k.startswith("b")},
        ).fetchone()
        total = int(total_row[0]) if total_row else 0

        columns = (
            _infer_columns(data[0])
            if data
            else [{"field": c, "headerName": c.replace("_", " ").title()} for c in all_cols]
        )

        return {"data": data, "total": total, "columns": columns}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/man_machine_final_process")
async def man_machine_final_process(
    request: Request,
    response: Response,
    payload: dict = Body(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Trigger the daily man-machine final process for the given date/branch.

    Stub — replace with actual finalisation SQL once target tables/SP are confirmed.
    """
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        tran_date = (payload.get("tran_date") or "").strip()
        branch_id = payload.get("branch_id")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        try:
            branch_id = int(branch_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        return {
            "message": f"Daily man-machine final process triggered for {tran_date}.",
            "tran_date": tran_date,
            "branch_id": branch_id,
            "inserted": 0,
            "skipped": 0,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
