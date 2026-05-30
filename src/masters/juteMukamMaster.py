"""
Jute Mukam Master API endpoints.
Provides CRUD operations for jute mukam (location) data.
Mukams are global (not company-specific) - they exist across all tenants.
"""

from fastapi import Depends, Request, HTTPException, APIRouter, Response
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist

router = APIRouter()


def get_jute_mukam_list_query():
    """
    Get all jute mukams (global - not company-specific).
    """
    return text("""
        SELECT
            jm.mukam_id,
            jm.mukam_name,
            jm.updated_by,
            jm.updated_date_time
        FROM jute_mukam_mst jm
        ORDER BY jm.mukam_id DESC
    """)


def get_jute_mukam_list_with_search_query():
    """
    Get all jute mukams with search filter.
    """
    return text("""
        SELECT
            jm.mukam_id,
            jm.mukam_name,
            jm.updated_by,
            jm.updated_date_time
        FROM jute_mukam_mst jm
        WHERE jm.mukam_name LIKE :search
        ORDER BY jm.mukam_id DESC
    """)


@router.get("/get_jute_mukam_table")
async def get_jute_mukam_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None,
    page: int = 1,
    limit: int = 10,
):
    """
    Get paginated list of jute mukams.
    Mukams are global - not filtered by company.
    """
    try:
        search_param = f"%{search}%" if search else None

        if search_param:
            query = get_jute_mukam_list_with_search_query()
            params = {"search": search_param}
        else:
            query = get_jute_mukam_list_query()
            params = {}

        result = db.execute(query, params).fetchall()
        all_data = [dict(row._mapping) for row in result]

        total = len(all_data)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_data = all_data[start_idx:end_idx]

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


@router.get("/get_jute_mukam_by_id/{mukam_id}")
async def get_jute_mukam_by_id(
    mukam_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute mukam record by ID.
    """
    try:
        query = text("""
            SELECT
                jm.mukam_id,
                jm.mukam_name,
                jm.updated_by,
                jm.updated_date_time
            FROM jute_mukam_mst jm
            WHERE jm.mukam_id = :mukam_id
        """)

        result = db.execute(query, {"mukam_id": mukam_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Jute mukam record not found")

        return {"data": dict(result._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_mukam_edit_setup/{mukam_id}")
async def jute_mukam_edit_setup(
    mukam_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for editing a jute mukam record.
    Returns the existing mukam details.
    """
    try:
        query = text("""
            SELECT
                jm.mukam_id,
                jm.mukam_name,
                jm.updated_by,
                jm.updated_date_time
            FROM jute_mukam_mst jm
            WHERE jm.mukam_id = :mukam_id
        """)

        result = db.execute(query, {"mukam_id": mukam_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Jute mukam record not found")

        return {
            "jute_mukam_details": dict(result._mapping)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_mukam_create")
async def jute_mukam_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new jute mukam record.
    """
    try:
        body = await request.json()
        mukam_name = (body.get("mukam_name") or "").strip()

        if not mukam_name:
            raise HTTPException(status_code=400, detail="Mukam name is required")

        duplicate_query = text("""
            SELECT mukam_id FROM jute_mukam_mst
            WHERE LOWER(mukam_name) = LOWER(:mukam_name)
        """)
        existing = db.execute(duplicate_query, {"mukam_name": mukam_name}).fetchone()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A mukam with the name '{mukam_name}' already exists"
            )

        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None

        insert_query = text("""
            INSERT INTO jute_mukam_mst (mukam_name, updated_by, updated_date_time)
            VALUES (:mukam_name, :updated_by, :updated_date_time)
        """)

        db.execute(insert_query, {
            "mukam_name": mukam_name,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {"message": "Jute mukam created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jute_mukam_edit/{mukam_id}")
async def jute_mukam_edit(
    mukam_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update an existing jute mukam record.
    """
    try:
        body = await request.json()
        mukam_name = (body.get("mukam_name") or "").strip()

        if not mukam_name:
            raise HTTPException(status_code=400, detail="Mukam name is required")

        exists_query = text("""
            SELECT mukam_id FROM jute_mukam_mst
            WHERE mukam_id = :mukam_id
        """)
        existing = db.execute(exists_query, {"mukam_id": mukam_id}).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Jute mukam not found")

        duplicate_query = text("""
            SELECT mukam_id FROM jute_mukam_mst
            WHERE LOWER(mukam_name) = LOWER(:mukam_name)
              AND mukam_id != :mukam_id
        """)
        duplicate = db.execute(duplicate_query, {
            "mukam_name": mukam_name,
            "mukam_id": mukam_id,
        }).fetchone()
        if duplicate:
            raise HTTPException(
                status_code=400,
                detail=f"A mukam with the name '{mukam_name}' already exists"
            )

        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None

        update_query = text("""
            UPDATE jute_mukam_mst
            SET mukam_name = :mukam_name,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE mukam_id = :mukam_id
        """)

        db.execute(update_query, {
            "mukam_id": mukam_id,
            "mukam_name": mukam_name,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {"message": "Jute mukam updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
