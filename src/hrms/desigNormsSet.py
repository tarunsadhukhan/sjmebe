"""
HRMS Designation Norms Set API endpoints.

Provides CRUD operations for the `designation_norms_mst` table along with
the linked `mc_occu_link_mst` row (machine, no_of_mcs, no_of_hands) which
is only persisted when `fixed_variable = 'V'` (Variable).

All listings/setups are scoped by `branch_id` (sourced from
`designation_mst.branch_id` for designations and from
`mechine_code_master.branch_id` for the machine dropdown).
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
            n.desg_norms_mst_id,
            n.desig_id,
            d.desig          AS designation_name,
            d.branch_id,
            b.branch_name,
            n.direct_indirect,
            n.fixed_variable,
            n.shift_a,
            n.shift_b,
            n.shift_c,
            n.shift_g,
            n.re_calculate,
            n.mc_type,
            n.mc_code,
            n.round_off,
            n.norms,
            n.active,
            l.mc_occu_line_mst_id,
            l.mc_id,
            l.no_of_mcs,
            l.no_of_hands,
            mc.mc_code        AS link_mc_code,
            mc.Mechine_type_name AS link_mc_name
        FROM designation_norms_mst n
        LEFT JOIN designation_mst   d  ON d.designation_id = n.desig_id
        LEFT JOIN branch_mst        b  ON b.branch_id      = d.branch_id
        LEFT JOIN mc_occu_link_mst  l  ON l.desig_id       = n.desig_id
                                      AND COALESCE(l.active, 1) = 1
        LEFT JOIN mechine_code_master mc ON mc.mc_code_id  = l.mc_id
        WHERE COALESCE(n.active, 1) = 1
          {branch_filter_sql}
          AND (:search IS NULL
               OR d.desig         LIKE :search
               OR n.norms         LIKE :search
               OR n.mc_code       LIKE :search
               OR mc.mc_code      LIKE :search)
        ORDER BY n.desg_norms_mst_id DESC
    """)


def _by_id_query():
    return text("""
        SELECT
            n.desg_norms_mst_id,
            n.desig_id,
            d.desig          AS designation_name,
            d.branch_id,
            n.direct_indirect,
            n.fixed_variable,
            n.shift_a,
            n.shift_b,
            n.shift_c,
            n.shift_g,
            n.re_calculate,
            n.mc_type,
            n.mc_code,
            n.round_off,
            n.norms,
            n.active,
            l.mc_occu_line_mst_id,
            l.mc_id,
            l.no_of_mcs,
            l.no_of_hands,
            mc.mc_code        AS link_mc_code,
            mc.Mechine_type_name AS link_mc_name
        FROM designation_norms_mst n
        LEFT JOIN designation_mst   d  ON d.designation_id = n.desig_id
        LEFT JOIN mc_occu_link_mst  l  ON l.desig_id       = n.desig_id
                                      AND COALESCE(l.active, 1) = 1
        LEFT JOIN mechine_code_master mc ON mc.mc_code_id  = l.mc_id
        WHERE n.desg_norms_mst_id = :desg_norms_mst_id
        LIMIT 1
    """)


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


def _upsert_mc_occu_link(
    db: Session,
    desig_id: int,
    mc_id: int | None,
    no_of_mcs,
    no_of_hands,
):
    """Create or update the single active mc_occu_link_mst row for a designation.
    Soft-deactivates the existing row(s) and inserts a fresh one when machine
    data is provided; otherwise just deactivates existing row(s).
    """
    db.execute(
        text("""
            UPDATE mc_occu_link_mst
               SET active = 0
             WHERE desig_id = :desig_id
               AND COALESCE(active, 1) = 1
        """),
        {"desig_id": desig_id},
    )

    if mc_id is None:
        return

    db.execute(
        text("""
            INSERT INTO mc_occu_link_mst (mc_id, desig_id, no_of_mcs, no_of_hands, active)
            VALUES (:mc_id, :desig_id, :no_of_mcs, :no_of_hands, 1)
        """),
        {
            "mc_id": mc_id,
            "desig_id": desig_id,
            "no_of_mcs": no_of_mcs,
            "no_of_hands": no_of_hands,
        },
    )


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/desig_norms_setup")
async def desig_norms_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Setup endpoint returning designations & machines filtered by branch."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))

        # Designations filtered by branch
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


@router.get("/get_desig_norms_table")
async def get_desig_norms_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of designation norms (filtered by branch)."""
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


@router.get("/get_desig_norms_by_id/{desg_norms_mst_id}")
async def get_desig_norms_by_id(
    desg_norms_mst_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Single designation norm by id (with linked machine info)."""
    try:
        row = db.execute(
            _by_id_query(), {"desg_norms_mst_id": desg_norms_mst_id}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Designation norm not found")
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _validate_payload(body: dict) -> dict:
    desig_id = _to_int(body.get("desig_id"), "desig_id")
    if not desig_id:
        raise HTTPException(status_code=400, detail="desig_id is required")

    fixed_variable = (body.get("fixed_variable") or "").strip().upper()
    if fixed_variable not in ("F", "V"):
        raise HTTPException(
            status_code=400,
            detail="fixed_variable must be 'F' (Fixed) or 'V' (Variable)",
        )

    direct_indirect = (body.get("direct_indirect") or "").strip()
    if direct_indirect and direct_indirect not in ("Direct", "Indirect", "D", "I"):
        raise HTTPException(
            status_code=400,
            detail="direct_indirect must be Direct/Indirect (or D/I)",
        )
    # Normalise to 1-char codes (column is varchar(8) so either is fine, keep readable)
    di_code = {"Direct": "D", "Indirect": "I"}.get(direct_indirect, direct_indirect) or None

    mc_id = None
    no_of_mcs = None
    no_of_hands = None
    mc_code = None
    mc_type = None

    if fixed_variable == "V":
        mc_id = _to_int(body.get("mc_id"), "mc_id")
        no_of_mcs = _to_decimal(body.get("no_of_mcs"), "no_of_mcs")
        no_of_hands = _to_decimal(body.get("no_of_hands"), "no_of_hands")
        # mc_code / mc_type stored on header for convenience (optional)
        mc_code = (body.get("mc_code") or None)
        mc_type = _to_int(body.get("mc_type"), "mc_type")

    return {
        "desig_id": desig_id,
        "direct_indirect": di_code,
        "fixed_variable": fixed_variable,
        "shift_a": _to_decimal(body.get("shift_a"), "shift_a"),
        "shift_b": _to_decimal(body.get("shift_b"), "shift_b"),
        "shift_c": _to_decimal(body.get("shift_c"), "shift_c"),
        "shift_g": _to_decimal(body.get("shift_g"), "shift_g"),
        "re_calculate": _to_int(body.get("re_calculate"), "re_calculate"),
        "round_off": _to_int(body.get("round_off"), "round_off"),
        "norms": body.get("norms") or None,
        "mc_id": mc_id,
        "no_of_mcs": no_of_mcs,
        "no_of_hands": no_of_hands,
        "mc_code": mc_code,
        "mc_type": mc_type,
    }


@router.post("/desig_norms_create")
async def desig_norms_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new designation norm (and linked mc_occu_link_mst row when V)."""
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        data = _validate_payload(body)

        # Duplicate check: one active norm per designation
        dup = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM designation_norms_mst
                WHERE desig_id = :desig_id
                  AND COALESCE(active, 1) = 1
            """),
            {"desig_id": data["desig_id"]},
        ).fetchone()
        if dup and dup.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="A norm already exists for this designation",
            )

        result = db.execute(
            text("""
                INSERT INTO designation_norms_mst
                    (desig_id, direct_indirect, fixed_variable,
                     shift_a, shift_b, shift_c, shift_g,
                     re_calculate, mc_type, mc_code, round_off, norms, active)
                VALUES
                    (:desig_id, :direct_indirect, :fixed_variable,
                     :shift_a, :shift_b, :shift_c, :shift_g,
                     :re_calculate, :mc_type, :mc_code, :round_off, :norms, 1)
            """),
            data,
        )
        new_id = result.lastrowid

        if data["fixed_variable"] == "V":
            _upsert_mc_occu_link(
                db,
                desig_id=data["desig_id"],
                mc_id=data["mc_id"],
                no_of_mcs=data["no_of_mcs"],
                no_of_hands=data["no_of_hands"],
            )

        db.commit()
        return {
            "message": "Designation norm created successfully",
            "desg_norms_mst_id": new_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/desig_norms_edit/{desg_norms_mst_id}")
async def desig_norms_edit(
    desg_norms_mst_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing designation norm + its linked machine row."""
    try:
        body = await request.json()
        existing = db.execute(
            text("SELECT desg_norms_mst_id, desig_id FROM designation_norms_mst WHERE desg_norms_mst_id = :id"),
            {"id": desg_norms_mst_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Designation norm not found")

        data = _validate_payload(body)

        params = dict(data)
        params["id"] = desg_norms_mst_id
        db.execute(
            text("""
                UPDATE designation_norms_mst SET
                    desig_id        = :desig_id,
                    direct_indirect = :direct_indirect,
                    fixed_variable  = :fixed_variable,
                    shift_a         = :shift_a,
                    shift_b         = :shift_b,
                    shift_c         = :shift_c,
                    shift_g         = :shift_g,
                    re_calculate    = :re_calculate,
                    mc_type         = :mc_type,
                    mc_code         = :mc_code,
                    round_off       = :round_off,
                    norms           = :norms
                WHERE desg_norms_mst_id = :id
            """),
            params,
        )

        if data["fixed_variable"] == "V":
            _upsert_mc_occu_link(
                db,
                desig_id=data["desig_id"],
                mc_id=data["mc_id"],
                no_of_mcs=data["no_of_mcs"],
                no_of_hands=data["no_of_hands"],
            )
        else:
            # Switching from V to F: deactivate any existing link rows
            _upsert_mc_occu_link(
                db,
                desig_id=data["desig_id"],
                mc_id=None,
                no_of_mcs=None,
                no_of_hands=None,
            )

        db.commit()
        return {"message": "Designation norm updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/desig_norms_delete/{desg_norms_mst_id}")
async def desig_norms_delete(
    desg_norms_mst_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete a designation norm and its linked machine row."""
    try:
        row = db.execute(
            text("SELECT desig_id FROM designation_norms_mst WHERE desg_norms_mst_id = :id"),
            {"id": desg_norms_mst_id},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Designation norm not found")

        db.execute(
            text("UPDATE designation_norms_mst SET active = 0 WHERE desg_norms_mst_id = :id"),
            {"id": desg_norms_mst_id},
        )
        db.execute(
            text("UPDATE mc_occu_link_mst SET active = 0 WHERE desig_id = :desig_id"),
            {"desig_id": row.desig_id},
        )
        db.commit()
        return {"message": "Designation norm deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
