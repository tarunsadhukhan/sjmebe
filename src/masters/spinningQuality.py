"""Spinning Quality Master API endpoints.

CRUD endpoints for spinning_quality_mst, modeled after yarnQuality.py.
spg_type_id sources from item_grp_mst (yarn types, item_type_id=4).
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import SpinningQualityMst
from src.masters.query import (
    get_branch_list,
    get_spinning_type_list,
    get_spinning_quality_list,
    get_spinning_quality_by_id,
    check_spinning_quality_exists,
)

router = APIRouter()


def optional_auth(
    request: Request,
    response: Response,
    access_token: str = Cookie(None, alias="access_token"),
) -> dict:
    """Dev-toggle auth dependency (matches yarnQuality.optional_auth)."""
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/spinning_quality_create_setup")
async def spinning_quality_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return dropdown options (spg types + branches) for create form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        spg_types = db.execute(get_spinning_type_list()).fetchall()
        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()

        return {
            "data": {
                "spg_types": [dict(r._mapping) for r in spg_types],
                "branches": [dict(r._mapping) for r in branches],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"spinning_quality_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spinning_quality_table")
async def spinning_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated spinning quality list with optional search."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        branch_id = request.query_params.get("branch_id")
        branch_id_int = int(branch_id) if branch_id else None

        search_param = f"%{search}%" if search else None
        params = {"search": search_param}
        if branch_id_int:
            params["branch_id"] = branch_id_int

        rows = db.execute(get_spinning_quality_list(branch_id_int), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        total = len(data)
        start = (page - 1) * limit
        end = start + limit
        return {
            "data": data[start:end],
            "total": total,
            "page": page,
            "page_size": limit,
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"spinning_quality_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spinning_quality_create")
async def spinning_quality_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new spinning quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        branch_id = payload.get("branch_id")
        spg_type_id = payload.get("spg_type_id")
        spg_quality = payload.get("spg_quality")
        speed = payload.get("speed")
        tpi = payload.get("tpi")
        std_count = payload.get("std_count")
        no_of_spindles = payload.get("no_of_spindles")
        frame_type = payload.get("frame_type")
        target_eff = payload.get("target_eff")

        if not spg_quality:
            raise HTTPException(status_code=400, detail="Spinning quality is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")
        if not spg_type_id:
            raise HTTPException(status_code=400, detail="Spinning type is required")
        if no_of_spindles in (None, ""):
            raise HTTPException(status_code=400, detail="No of spindles is required")
        if not frame_type:
            raise HTTPException(status_code=400, detail="Frame type is required")

        dup_row = db.execute(
            check_spinning_quality_exists(
                spg_quality, int(spg_type_id), int(no_of_spindles), frame_type
            ),
            {
                "spg_quality": spg_quality,
                "spg_type_id": int(spg_type_id),
                "no_of_spindles": int(no_of_spindles),
                "frame_type": frame_type,
            },
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Spinning quality with same Spinning Type, No of Spindles and Frame Type already exists",
            )

        record = SpinningQualityMst(
            spg_quality=spg_quality,
            spg_type_id=int(spg_type_id) if spg_type_id else None,
            speed=int(speed) if speed not in (None, "") else None,
            tpi=float(tpi) if tpi not in (None, "") else None,
            std_count=float(std_count) if std_count not in (None, "") else None,
            no_of_spindles=int(no_of_spindles) if no_of_spindles not in (None, "") else None,
            frame_type=frame_type or None,
            target_eff=int(target_eff) if target_eff not in (None, "") else None,
            branch_id=int(branch_id) if branch_id else None,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Spinning quality created successfully",
            "spg_quality_mst_id": record.spg_quality_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"spinning_quality_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spinning_quality_edit_setup")
async def spinning_quality_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + dropdown options for edit form."""
    try:
        co_id = request.query_params.get("co_id")
        spg_quality_mst_id = request.query_params.get("spg_quality_mst_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not spg_quality_mst_id:
            raise HTTPException(status_code=400, detail="spg_quality_mst_id is required")

        row = db.execute(
            get_spinning_quality_by_id(),
            {"spg_quality_mst_id": int(spg_quality_mst_id)},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Spinning quality not found")

        spg_types = db.execute(get_spinning_type_list()).fetchall()
        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()

        return {
            "data": {
                "spinning_quality_details": dict(row._mapping),
                "spg_types": [dict(r._mapping) for r in spg_types],
                "branches": [dict(r._mapping) for r in branches],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"spinning_quality_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/spinning_quality_edit", methods=["POST", "PUT"])
async def spinning_quality_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing spinning quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        spg_quality_mst_id = payload.get("spg_quality_mst_id")
        if not spg_quality_mst_id:
            raise HTTPException(status_code=400, detail="spg_quality_mst_id is required")

        existing = (
            db.query(SpinningQualityMst)
            .filter(SpinningQualityMst.spg_quality_mst_id == int(spg_quality_mst_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Spinning quality not found")

        spg_quality = payload.get("spg_quality")
        spg_type_id = payload.get("spg_type_id")
        branch_id = payload.get("branch_id")
        speed = payload.get("speed")
        tpi = payload.get("tpi")
        std_count = payload.get("std_count")
        no_of_spindles = payload.get("no_of_spindles")
        frame_type = payload.get("frame_type")
        target_eff = payload.get("target_eff")

        # Duplicate check on the unique combination
        target_quality = spg_quality if spg_quality is not None else existing.spg_quality
        target_spg_type = int(spg_type_id) if spg_type_id not in (None, "") else existing.spg_type_id
        target_spindles = (
            int(no_of_spindles) if no_of_spindles not in (None, "") else existing.no_of_spindles
        )
        target_frame = frame_type if frame_type is not None else existing.frame_type

        if (
            target_quality is not None
            and target_spg_type is not None
            and target_spindles is not None
            and target_frame is not None
        ):
            dup_row = db.execute(
                check_spinning_quality_exists(
                    target_quality,
                    target_spg_type,
                    target_spindles,
                    target_frame,
                    int(spg_quality_mst_id),
                ),
                {
                    "spg_quality": target_quality,
                    "spg_type_id": target_spg_type,
                    "no_of_spindles": target_spindles,
                    "frame_type": target_frame,
                    "exclude_id": int(spg_quality_mst_id),
                },
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Spinning quality with same Spinning Type, No of Spindles and Frame Type already exists",
                )

        if spg_quality is not None:
            existing.spg_quality = spg_quality
        if spg_type_id not in (None, ""):
            existing.spg_type_id = int(spg_type_id)
        if branch_id not in (None, ""):
            existing.branch_id = int(branch_id)
        if speed not in (None, ""):
            existing.speed = int(speed)
        if tpi not in (None, ""):
            existing.tpi = float(tpi)
        if std_count not in (None, ""):
            existing.std_count = float(std_count)
        if no_of_spindles not in (None, ""):
            existing.no_of_spindles = int(no_of_spindles)
        if frame_type is not None:
            existing.frame_type = frame_type or None
        if target_eff not in (None, ""):
            existing.target_eff = int(target_eff)
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "data": {
                "message": "Spinning quality updated successfully",
                "spg_quality_mst_id": existing.spg_quality_mst_id,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"spinning_quality_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
