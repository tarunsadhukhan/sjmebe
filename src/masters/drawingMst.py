"""Drawing Master API endpoints.

CRUD endpoints for tbl_drawing_mst, modeled after frameDetails.py.
Machine options come from machine_mst where machine_type_id = DRAWING_MACHINE_TYPE_ID.
meter_type: 0 = No Meter, 1 = Hours, 2 = Seconds.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import TblDrawingMst
from src.masters.query import (
    get_branch_list,
    get_frame_machine_list,
    get_drawing_mst_list,
    get_drawing_mst_by_id,
    check_drawing_mst_exists,
)

router = APIRouter()

DRAWING_MACHINE_TYPE_ID = 14


def optional_auth(
    request: Request,
    response: Response,
    access_token: str = Cookie(None, alias="access_token"),
) -> dict:
    """Dev-toggle auth dependency."""
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    return get_current_user_with_refresh(request, response, access_token)


def _int_or_none(value):
    return int(value) if value not in (None, "") else None


def _setup_options(db: Session, co_id: int):
    machines = db.execute(
        get_frame_machine_list(), {"machine_type_id": DRAWING_MACHINE_TYPE_ID}
    ).fetchall()
    branches = db.execute(get_branch_list(co_id=co_id), {"co_id": co_id}).fetchall()
    return {
        "machines": [dict(r._mapping) for r in machines],
        "branches": [dict(r._mapping) for r in branches],
    }


@router.get("/drawing_create_setup")
async def drawing_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return machine + branch dropdown options for create form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        return {"data": _setup_options(db, int(co_id))}
    except HTTPException:
        raise
    except Exception as e:
        print(f"drawing_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawing_table")
async def drawing_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated drawing master list with optional search."""
    try:
        search_param = f"%{search}%" if search else None
        rows = db.execute(get_drawing_mst_list(), {"search": search_param}).fetchall()
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
    except Exception as e:
        print(f"drawing_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drawing_create")
async def drawing_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new drawing master record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        mc_id = payload.get("mc_id")
        if not mc_id:
            raise HTTPException(status_code=400, detail="Machine (mc_id) is required")

        dup_row = db.execute(
            check_drawing_mst_exists(), {"mc_id": int(mc_id)}
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Drawing master already exists for this Machine",
            )

        record = TblDrawingMst(
            mc_id=int(mc_id),
            const_meter=_int_or_none(payload.get("const_meter")),
            drg_type=_int_or_none(payload.get("drg_type")),
            short_name=payload.get("short_name") or None,
            shed_type=payload.get("shed_type") or None,
            branch_id=_int_or_none(payload.get("branch_id")),
            meter_type=_int_or_none(payload.get("meter_type")) if payload.get("meter_type") not in (None, "") else 1,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Drawing master created successfully",
            "drg_mst_id": record.drg_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"drawing_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/drawing_edit_setup")
async def drawing_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + dropdown options for edit form."""
    try:
        co_id = request.query_params.get("co_id")
        drg_mst_id = request.query_params.get("drg_mst_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not drg_mst_id:
            raise HTTPException(status_code=400, detail="drg_mst_id is required")

        row = db.execute(
            get_drawing_mst_by_id(), {"drg_mst_id": int(drg_mst_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Drawing master not found")

        return {
            "data": {
                "drawing_details": dict(row._mapping),
                **_setup_options(db, int(co_id)),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"drawing_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/drawing_edit", methods=["POST", "PUT"])
async def drawing_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing drawing master record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        drg_mst_id = payload.get("drg_mst_id")
        if not drg_mst_id:
            raise HTTPException(status_code=400, detail="drg_mst_id is required")

        existing = (
            db.query(TblDrawingMst)
            .filter(TblDrawingMst.drg_mst_id == int(drg_mst_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Drawing master not found")

        mc_id = payload.get("mc_id")
        target_mc = int(mc_id) if mc_id not in (None, "") else existing.mc_id
        if target_mc:
            dup_row = db.execute(
                check_drawing_mst_exists(int(drg_mst_id)),
                {"mc_id": target_mc, "exclude_id": int(drg_mst_id)},
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Drawing master already exists for this Machine",
                )

        if mc_id not in (None, ""):
            existing.mc_id = int(mc_id)
        if "const_meter" in payload:
            existing.const_meter = _int_or_none(payload["const_meter"])
        if "drg_type" in payload:
            existing.drg_type = _int_or_none(payload["drg_type"])
        if "short_name" in payload:
            existing.short_name = payload["short_name"] or None
        if "shed_type" in payload:
            existing.shed_type = payload["shed_type"] or None
        if "branch_id" in payload:
            existing.branch_id = _int_or_none(payload["branch_id"])
        if payload.get("meter_type") not in (None, ""):
            existing.meter_type = int(payload["meter_type"])
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "message": "Drawing master updated successfully",
            "drg_mst_id": existing.drg_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"drawing_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
