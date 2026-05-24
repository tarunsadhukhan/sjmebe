from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
import os
from sqlalchemy.orm import Session
from datetime import datetime
from src.common.utils import now_ist

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.jute import YarnQualityMst
from src.masters.query import (
    get_yarn_type_list,
    get_yarn_quality_list,
    get_yarn_quality_by_id,
    check_yarn_quality_code_exists,
    get_branch_list,
)

router = APIRouter()


def optional_auth(request: Request, response: Response, access_token: str = Cookie(None, alias="access_token")) -> dict:
    """Dev-toggle auth dependency.
    If BYPASS_AUTH=1 or ENV=development, return a dummy user dict. Otherwise delegate to the real auth helper.
    """
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/yarn_quality_create_setup")
async def yarn_quality_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get setup data for creating yarn quality - returns yarn types and branches dropdown."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get yarn types for dropdown
        yarn_type_query = get_yarn_type_list(int(co_id))
        yarn_types = db.execute(yarn_type_query, {"co_id": int(co_id)}).fetchall()
        yarn_types_data = [dict(row._mapping) for row in yarn_types] if yarn_types else []
        
        # Get branches for dropdown based on co_id
        branch_query = get_branch_list(co_id=int(co_id))
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()
        branches_data = [dict(row._mapping) for row in branches] if branches else []
        
        return {
            "data": {
                "yarn_types": yarn_types_data,
                "branches": branches_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"yarn_quality_create_setup error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_quality_table")
async def yarn_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Get yarn quality list with pagination and search."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        co_id = int(co_id)
        search_param = f"%{search}%" if search else None

        query = get_yarn_quality_list(co_id)
        rows = db.execute(query, {"co_id": co_id, "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in rows]

        # Simple pagination logic
        total = len(data)
        start = (page - 1) * limit
        end = start + limit
        paginated_data = data[start:end]

        return {
            "data": paginated_data,
            "total": total,
            "page": page,
            "page_size": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"yarn_quality_table error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/yarn_quality_create")
async def yarn_quality_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new yarn quality record."""
    try:
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        # Extract fields
        co_id = payload.get("co_id")
        branch_id = payload.get("branch_id")
        quality_code = payload.get("quality_code")
        item_grp_id = payload.get("item_grp_id")
        twist_per_inch = payload.get("twist_per_inch")
        std_count = payload.get("std_count")
        std_doff = payload.get("std_doff")
        std_wt_doff = payload.get("std_wt_doff")
        target_eff = payload.get("target_eff")
        is_active = payload.get("is_active", 1)

        # Validate required fields
        if not quality_code:
            raise HTTPException(status_code=400, detail="Quality code is required")
        if not item_grp_id:
            raise HTTPException(status_code=400, detail="Yarn type is required")

        # Check for duplicate quality code
        dup_query = check_yarn_quality_code_exists(branch_id, quality_code)
        print(dup_query, flush=True)
        dup_result = db.execute(dup_query, {"branch_id": branch_id, "quality_code": quality_code}).fetchone()
        if dup_result and dup_result._mapping.get("count", 0) > 0:
            raise HTTPException(status_code=409, detail="Quality code already exists")

        # Create new yarn quality record
        new_yarn_quality = YarnQualityMst(
            quality_code=quality_code,
            item_grp_id=int(item_grp_id) if item_grp_id else None,
            twist_per_inch=float(twist_per_inch) if twist_per_inch else None,
            std_count=float(std_count) if std_count else None,
            std_doff=int(std_doff) if std_doff else None,
            std_wt_doff=float(std_wt_doff) if std_wt_doff else None,
            target_eff=float(target_eff) if target_eff else None,
            is_active=int(is_active) if is_active else 1,
            branch_id=int(branch_id) if branch_id else None,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )

        db.add(new_yarn_quality)
        db.commit()
        db.refresh(new_yarn_quality) 
        response.status_code = 201

        return {
            "message": "Yarn quality created successfully",
            "yarn_quality_id": new_yarn_quality.yarn_quality_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"yarn_quality_create error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/yarn_quality_edit_setup")
async def yarn_quality_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get setup data for editing yarn quality."""
    try:
        co_id = request.query_params.get("co_id")
        yarn_quality_id = request.query_params.get("yarn_quality_id")

        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not yarn_quality_id:
            raise HTTPException(status_code=400, detail="Yarn Quality ID (yarn_quality_id) is required")

        # Get yarn quality details
        quality_query = get_yarn_quality_by_id(int(yarn_quality_id))
        quality_row = db.execute(quality_query, {"yarn_quality_id": int(yarn_quality_id)}).fetchone()

        if not quality_row:
            raise HTTPException(status_code=404, detail="Yarn quality not found")

        quality_details = dict(quality_row._mapping)

        # Get yarn types for dropdown
        yarn_type_query = get_yarn_type_list(int(co_id))
        yarn_types = db.execute(yarn_type_query, {"co_id": int(co_id)}).fetchall()
        yarn_types_data = [dict(row._mapping) for row in yarn_types] if yarn_types else []

        # Get branches for dropdown based on co_id
        branch_query = get_branch_list(co_id=int(co_id))
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()
        branches_data = [dict(row._mapping) for row in branches] if branches else []

        return {
            "data": {
                "yarn_quality_details": quality_details,
                "yarn_types": yarn_types_data,
                "branches": branches_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"yarn_quality_edit_setup error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/yarn_quality_view")
async def yarn_quality_view(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get details of a single yarn quality record."""
    try:
        co_id = request.query_params.get("co_id")
        yarn_quality_id = request.query_params.get("yarn_quality_id")

        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not yarn_quality_id:
            raise HTTPException(status_code=400, detail="Yarn Quality ID (yarn_quality_id) is required")

        # Get yarn quality details
        quality_query = get_yarn_quality_by_id(int(yarn_quality_id))
        quality_row = db.execute(quality_query, {"yarn_quality_id": int(yarn_quality_id)}).fetchone()

        if not quality_row:
            raise HTTPException(status_code=404, detail="Yarn quality not found")

        quality_details = dict(quality_row._mapping)

        return {
            "data": quality_details
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"yarn_quality_view error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/yarn_quality_edit", methods=["POST", "PUT"])
async def yarn_quality_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing yarn quality record."""
    try:
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        # Extract fields
        yarn_quality_id = payload.get("yarn_quality_id")
        co_id = payload.get("co_id")
        quality_code = payload.get("quality_code")
        item_grp_id = payload.get("item_grp_id")
        twist_per_inch = payload.get("twist_per_inch")
        std_count = payload.get("std_count")
        std_doff = payload.get("std_doff")
        std_wt_doff = payload.get("std_wt_doff")
        target_eff = payload.get("target_eff")
        is_active = payload.get("is_active", 1)

        if not yarn_quality_id:
            raise HTTPException(status_code=400, detail="Yarn Quality ID is required")

        # Find existing record
        existing = db.query(YarnQualityMst).filter(
            YarnQualityMst.yarn_quality_id == int(yarn_quality_id)
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Yarn quality not found")

        # Check for duplicate quality code (excluding current record)
        if quality_code and quality_code != existing.quality_code:
            dup_query = check_yarn_quality_code_exists(co_id, quality_code, int(yarn_quality_id))
            dup_result = db.execute(
                dup_query,
                {
                    "co_id": co_id,
                    "quality_code": quality_code,
                    "exclude_id": int(yarn_quality_id),
                },
            ).fetchone()
            if dup_result and dup_result._mapping.get("count", 0) > 0:
                raise HTTPException(status_code=409, detail="Quality code already exists")

        # Update fields
        existing.quality_code = quality_code or existing.quality_code
        existing.item_grp_id = int(item_grp_id) if item_grp_id else existing.item_grp_id
        existing.twist_per_inch = float(twist_per_inch) if twist_per_inch else existing.twist_per_inch
        existing.std_count = float(std_count) if std_count else existing.std_count
        existing.std_doff = int(std_doff) if std_doff else existing.std_doff
        existing.std_wt_doff = float(std_wt_doff) if std_wt_doff else existing.std_wt_doff
        existing.target_eff = float(target_eff) if target_eff else existing.target_eff
        existing.is_active = int(is_active) if is_active else existing.is_active
        existing.updated_by = int(user_id) if user_id and str(user_id).isdigit() else existing.updated_by
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        print(f"Yarn quality {yarn_quality_id} updated successfully", flush=True)

        return {
            "data": {
                "message": "Yarn quality updated successfully",
                "yarn_quality_id": existing.yarn_quality_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"yarn_quality_edit error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
