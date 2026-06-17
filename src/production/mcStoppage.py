"""
Production Entry — Machine Stoppage endpoints.

CRUD over `tbl_mc_stoppage`, which records downtime per machine / spell / date:

    stop_date  date          when the stoppage occurred
    spell_id   int           spell_mst.spell_id  (global, status=1)
    mc_id      int           machine_mst.machine_id (branch via dept_mst)
    stop_hours decimal(6,3)  downtime in decimal hours (e.g. 1.500 = 1h 30m)
    updated_by int           con user id (from the access token)

The table has no branch_id column, so listing is scoped to a branch by joining
the machine's department (`machine_mst` -> `dept_mst.branch_id`). Multiple rows
per (stop_date, spell_id, mc_id) are allowed (e.g. several breakdowns).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.common.utils import now_ist

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


def _req_int(value, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} is required")


def _req_stop_hours(value):
    if value is None or value == "":
        raise HTTPException(status_code=400, detail="stop_hours is required")
    try:
        hours = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="stop_hours must be a number")
    if hours < 0:
        raise HTTPException(status_code=400, detail="stop_hours cannot be negative")
    return hours


def _validate_payload(body: dict) -> dict:
    stop_date = (body.get("stop_date") or "").strip()
    if not stop_date:
        raise HTTPException(status_code=400, detail="stop_date is required")
    return {
        "stop_date": stop_date,
        "spell_id": _req_int(body.get("spell_id"), "spell_id"),
        "mc_id": _req_int(body.get("mc_id"), "mc_id"),
        "stop_hours": _req_stop_hours(body.get("stop_hours")),
    }


# ─── Setup (dropdown options) ───────────────────────────────────────

@router.get("/mc_stoppage_setup")
async def mc_stoppage_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Dropdown options for the machine-stoppage form.

    Query params: co_id (required), branch_id (required, csv allowed).
    Returns {spells, machines}.
    """
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))
    if not branch_ids:
        raise HTTPException(status_code=400, detail="branch_id is required")

    placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
    params = {f"b{i}": bid for i, bid in enumerate(branch_ids)}

    try:
        spells = db.execute(
            text(
                f"""
                SELECT sp.spell_id, sp.spell_name
                FROM spell_mst sp
                JOIN shift_mst sh ON sh.shift_id = sp.shift_id
                WHERE COALESCE(sp.status, 1) = 1
                  AND COALESCE(sh.status, 1) = 1
                  AND sh.branch_id IN ({placeholders})
                ORDER BY sp.spell_id
                """
            ),
            params,
        ).fetchall()

        machines = db.execute(
            text(
                f"""
                SELECT m.machine_id, m.machine_name, dm.dept_desc AS dept_name
                FROM machine_mst m
                LEFT JOIN dept_mst dm ON dm.dept_id = m.dept_id
                WHERE m.active = 1
                  AND dm.branch_id IN ({placeholders})
                ORDER BY m.machine_name
                """
            ),
            params,
        ).fetchall()

        return {
            "spells": [dict(r._mapping) for r in spells],
            "machines": [dict(r._mapping) for r in machines],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── List ───────────────────────────────────────────────────────────

@router.get("/mc_stoppage_list")
async def mc_stoppage_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated stoppage listing scoped to the branch's machines.

    Query params: co_id (required), branch_id (required, csv allowed),
    page, limit, search (machine / spell name).
    """
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    branch_ids = _parse_branch_ids(request.query_params.get("branch_id"))
    if not branch_ids:
        raise HTTPException(status_code=400, detail="branch_id is required")

    page = int(request.query_params.get("page", 1))
    limit = int(request.query_params.get("limit", 10))
    offset = max(page - 1, 0) * limit
    search = (request.query_params.get("search") or "").strip()

    placeholders = ",".join(f":b{i}" for i in range(len(branch_ids)))
    params: dict = {f"b{i}": bid for i, bid in enumerate(branch_ids)}
    params.update({"limit": limit, "offset": offset})

    clauses = [f"dm.branch_id IN ({placeholders})"]
    if search:
        clauses.append("(m.machine_name LIKE :s OR sm.spell_name LIKE :s)")
        params["s"] = f"%{search}%"
    where = " WHERE " + " AND ".join(clauses)

    try:
        rows = db.execute(
            text(
                f"""
                SELECT s.tbl_mc_stop_id, s.stop_date, s.spell_id, s.mc_id,
                       s.stop_hours, sm.spell_name, m.machine_name
                FROM tbl_mc_stoppage s
                LEFT JOIN spell_mst sm ON sm.spell_id = s.spell_id
                LEFT JOIN machine_mst m ON m.machine_id = s.mc_id
                LEFT JOIN dept_mst dm ON dm.dept_id = m.dept_id
                {where}
                ORDER BY s.stop_date DESC, s.tbl_mc_stop_id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).fetchall()

        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        total = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS cnt
                FROM tbl_mc_stoppage s
                LEFT JOIN machine_mst m ON m.machine_id = s.mc_id
                LEFT JOIN dept_mst dm ON dm.dept_id = m.dept_id
                {where}
                """
            ),
            count_params,
        ).fetchone()

        data = []
        for r in rows:
            d = dict(r._mapping)
            if d.get("stop_date") is not None:
                d["stop_date"] = str(d["stop_date"])[:10]
            if d.get("stop_hours") is not None:
                d["stop_hours"] = float(d["stop_hours"])
            data.append(d)

        return {
            "data": data,
            "total": int(total.cnt) if total else 0,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Get by id ──────────────────────────────────────────────────────

@router.get("/mc_stoppage_by_id/{stop_id}")
async def mc_stoppage_by_id(
    stop_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        row = db.execute(
            text(
                """
                SELECT tbl_mc_stop_id, stop_date, spell_id, mc_id, stop_hours
                FROM tbl_mc_stoppage
                WHERE tbl_mc_stop_id = :id
                """
            ),
            {"id": stop_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Stoppage entry not found")
        d = dict(row)
        if d.get("stop_date") is not None:
            d["stop_date"] = str(d["stop_date"])[:10]
        if d.get("stop_hours") is not None:
            d["stop_hours"] = float(d["stop_hours"])
        return {"data": d}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Create ─────────────────────────────────────────────────────────

@router.post("/mc_stoppage_create")
async def mc_stoppage_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    body = await request.json()
    data = _validate_payload(body)
    data["updated_by"] = int(token_data.get("user_id", 0))
    try:
        db.execute(
            text(
                """
                INSERT INTO tbl_mc_stoppage
                    (stop_date, spell_id, mc_id, stop_hours, updated_by)
                VALUES
                    (:stop_date, :spell_id, :mc_id, :stop_hours, :updated_by)
                """
            ),
            data,
        )
        db.commit()
        return {"message": "Machine stoppage entry created"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Edit ───────────────────────────────────────────────────────────

@router.put("/mc_stoppage_edit/{stop_id}")
async def mc_stoppage_edit(
    stop_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    body = await request.json()
    data = _validate_payload(body)
    data["id"] = stop_id
    data["updated_by"] = int(token_data.get("user_id", 0))
    data["updated_date_time"] = now_ist()
    try:
        res = db.execute(
            text(
                """
                UPDATE tbl_mc_stoppage
                   SET stop_date = :stop_date,
                       spell_id  = :spell_id,
                       mc_id     = :mc_id,
                       stop_hours = :stop_hours,
                       updated_by = :updated_by,
                       updated_date_time = :updated_date_time
                 WHERE tbl_mc_stop_id = :id
                """
            ),
            data,
        )
        if res.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=404, detail="Stoppage entry not found")
        db.commit()
        return {"message": "Machine stoppage entry updated"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Delete ─────────────────────────────────────────────────────────

@router.delete("/mc_stoppage_delete/{stop_id}")
async def mc_stoppage_delete(
    stop_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        res = db.execute(
            text("DELETE FROM tbl_mc_stoppage WHERE tbl_mc_stop_id = :id"),
            {"id": stop_id},
        )
        if res.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=404, detail="Stoppage entry not found")
        db.commit()
        return {"message": "Machine stoppage entry deleted"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
