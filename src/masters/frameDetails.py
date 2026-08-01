"""Frame Details Master API endpoints.

CRUD endpoints for frame_details_mst, modeled after trolly.py.
Frame No options come from machine_mst where machine_type_id = SPINNING_FRAME_TYPE_ID.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import FrameDetailsMst
from src.masters.query import (
    get_frame_machine_list,
    get_frame_details_list,
    get_frame_details_by_id,
    check_frame_details_exists,
)

router = APIRouter()

SPINNING_FRAME_TYPE_ID = 36


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


@router.get("/frame_create_setup")
async def frame_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return Frame No dropdown options (spinning-frame machines)."""
    try:
        machines = db.execute(
            get_frame_machine_list(), {"machine_type_id": SPINNING_FRAME_TYPE_ID}
        ).fetchall()
        return {"data": {"machines": [dict(r._mapping) for r in machines]}}
    except Exception as e:
        print(f"frame_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frame_table")
async def frame_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated frame details list with optional search."""
    try:
        search_param = f"%{search}%" if search else None
        rows = db.execute(get_frame_details_list(), {"search": search_param}).fetchall()
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
        print(f"frame_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/frame_create")
async def frame_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new frame details record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        mc_id = payload.get("mc_id")
        if not mc_id:
            raise HTTPException(status_code=400, detail="Frame No (mc_id) is required")

        dup_row = db.execute(
            check_frame_details_exists(), {"mc_id": int(mc_id)}
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Frame details already exist for this Frame No",
            )

        record = FrameDetailsMst(
            mc_id=int(mc_id),
            speed=_int_or_none(payload.get("speed")),
            frame_type=payload.get("frame_type") or None,
            bobbin_weight=_int_or_none(payload.get("bobbin_weight")),
            no_of_spindle=_int_or_none(payload.get("no_of_spindle")),
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Frame details created successfully",
            "frame_details_mst_id": record.frame_details_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"frame_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frame_edit_setup")
async def frame_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + Frame No dropdown options for edit form."""
    try:
        frame_details_mst_id = request.query_params.get("frame_details_mst_id")
        if not frame_details_mst_id:
            raise HTTPException(status_code=400, detail="frame_details_mst_id is required")

        row = db.execute(
            get_frame_details_by_id(),
            {"frame_details_mst_id": int(frame_details_mst_id)},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Frame details not found")

        machines = db.execute(
            get_frame_machine_list(), {"machine_type_id": SPINNING_FRAME_TYPE_ID}
        ).fetchall()

        return {
            "data": {
                "frame_details": dict(row._mapping),
                "machines": [dict(r._mapping) for r in machines],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"frame_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/frame_edit", methods=["POST", "PUT"])
async def frame_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing frame details record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        frame_details_mst_id = payload.get("frame_details_mst_id")
        if not frame_details_mst_id:
            raise HTTPException(status_code=400, detail="frame_details_mst_id is required")

        existing = (
            db.query(FrameDetailsMst)
            .filter(FrameDetailsMst.frame_details_mst_id == int(frame_details_mst_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Frame details not found")

        mc_id = payload.get("mc_id")
        target_mc = int(mc_id) if mc_id not in (None, "") else existing.mc_id
        if target_mc:
            dup_row = db.execute(
                check_frame_details_exists(int(frame_details_mst_id)),
                {"mc_id": target_mc, "exclude_id": int(frame_details_mst_id)},
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Frame details already exist for this Frame No",
                )

        if mc_id not in (None, ""):
            existing.mc_id = int(mc_id)
        if "speed" in payload:
            existing.speed = _int_or_none(payload["speed"])
        if "frame_type" in payload:
            existing.frame_type = payload["frame_type"] or None
        if "bobbin_weight" in payload:
            existing.bobbin_weight = _int_or_none(payload["bobbin_weight"])
        if "no_of_spindle" in payload:
            existing.no_of_spindle = _int_or_none(payload["no_of_spindle"])
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "message": "Frame details updated successfully",
            "frame_details_mst_id": existing.frame_details_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"frame_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
