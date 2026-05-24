"""
Spell Master API endpoints.

Provides CRUD operations for the spell_mst table.
Each spell belongs to a shift via shift_id FK.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.mst import SpellMst
from datetime import datetime, timedelta
from decimal import Decimal

router = APIRouter()


# ─── Helpers ────────────────────────────────────────────────────────


def _serialize_spell_row(row):
    """Convert a spell row to a JSON-safe dict (handle timedelta/Decimal)."""
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, timedelta):
            total = int(v.total_seconds())
            hours, remainder = divmod(total, 3600)
            minutes = remainder // 60
            d[k] = f"{hours:02d}:{minutes:02d}"
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


# ─── SQL Queries ────────────────────────────────────────────────────


def get_spell_list_query(branch_ids=None):
    branch_filter = ""
    if branch_ids:
        placeholders = ",".join(str(int(b)) for b in branch_ids)
        branch_filter = f"AND sh.branch_id IN ({placeholders})"
    return text(f"""
        SELECT
            sp.spell_id,
            sp.spell_code,
            sp.spell_name,
            sp.status,
            sp.shift_id,
            TIME_FORMAT(sp.starting_time, '%H:%i') AS starting_time,
            TIME_FORMAT(sp.end_time, '%H:%i') AS end_time,
            sp.working_hours,
            sp.minimum_work_hours,
            sp.break_hours,
            sp.halfday_work_hours,
            sp.late_minutes,
            sp.late_minutes2,
            sp.is_overnight,
            sp.updated_by,
            sp.update_date_time,
            sh.shift_name,
            b.branch_name
        FROM spell_mst sp
        LEFT JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        LEFT JOIN branch_mst b ON b.branch_id = sh.branch_id
        WHERE sp.status = 1
          {branch_filter}
          AND (:search IS NULL OR sp.spell_name LIKE :search
               OR sp.spell_code LIKE :search
               OR sh.shift_name LIKE :search)
        ORDER BY sp.spell_id DESC
    """)


def get_spell_by_id_query():
    return text("""
        SELECT
            sp.spell_id,
            sp.spell_code,
            sp.spell_name,
            sp.status,
            sp.shift_id,
            TIME_FORMAT(sp.starting_time, '%H:%i') AS starting_time,
            TIME_FORMAT(sp.end_time, '%H:%i') AS end_time,
            sp.working_hours,
            sp.minimum_work_hours,
            sp.break_hours,
            sp.halfday_work_hours,
            sp.late_minutes,
            sp.late_minutes2,
            sp.is_overnight,
            sp.updated_by,
            sp.update_date_time,
            sh.shift_name,
            b.branch_name
        FROM spell_mst sp
        LEFT JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        LEFT JOIN branch_mst b ON b.branch_id = sh.branch_id
        WHERE sp.spell_id = :spell_id
    """)


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/get_spell_table")
async def get_spell_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of spells."""
    try:
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        raw_branch_ids = request.query_params.get("branch_id")
        branch_ids = None
        if raw_branch_ids:
            try:
                branch_ids = [int(b) for b in raw_branch_ids.split(",") if b.strip()]
            except (ValueError, TypeError):
                branch_ids = None

        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))

        query = get_spell_list_query(branch_ids=branch_ids)
        result = db.execute(query, {"search": search_param}).fetchall()

        all_data = [_serialize_spell_row(row) for row in result]
        total = len(all_data)
        start_idx = (page - 1) * limit
        paginated_data = all_data[start_idx:start_idx + limit]

        return {
            "data": paginated_data,
            "total": total,
            "page": page,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_spell_by_id/{spell_id}")
async def get_spell_by_id(
    spell_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get a single spell record by ID."""
    try:
        query = get_spell_by_id_query()
        result = db.execute(query, {"spell_id": spell_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Spell not found")

        return {"data": _serialize_spell_row(result)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spell_create_setup")
async def spell_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get dropdown options needed for spell creation (shifts by branch)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")

        # branch_id may be a single value "103" or CSV "103,104"
        branch_ids: list[int] = []
        if branch_id:
            for part in str(branch_id).split(","):
                part = part.strip()
                if part:
                    try:
                        branch_ids.append(int(part))
                    except ValueError:
                        raise HTTPException(status_code=400, detail="Invalid branch_id format")

        if branch_ids:
            placeholders = ",".join(str(b) for b in branch_ids)
            branch_filter = f"AND s.branch_id IN ({placeholders})"
        else:
            branch_filter = ""

        shift_query = text(f"""
            SELECT s.shift_id, s.shift_name FROM shift_mst s
            JOIN branch_mst b ON b.branch_id = s.branch_id
            WHERE b.co_id = :co_id AND s.status = 1
              {branch_filter}
            ORDER BY s.shift_name
        """)

        shifts = db.execute(shift_query, {"co_id": int(co_id)}).fetchall()

        return {
            "shifts": [dict(r._mapping) for r in shifts],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spell_create")
async def spell_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new spell record."""
    try:
        body = await request.json()

        spell_name = body.get("spell_name")
        if not spell_name:
            raise HTTPException(status_code=400, detail="Spell name is required")

        shift_id = body.get("shift_id")
        if not shift_id:
            raise HTTPException(status_code=400, detail="Shift is required")

        # Check duplicate (spell_name + branch_id, branch resolved via shift)
        dup_query = text("""
            SELECT COUNT(*) AS cnt
            FROM spell_mst sp
            JOIN shift_mst sh ON sh.shift_id = sp.shift_id
            WHERE sp.spell_name = :spell_name
              AND sp.status = 1
              AND sh.branch_id = (
                  SELECT branch_id FROM shift_mst WHERE shift_id = :shift_id
              )
        """)
        dup_result = db.execute(dup_query, {
            "spell_name": spell_name,
            "shift_id": int(shift_id),
        }).fetchone()
        print(f"Duplicate check for spell_name='{spell_name}' and shift_id={shift_id} returned count={dup_result.cnt if dup_result else 'None'}")
        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Spell with this name already exists for this branch",
            )

        user_id = token_data.get("user_id") if token_data else None

        insert_query = text("""
            INSERT INTO spell_mst
                (spell_code, spell_name, status, shift_id, starting_time, end_time,
                 working_hours, minimum_work_hours, break_hours, halfday_work_hours,
                 late_minutes, late_minutes2, is_overnight, updated_by, update_date_time)
            VALUES
                (:spell_code, :spell_name, :status, :shift_id, :starting_time, :end_time,
                 :working_hours, :minimum_work_hours, :break_hours, :halfday_work_hours,
                 :late_minutes, :late_minutes2, :is_overnight, :updated_by, :update_date_time)
        """)
        result = db.execute(insert_query, {
            "spell_code": body.get("spell_code", ""),
            "spell_name": spell_name,
            "status": 1,
            "shift_id": int(shift_id),
            "starting_time": body.get("starting_time") or None,
            "end_time": body.get("end_time") or None,
            "working_hours": body.get("working_hours") or None,
            "minimum_work_hours": body.get("minimum_work_hours") or None,
            "break_hours": body.get("break_hours") or None,
            "halfday_work_hours": body.get("halfday_work_hours") or None,
            "late_minutes": int(body["late_minutes"]) if body.get("late_minutes") else None,
            "late_minutes2": int(body["late_minutes2"]) if body.get("late_minutes2") else None,
            "is_overnight": int(body["is_overnight"]) if body.get("is_overnight") else 0,
            "updated_by": user_id,
            "update_date_time": datetime.now(),
        })
        db.commit()
        new_spell_id = result.lastrowid

        return {
            "message": "Spell created successfully",
            "spell_id": new_spell_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/spell_edit/{spell_id}")
async def spell_edit(
    spell_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing spell record."""
    try:
        body = await request.json()

        spell_name = body.get("spell_name")
        if not spell_name:
            raise HTTPException(status_code=400, detail="Spell name is required")

        existing = db.query(SpellMst).filter(
            SpellMst.spell_id == spell_id,
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Spell not found")

        # Check duplicate (spell_name + branch_id, excluding current record).
        # Branch resolved via the shift_id of incoming body, falling back to existing.
        new_shift_id = int(body["shift_id"]) if body.get("shift_id") else existing.shift_id
        dup_query = text("""
            SELECT COUNT(*) AS cnt
            FROM spell_mst sp
            JOIN shift_mst sh ON sh.shift_id = sp.shift_id
            WHERE sp.spell_name = :spell_name
              AND sp.status = 1
              AND sp.spell_id != :spell_id
              AND sh.branch_id = (
                  SELECT branch_id FROM shift_mst WHERE shift_id = :shift_id
              )
        """)
        dup_result = db.execute(dup_query, {
            "spell_name": spell_name,
            "spell_id": spell_id,
            "shift_id": new_shift_id,
        }).fetchone()

        if dup_result and dup_result.cnt > 0:
            raise HTTPException(
                status_code=400,
                detail="Spell with this name already exists for this branch",
            )

        user_id = token_data.get("user_id") if token_data else None

        existing.spell_code = body.get("spell_code", existing.spell_code)
        existing.spell_name = spell_name
        existing.shift_id = int(body["shift_id"]) if body.get("shift_id") else existing.shift_id
        existing.starting_time = body.get("starting_time", existing.starting_time)
        existing.end_time = body.get("end_time", existing.end_time)
        existing.working_hours = body.get("working_hours", existing.working_hours)
        existing.minimum_work_hours = body.get("minimum_work_hours", existing.minimum_work_hours)
        existing.break_hours = body.get("break_hours", existing.break_hours)
        existing.halfday_work_hours = body.get("halfday_work_hours", existing.halfday_work_hours)
        existing.late_minutes = int(body["late_minutes"]) if body.get("late_minutes") is not None else existing.late_minutes
        existing.late_minutes2 = int(body["late_minutes2"]) if body.get("late_minutes2") is not None else existing.late_minutes2
        existing.is_overnight = int(body["is_overnight"]) if body.get("is_overnight") is not None else existing.is_overnight
        existing.updated_by = user_id
        existing.update_date_time = datetime.now()

        db.commit()

        return {"message": "Spell updated successfully", "spell_id": spell_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
