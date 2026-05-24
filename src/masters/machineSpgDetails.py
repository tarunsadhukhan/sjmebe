from datetime import datetime
from src.common.utils import now_ist
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Cookie
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.machineSpgDetailsQuery import (
    get_machine_spg_details_list,
    get_machine_spg_details_by_id,
    get_machine_list_by_branch,
    check_machine_spg_code_exists,
)
from src.masters.query import get_branch_list
from src.models.jute import MachineSpgDetails

router = APIRouter(tags=["Machine SPG Details"])


def optional_auth(request: Request, response: Response, access_token: str = Cookie(None, alias="access_token")) -> dict:
    """Optional authentication - returns token data if available, None otherwise."""
    if not access_token:
        return None
    
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/machine_spg_details_create_setup")
async def machine_spg_details_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get setup data for creating machine SPG details - returns branches dropdown."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        # Get branches for dropdown based on co_id
        branch_query = get_branch_list(co_id=int(co_id))
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()
        branches_data = [dict(row._mapping) for row in branches] if branches else []
        
        return {
            "data": {
                "branches": branches_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"machine_spg_details_create_setup error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machine_spg_details_table")
async def machine_spg_details_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get paginated list of machine SPG details."""
    try:
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 10))
        search = request.query_params.get("search", "")
        branch_ids = request.query_params.get("branch_id", "")

        # Build WHERE clause for filtering
        where_conditions = []
        params = {"search": f"%{search}%"}
        
        if search:
            where_conditions.append("mm.machine_name LIKE :search")
        
        if branch_ids:
            # Parse comma-separated branch IDs
            branch_list = [b.strip() for b in branch_ids.split(",") if b.strip()]
            if branch_list:
                placeholders = ",".join([f":branch_{i}" for i in range(len(branch_list))])
                where_conditions.append(f"msd.branch_id IN ({placeholders})")
                for i, bid in enumerate(branch_list):
                    params[f"branch_{i}"] = int(bid)

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        # Get total count
        count_sql = f"""SELECT COUNT(*) as total FROM mechine_spg_details msd
                        LEFT JOIN machine_mst mm ON msd.mechine_id = mm.machine_id
                        WHERE {where_clause}"""
        count_result = db.execute(text(count_sql), params).scalar()

        # Get paginated data
        offset = (page - 1) * limit
        data_sql = f"""
        SELECT
          msd.mc_spg_det_id,
          msd.mechine_id,
          mm.machine_name,
          msd.speed,
          msd.no_of_spindle,
          msd.weight_per_spindle,
          msd.is_active,
          msd.branch_id,
          bm.branch_name
        FROM mechine_spg_details msd
        LEFT JOIN machine_mst mm ON msd.mechine_id = mm.machine_id
        LEFT JOIN branch_mst bm ON msd.branch_id = bm.branch_id
        WHERE {where_clause}
        ORDER BY msd.mc_spg_det_id DESC
        LIMIT :limit OFFSET :offset
        """
        params["limit"] = limit
        params["offset"] = offset

        rows = db.execute(text(data_sql), params).fetchall()
        data = [dict(row._mapping) for row in rows] if rows else []

        return {
            "data": data,
            "total": count_result or 0,
            "page": page,
            "page_size": limit,
        }
    except Exception as e:
        print(f"machine_spg_details_table error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_machines_by_branch")
async def get_machines_by_branch(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get list of machines for a branch."""
    try:
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch ID is required")

        machine_query = get_machine_list_by_branch(int(branch_id))
        machines = db.execute(machine_query, {"branch_id": int(branch_id)}).fetchall()
        machines_data = [dict(row._mapping) for row in machines] if machines else []

        return {
            "data": {
                "machines": machines_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"get_machines_by_branch error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/machine_spg_details_create")
async def machine_spg_details_create(
    request: Request,
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new machine SPG details record."""
    try:
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        # Extract fields
        co_id = payload.get("co_id")
        branch_id = payload.get("branch_id")
        mechine_id = payload.get("mechine_id")
        speed = payload.get("speed")
        no_of_spindle = payload.get("no_of_spindle")
        weight_per_spindle = payload.get("weight_per_spindle")
        is_active = payload.get("is_active", 1)

        # Validate required fields
        if not mechine_id:
            raise HTTPException(status_code=400, detail="Machine is required")

        # Check for duplicate
        dup_query = check_machine_spg_code_exists(int(branch_id), int(mechine_id))
        dup_result = db.execute(dup_query, {"branch_id": int(branch_id), "mechine_id": int(mechine_id)}).fetchone()
        if dup_result and dup_result._mapping.get("count", 0) > 0:
            raise HTTPException(status_code=409, detail="Machine SPG details already exist for this machine")

        # Create new record
        new_record = MachineSpgDetails(
            mechine_id=int(mechine_id) if mechine_id else None,
            frame_type="",
            speed=float(speed) if speed is not None else None,
            no_of_spindle=int(no_of_spindle) if no_of_spindle is not None else None,
            weight_per_spindle=float(weight_per_spindle) if weight_per_spindle is not None else None,
            is_active=int(is_active) if is_active else 1,
            branch_id=int(branch_id) if branch_id is not None else None,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )

        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        response.status_code = 201

        return {
            "message": "Machine SPG details created successfully",
            "mc_spg_det_id": new_record.mc_spg_det_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"machine_spg_details_create error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/machine_spg_details_edit_setup")
async def machine_spg_details_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get setup data for editing machine SPG details."""
    try:
        co_id = request.query_params.get("co_id")
        mc_spg_det_id = request.query_params.get("mc_spg_det_id")

        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not mc_spg_det_id:
            raise HTTPException(status_code=400, detail="Machine SPG Detail ID is required")

        # Get record details
        details_query = get_machine_spg_details_by_id(int(mc_spg_det_id))
        details_row = db.execute(details_query, {"mc_spg_det_id": int(mc_spg_det_id)}).fetchone()

        if not details_row:
            raise HTTPException(status_code=404, detail="Machine SPG details not found")

        details = dict(details_row._mapping)

        # Get branches for dropdown based on co_id
        branch_query = get_branch_list(co_id=int(co_id))
        branches = db.execute(branch_query, {"co_id": int(co_id)}).fetchall()
        branches_data = [dict(row._mapping) for row in branches] if branches else []

        return {
            "data": {
                "machine_spg_details": details,
                "branches": branches_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"machine_spg_details_edit_setup error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/machine_spg_details_edit")
async def machine_spg_details_edit(
    request: Request,
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing machine SPG details record."""
    try:
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        # Extract fields
        mc_spg_det_id = payload.get("mc_spg_det_id")
        co_id = payload.get("co_id")
        mechine_id = payload.get("mechine_id")
        speed = payload.get("speed")
        no_of_spindle = payload.get("no_of_spindle")
        weight_per_spindle = payload.get("weight_per_spindle")
        is_active = payload.get("is_active", 1)

        if not mc_spg_det_id:
            raise HTTPException(status_code=400, detail="Machine SPG Detail ID is required")

        # Find existing record
        existing = db.query(MachineSpgDetails).filter(
            MachineSpgDetails.mc_spg_det_id == int(mc_spg_det_id)
        ).first()

        if not existing:
            raise HTTPException(status_code=404, detail="Machine SPG details not found")

        # Update fields
        existing.speed = float(speed) if speed is not None else existing.speed
        existing.no_of_spindle = int(no_of_spindle) if no_of_spindle is not None else existing.no_of_spindle
        existing.weight_per_spindle = float(weight_per_spindle) if weight_per_spindle is not None else existing.weight_per_spindle
        existing.is_active = int(is_active) if is_active else existing.is_active
        existing.updated_by = int(user_id) if user_id and str(user_id).isdigit() else existing.updated_by
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        print(f"Machine SPG details {mc_spg_det_id} updated successfully", flush=True)

        return {
            "data": {
                "message": "Machine SPG details updated successfully",
                "mc_spg_det_id": existing.mc_spg_det_id
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"machine_spg_details_edit error: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
