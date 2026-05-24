"""
HRMS Daily Machine Entry endpoints.

Provides CRUD for tbl_daily_summ_mechine_data and a lookup against
mechine_code_master for validating mc_code.

Inputs per row: tran_date, mc_code (validated), shift_a, shift_b, shift_c.
total_mc is derived = shift_a + shift_b + shift_c.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()


# ─── SQL ────────────────────────────────────────────────────────────


def _list_query(branch_filter_sql: str = ""):
    return text(f"""
        SELECT
            d.daily_sum_mc_id,
            d.tran_date,
            d.mc_code_id,
            m.mc_code,
            m.Mechine_type_name AS mc_name,
            d.shift_a,
            d.shift_b,
            d.shift_c,
            (COALESCE(d.shift_a,0) + COALESCE(d.shift_b,0) + COALESCE(d.shift_c,0)) AS total_mc,
            m.company_id,
            d.branch_id,
            d.is_active,
            d.created_on
        FROM tbl_daily_summ_mechine_data d
        LEFT JOIN mechine_code_master m ON m.mc_code_id = d.mc_code_id
        WHERE COALESCE(d.is_active, 1) = 1
          {branch_filter_sql}
          AND (:search IS NULL
               OR m.mc_code LIKE :search
               OR m.Mechine_type_name LIKE :search
               OR DATE_FORMAT(d.tran_date, '%Y-%m-%d') LIKE :search)
        ORDER BY d.tran_date DESC, d.daily_sum_mc_id DESC
    """)


def _by_id_query():
    return text("""
        SELECT
            d.daily_sum_mc_id,
            d.tran_date,
            d.mc_code_id,
            m.mc_code,
            m.Mechine_type_name AS mc_name,
            d.shift_a,
            d.shift_b,
            d.shift_c,
            (COALESCE(d.shift_a,0) + COALESCE(d.shift_b,0) + COALESCE(d.shift_c,0)) AS total_mc,
            m.company_id,
            d.branch_id,
            d.is_active
        FROM tbl_daily_summ_mechine_data d
        LEFT JOIN mechine_code_master m ON m.mc_code_id = d.mc_code_id
        WHERE d.daily_sum_mc_id = :daily_sum_mc_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/daily_machine_lookup_mc")
async def daily_machine_lookup_mc(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Validate an mc_code against mechine_code_master and return its id + name."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        mc_code = (request.query_params.get("mc_code") or "").strip()
        if not mc_code:
            raise HTTPException(status_code=400, detail="mc_code is required")

        row = db.execute(
            text("""
                SELECT mc_code_id, mc_code, Mechine_type_name AS mc_name,
                       company_id, branch_id
                FROM mechine_code_master
                WHERE mc_code = :mc_code
                  AND COALESCE(is_active, 1) = 1
                LIMIT 1
            """),
            {"mc_code": mc_code},
        ).fetchone()

        if not row:
            return {"found": False, "data": None}
        payload = dict(row._mapping)
        payload["machine_type_id"] = _get_mc_machine_type_id(db, int(row.mc_code_id))
        return {"found": True, "data": payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_daily_machine_table")
async def get_daily_machine_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of daily machine entries."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        # Optional branch filter (comma-separated list of ids)
        branch_raw = request.query_params.get("branch_id")
        branch_ids: list[int] = []
        if branch_raw:
            for tok in str(branch_raw).split(","):
                tok = tok.strip()
                if tok:
                    try:
                        branch_ids.append(int(tok))
                    except ValueError:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid branch_id: {tok}",
                        )

        params: dict = {"company_id": int(co_id), "search": search_param}
        branch_filter_sql = ""
        if branch_ids:
            placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
            branch_filter_sql = f"AND d.branch_id IN ({placeholders})"
            for i, bid in enumerate(branch_ids):
                params[f"b{i}"] = bid
        print("DEBUG: branch_filter_sql =", branch_filter_sql)
        print("DEBUG: params =", params)    
        result = db.execute(
            _list_query(branch_filter_sql),
            params,
        ).fetchall()

        all_data = [dict(r._mapping) for r in result]
        total = len(all_data)
        start = (page - 1) * limit
        return {
            "data": all_data[start : start + limit],
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_daily_machine_by_id/{daily_sum_mc_id}")
async def get_daily_machine_by_id(
    daily_sum_mc_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single daily machine entry by id."""
    try:
        row = db.execute(
            _by_id_query(), {"daily_sum_mc_id": daily_sum_mc_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Daily machine entry not found")
        payload = dict(row._mapping)
        payload["machine_type_id"] = _get_mc_machine_type_id(db, int(row.mc_code_id))
        return {"data": payload}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _parse_decimal(value, field: str):
    """Return float for shift inputs; allow None / empty."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be numeric")


def _resolve_mc_code_id(db: Session, body: dict) -> tuple[int, int | None, int | None]:
    """Return (mc_code_id, company_id, branch_id) by validating mc_code."""
    mc_code_id = body.get("mc_code_id")
    if mc_code_id:
        row = db.execute(
            text("""
                SELECT mc_code_id, company_id, branch_id
                FROM mechine_code_master
                WHERE mc_code_id = :mc_code_id
                  AND COALESCE(is_active, 1) = 1
                LIMIT 1
            """),
            {"mc_code_id": int(mc_code_id)},
        ).fetchone()
    else:
        mc_code = (body.get("mc_code") or "").strip()
        if not mc_code:
            raise HTTPException(status_code=400, detail="mc_code is required")
        row = db.execute(
            text("""
                SELECT mc_code_id, company_id, branch_id
                FROM mechine_code_master
                WHERE mc_code = :mc_code
                  AND COALESCE(is_active, 1) = 1
                LIMIT 1
            """),
            {"mc_code": mc_code},
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=400, detail="mc_code not found in machine master"
        )
    return int(row.mc_code_id), row.company_id, row.branch_id


def _validate_machine_type_id(db: Session, body: dict) -> int | None:
    """Validate optional machine_type_id against machine_type_mst.

    Returns int machine_type_id when provided, else None.
    """
    raw_id = body.get("machine_type_id")
    if raw_id is None or raw_id == "":
        return None
    try:
        machine_type_id = int(raw_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid machine_type_id")

    row = db.execute(
        text(
            """
            SELECT machine_type_id
            FROM machine_type_mst
            WHERE machine_type_id = :machine_type_id
              AND COALESCE(active, 1) = 1
            LIMIT 1
            """
        ),
        {"machine_type_id": machine_type_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="machine_type_id not found")
    return machine_type_id


def _validate_mc_type_consistency(db: Session, mc_code_id: int, machine_type_id: int | None) -> None:
    """If both IDs are provided, verify mc_code_id belongs to the selected machine type.

    Some deployments store type link as `machine_type_id`, others as `mechine_type_id`.
    We detect whichever column exists before validating.
    """
    if machine_type_id is None:
        return

    col_row = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'mechine_code_master'
              AND COLUMN_NAME IN ('machine_type_id', 'mechine_type_id')
            LIMIT 1
            """
        )
    ).fetchone()
    if not col_row:
        return

    type_col = str(col_row[0])
    row = db.execute(
        text(
            f"""
            SELECT mc_code_id
            FROM mechine_code_master
            WHERE mc_code_id = :mc_code_id
              AND {type_col} = :machine_type_id
              AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """
        ),
        {"mc_code_id": mc_code_id, "machine_type_id": machine_type_id},
    ).fetchone()
    if not row:
        raise HTTPException(
            status_code=400,
            detail="Selected machine_type_id does not match machine code",
        )


def _get_mc_machine_type_id(db: Session, mc_code_id: int) -> int | None:
    """Return machine type id for mc_code_id when type column exists."""
    col_row = db.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'mechine_code_master'
              AND COLUMN_NAME IN ('machine_type_id', 'mechine_type_id')
            LIMIT 1
            """
        )
    ).fetchone()
    if not col_row:
        return None

    type_col = str(col_row[0])
    row = db.execute(
        text(
            f"""
            SELECT {type_col} AS machine_type_id
            FROM mechine_code_master
            WHERE mc_code_id = :mc_code_id
              AND COALESCE(is_active, 1) = 1
            LIMIT 1
            """
        ),
        {"mc_code_id": mc_code_id},
    ).fetchone()
    if not row or row.machine_type_id is None:
        return None
    return int(row.machine_type_id)


@router.post("/daily_machine_create")
async def daily_machine_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Insert a daily machine entry."""
    try:
        body = await request.json()

        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")

        machine_type_id = _validate_machine_type_id(db, body)
        mc_code_id, mc_company_id, mc_branch_id = _resolve_mc_code_id(db, body)
        _validate_mc_type_consistency(db, mc_code_id, machine_type_id)

        shift_a = _parse_decimal(body.get("shift_a"), "shift_a") or 0
        shift_b = _parse_decimal(body.get("shift_b"), "shift_b") or 0
        shift_c = _parse_decimal(body.get("shift_c"), "shift_c") or 0

        # Optional duplicate-guard: same date + mc_code_id already exists
        dup = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM tbl_daily_summ_mechine_data
                WHERE tran_date = :tran_date
                  AND mc_code_id = :mc_code_id
                  AND COALESCE(is_active, 1) = 1
            """),
            {"tran_date": tran_date, "mc_code_id": mc_code_id},
        ).fetchone()
        if dup and int(dup.cnt or 0) > 0:
            raise HTTPException(
                status_code=400,
                detail="An entry already exists for this date and machine code",
            )

        branch_id = body.get("branch_id") or mc_branch_id

        db.execute(
            text("""
                INSERT INTO tbl_daily_summ_mechine_data
                    (tran_date, mc_code_id, shift_a, shift_b, shift_c,
                     branch_id, is_active, created_on)
                VALUES
                    (:tran_date, :mc_code_id, :shift_a, :shift_b, :shift_c,
                     :branch_id, 1, :created_on)
            """),
            {
                "tran_date": tran_date,
                "mc_code_id": mc_code_id,
                "shift_a": shift_a,
                "shift_b": shift_b,
                "shift_c": shift_c,
                "branch_id": int(branch_id) if branch_id is not None else None,
                "created_on": datetime.now(),
            },
        )
        db.commit()
        _ = mc_company_id  # unused but kept for symmetry

        return {"message": "Daily machine entry created successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/daily_machine_edit/{daily_sum_mc_id}")
async def daily_machine_edit(
    daily_sum_mc_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a daily machine entry."""
    try:
        body = await request.json()

        existing = db.execute(
            text("""
                SELECT daily_sum_mc_id, branch_id
                FROM tbl_daily_summ_mechine_data
                WHERE daily_sum_mc_id = :id
            """),
            {"id": daily_sum_mc_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Daily machine entry not found")

        tran_date = body.get("tran_date")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")

        machine_type_id = _validate_machine_type_id(db, body)
        mc_code_id, _mc_co, mc_branch_id = _resolve_mc_code_id(db, body)
        _validate_mc_type_consistency(db, mc_code_id, machine_type_id)

        shift_a = _parse_decimal(body.get("shift_a"), "shift_a") or 0
        shift_b = _parse_decimal(body.get("shift_b"), "shift_b") or 0
        shift_c = _parse_decimal(body.get("shift_c"), "shift_c") or 0

        # Duplicate-guard excluding self
        dup = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM tbl_daily_summ_mechine_data
                WHERE tran_date = :tran_date
                  AND mc_code_id = :mc_code_id
                  AND daily_sum_mc_id != :id
                  AND COALESCE(is_active, 1) = 1
            """),
            {
                "tran_date": tran_date,
                "mc_code_id": mc_code_id,
                "id": daily_sum_mc_id,
            },
        ).fetchone()
        if dup and int(dup.cnt or 0) > 0:
            raise HTTPException(
                status_code=400,
                detail="An entry already exists for this date and machine code",
            )

        branch_id = body.get("branch_id") or mc_branch_id

        db.execute(
            text("""
                UPDATE tbl_daily_summ_mechine_data
                SET tran_date  = :tran_date,
                    mc_code_id = :mc_code_id,
                    shift_a    = :shift_a,
                    shift_b    = :shift_b,
                    shift_c    = :shift_c,
                    branch_id  = COALESCE(:branch_id, branch_id)
                WHERE daily_sum_mc_id = :id
            """),
            {
                "tran_date": tran_date,
                "mc_code_id": mc_code_id,
                "shift_a": shift_a,
                "shift_b": shift_b,
                "shift_c": shift_c,
                "branch_id": int(branch_id) if branch_id is not None else None,
                "id": daily_sum_mc_id,
            },
        )
        db.commit()
        return {
            "message": "Daily machine entry updated successfully",
            "daily_sum_mc_id": daily_sum_mc_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/daily_machine_final_process")
async def daily_machine_final_process(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Finalize daily machine entries for a given date / branch.

    Steps:
      1. Delete previously-finalised rows in tbl_daily_summ_mechine_data
         where tran_date = :tran_date AND updated = 'Y'
         (optionally scoped by branch_id).
      2. Re-insert finalised rows aggregated from
         daily_ebmc_attendance + daily_attendance + machine_mst +
         mechine_code_master for that date / branch.
    """
    try:
        body = await request.json()
        tran_date = body.get("tran_date")
        branch_id = body.get("branch_id")
        if not tran_date:
            raise HTTPException(status_code=400, detail="tran_date is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        try:
            branch_id_int = int(branch_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        # 1) Delete previously finalised rows for this date + branch
        del_result = db.execute(
            text("""
                DELETE FROM tbl_daily_summ_mechine_data
                WHERE tran_date = :tran_date
                  AND updated = 'Y'
                  AND branch_id = :branch_id
            """),
            {"tran_date": tran_date, "branch_id": branch_id_int},
        )

        # 2) Re-insert aggregated rows
        ins_result = db.execute(
            text("""
                INSERT INTO tbl_daily_summ_mechine_data
                    (tran_date, shift_a, shift_b, shift_c, updated,
                     branch_id, mc_code_id, is_active)
                SELECT
                    attendance_date,
                    shift_a,
                    shift_b,
                    shift_c,
                    'Y' AS upd,
                    :branch_id AS branchid,
                    mc_code_id,
                    1 AS act
                FROM (
                    SELECT
                        da.attendance_date,
                        mm.machine_type_id,
                        mcm.mc_code_id,
                        COUNT(DISTINCT CASE WHEN da.spell = 'A' THEN dea.mc_id END) AS shift_a,
                        COUNT(DISTINCT CASE WHEN da.spell = 'B' THEN dea.mc_id END) AS shift_b,
                        COUNT(DISTINCT CASE WHEN da.spell = 'C' THEN dea.mc_id END) AS shift_c
                    FROM daily_ebmc_attendance dea
                    LEFT JOIN daily_attendance da
                        ON da.daily_atten_id = dea.daily_atten_id
                    LEFT JOIN machine_mst mm
                        ON dea.mc_id = mm.machine_id
                    LEFT JOIN mechine_code_master mcm
                        ON mm.machine_type_id = mcm.machine_type
                    WHERE dea.is_active = 1
                      AND da.is_active = 1
                      AND da.branch_id = :branch_id
                      AND da.attendance_date = :tran_date
                    GROUP BY
                        da.attendance_date,
                        mm.machine_type_id,
                        mcm.mc_code_id
                ) dmc
            """),
            {"tran_date": tran_date, "branch_id": branch_id_int},
        )

        db.commit()
        return {
            "message": (
                f"Final process completed for {tran_date} (branch {branch_id_int}): "
                f"deleted {del_result.rowcount or 0}, inserted {ins_result.rowcount or 0}"
            ),
            "deleted": del_result.rowcount or 0,
            "inserted": ins_result.rowcount or 0,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
