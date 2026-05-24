"""
HRMS Man-Machine Master endpoints.

Provides CRUD operations for the `mc_occu_link_mst` table which links a
machine (`mc_id` from `mechine_code_master`) to a designation (`desig_id`
from `designation_mst`) with optional `no_of_mcs` / `no_of_hands` values.

All listings/setups are scoped by `branch_id` (sourced from
`designation_mst.branch_id` for designations and from
`mechine_code_master.branch_id` for machines).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────


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


def _to_decimal(value, field: str):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid number for {field}")


def _to_int(value, field: str):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid integer for {field}")


def _validate_payload(body: dict) -> dict:
    desig_id = _to_int(body.get("desig_id"), "desig_id")
    if not desig_id:
        raise HTTPException(status_code=400, detail="desig_id is required")
    mc_id = _to_int(body.get("mc_id"), "mc_id")
    if not mc_id:
        raise HTTPException(status_code=400, detail="mc_id is required")
    return {
        "desig_id": desig_id,
        "mc_id": mc_id,
        "no_of_mcs": _to_decimal(body.get("no_of_mcs"), "no_of_mcs"),
        "no_of_hands": _to_decimal(body.get("no_of_hands"), "no_of_hands"),
    }


# ─── SQL ────────────────────────────────────────────────────────────


def _list_query(branch_filter_sql: str = ""):
    return text(f"""
        SELECT
            l.mc_occu_line_mst_id,
            l.mc_id,
            l.desig_id,
            l.no_of_mcs,
            l.no_of_hands,
            mc.mc_code            AS mc_code,
            mc.Mechine_type_name  AS mc_name,
            d.desig               AS designation_name,
            d.branch_id           AS branch_id,
            b.branch_name         AS branch_name
        FROM mc_occu_link_mst l
        LEFT JOIN mechine_code_master mc ON mc.mc_code_id     = l.mc_id
        LEFT JOIN designation_mst     d  ON d.designation_id  = l.desig_id
        LEFT JOIN branch_mst          b  ON b.branch_id       = d.branch_id
        WHERE COALESCE(l.active, 1) = 1
          {branch_filter_sql}
          AND (:search IS NULL
               OR d.desig    LIKE :search
               OR mc.mc_code LIKE :search
               OR mc.Mechine_type_name LIKE :search)
        ORDER BY l.mc_occu_line_mst_id DESC
    """)


def _by_id_query():
    return text("""
        SELECT
            l.mc_occu_line_mst_id,
            l.mc_id,
            l.desig_id,
            l.no_of_mcs,
            l.no_of_hands,
            mc.mc_code            AS mc_code,
            mc.Mechine_type_name  AS mc_name,
            d.desig               AS designation_name,
            d.branch_id           AS branch_id
        FROM mc_occu_link_mst l
        LEFT JOIN mechine_code_master mc ON mc.mc_code_id     = l.mc_id
        LEFT JOIN designation_mst     d  ON d.designation_id  = l.desig_id
        WHERE l.mc_occu_line_mst_id = :id
        LIMIT 1
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/man_machine_mst_setup")
async def man_machine_mst_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup endpoint returning machines & designations filtered by branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        if branch_ids:
            placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
            desig_sql = f"""
                SELECT designation_id, desig, branch_id, dept_id
                FROM designation_mst
                WHERE COALESCE(active, 1) = 1
                  AND branch_id IN ({placeholders})
                ORDER BY desig
            """
            mc_sql = f"""
                SELECT mc_code_id, mc_code, Mechine_type_name AS mc_name,
                       branch_id, machine_type
                FROM mechine_code_master
                WHERE COALESCE(is_active, 1) = 1
                  AND branch_id IN ({placeholders})
                ORDER BY mc_code
            """
            params = {f"b{i}": bid for i, bid in enumerate(branch_ids)}
        else:
            desig_sql = """
                SELECT designation_id, desig, branch_id, dept_id
                FROM designation_mst
                WHERE COALESCE(active, 1) = 1
                ORDER BY desig
            """
            mc_sql = """
                SELECT mc_code_id, mc_code, Mechine_type_name AS mc_name,
                       branch_id, machine_type
                FROM mechine_code_master
                WHERE COALESCE(is_active, 1) = 1
                ORDER BY mc_code
            """
            params = {}

        designations = db.execute(text(desig_sql), params).fetchall()
        machines = db.execute(text(mc_sql), params).fetchall()

        return {
            "designations": [dict(r._mapping) for r in designations],
            "machines": [dict(r._mapping) for r in machines],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_man_machine_mst_table")
async def get_man_machine_mst_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of mc_occu_link_mst rows (filtered by branch)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        params: dict = {"search": search_param}
        branch_filter_sql = ""
        if branch_ids:
            placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
            branch_filter_sql = f"AND d.branch_id IN ({placeholders})"
            for i, bid in enumerate(branch_ids):
                params[f"b{i}"] = bid

        result = db.execute(_list_query(branch_filter_sql), params).fetchall()

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


@router.get("/get_man_machine_mst_by_id/{record_id}")
async def get_man_machine_mst_by_id(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single mc_occu_link_mst row by id."""
    try:
        row = db.execute(_by_id_query(), {"id": record_id}).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/man_machine_mst_create")
async def man_machine_mst_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new mc_occu_link_mst row."""
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        data = _validate_payload(body)

        # Duplicate check: one active row per (mc_id, desig_id) pair
        dup = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM mc_occu_link_mst
                WHERE mc_id = :mc_id
                  AND desig_id = :desig_id
                  AND COALESCE(active, 1) = 1
            """),
            {"mc_id": data["mc_id"], "desig_id": data["desig_id"]},
        ).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A link already exists for this machine and designation",
            )

        result = db.execute(
            text("""
                INSERT INTO mc_occu_link_mst
                    (mc_id, desig_id, no_of_mcs, no_of_hands, active)
                VALUES
                    (:mc_id, :desig_id, :no_of_mcs, :no_of_hands, 1)
            """),
            data,
        )
        db.commit()
        return {
            "message": "Man-Machine link created successfully",
            "mc_occu_line_mst_id": result.lastrowid,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/man_machine_mst_edit/{record_id}")
async def man_machine_mst_edit(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing mc_occu_link_mst row."""
    try:
        body = await request.json()
        existing = db.execute(
            text("SELECT mc_occu_line_mst_id FROM mc_occu_link_mst WHERE mc_occu_line_mst_id = :id"),
            {"id": record_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Record not found")

        data = _validate_payload(body)

        # Duplicate check excluding self
        dup = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM mc_occu_link_mst
                WHERE mc_id = :mc_id
                  AND desig_id = :desig_id
                  AND mc_occu_line_mst_id <> :id
                  AND COALESCE(active, 1) = 1
            """),
            {"mc_id": data["mc_id"], "desig_id": data["desig_id"], "id": record_id},
        ).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A link already exists for this machine and designation",
            )

        params = dict(data)
        params["id"] = record_id
        db.execute(
            text("""
                UPDATE mc_occu_link_mst SET
                    mc_id       = :mc_id,
                    desig_id    = :desig_id,
                    no_of_mcs   = :no_of_mcs,
                    no_of_hands = :no_of_hands
                WHERE mc_occu_line_mst_id = :id
            """),
            params,
        )
        db.commit()
        return {"message": "Man-Machine link updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/man_machine_mst_delete/{record_id}")
async def man_machine_mst_delete(
    record_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a mc_occu_link_mst row."""
    try:
        row = db.execute(
            text("SELECT mc_occu_line_mst_id FROM mc_occu_link_mst WHERE mc_occu_line_mst_id = :id"),
            {"id": record_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Record not found")

        db.execute(
            text("UPDATE mc_occu_link_mst SET active = 0 WHERE mc_occu_line_mst_id = :id"),
            {"id": record_id},
        )
        db.commit()
        return {"message": "Man-Machine link deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
