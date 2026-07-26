"""Jute Quality Entry API endpoints.

CRUD endpoints for jute_quality_mst (new branch-scoped schema), modeled after
selector.py. Replaces the deprecated juteQuality.py which targeted the old
co_id-based schema.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import JuteQualityMst
from src.masters.query import (
    get_branch_list,
    get_jute_quality_entry_list,
    get_jute_quality_entry_by_id,
    get_jute_item_options,
    check_jute_quality_entry_exists,
)

router = APIRouter()


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


@router.get("/jute_quality_create_setup")
async def jute_quality_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return dropdown options (branches + jute items) for create form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        items = db.execute(get_jute_item_options(), {"co_id": int(co_id)}).fetchall()

        return {
            "data": {
                "branches": [dict(r._mapping) for r in branches],
                "items": [dict(r._mapping) for r in items],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"jute_quality_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_quality_table")
async def jute_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated jute quality list with optional search and branch filter."""
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

        rows = db.execute(get_jute_quality_entry_list(branch_id_int), params).fetchall()
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
        print(f"jute_quality_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jute_quality_create")
async def jute_quality_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new jute quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        jute_quality = payload.get("jute_quality")
        shr_name = payload.get("shr_name")
        branch_id = payload.get("branch_id")
        item_id = payload.get("item_id")

        if not jute_quality:
            raise HTTPException(status_code=400, detail="Jute Quality is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")

        dup_row = db.execute(
            check_jute_quality_entry_exists(),
            {"branch_id": int(branch_id), "jute_quality": jute_quality},
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Jute Quality with same name already exists for this Branch",
            )

        record = JuteQualityMst(
            jute_quality=jute_quality,
            shr_name=shr_name or None,
            branch_id=int(branch_id),
            item_id=int(item_id) if item_id not in (None, "") else None,
            active=int(payload.get("active", 1)),
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Jute Quality created successfully",
            "jute_qlty_id": record.jute_qlty_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"jute_quality_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_quality_edit_setup")
async def jute_quality_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + dropdown options for edit form."""
    try:
        co_id = request.query_params.get("co_id")
        jute_qlty_id = request.query_params.get("jute_qlty_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not jute_qlty_id:
            raise HTTPException(status_code=400, detail="jute_qlty_id is required")

        row = db.execute(
            get_jute_quality_entry_by_id(), {"jute_qlty_id": int(jute_qlty_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Jute Quality not found")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        items = db.execute(get_jute_item_options(), {"co_id": int(co_id)}).fetchall()

        return {
            "data": {
                "jute_quality_details": dict(row._mapping),
                "branches": [dict(r._mapping) for r in branches],
                "items": [dict(r._mapping) for r in items],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"jute_quality_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/jute_quality_edit", methods=["POST", "PUT"])
async def jute_quality_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing jute quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        jute_qlty_id = payload.get("jute_qlty_id")
        if not jute_qlty_id:
            raise HTTPException(status_code=400, detail="jute_qlty_id is required")

        existing = (
            db.query(JuteQualityMst)
            .filter(JuteQualityMst.jute_qlty_id == int(jute_qlty_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Jute Quality not found")

        jute_quality = payload.get("jute_quality")
        shr_name = payload.get("shr_name")
        branch_id = payload.get("branch_id")
        item_id = payload.get("item_id")

        target_branch = int(branch_id) if branch_id not in (None, "") else existing.branch_id
        target_name = jute_quality if jute_quality is not None else existing.jute_quality

        if target_branch and target_name:
            dup_row = db.execute(
                check_jute_quality_entry_exists(int(jute_qlty_id)),
                {
                    "branch_id": target_branch,
                    "jute_quality": target_name,
                    "exclude_id": int(jute_qlty_id),
                },
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Jute Quality with same name already exists for this Branch",
                )

        if jute_quality is not None:
            existing.jute_quality = jute_quality
        if shr_name is not None:
            existing.shr_name = shr_name or None
        if branch_id not in (None, ""):
            existing.branch_id = int(branch_id)
        # item_id: "" clears the item, absent key leaves it unchanged
        if "item_id" in payload:
            existing.item_id = int(item_id) if item_id not in (None, "") else None
        if payload.get("active") not in (None, ""):
            existing.active = int(payload["active"])
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "message": "Jute Quality updated successfully",
            "jute_qlty_id": existing.jute_qlty_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"jute_quality_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
