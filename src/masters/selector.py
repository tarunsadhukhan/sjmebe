"""Selector Master API endpoints.

CRUD endpoints for tbl_selector_mst, modeled after trolly.py.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import SelectorMst
from src.masters.query import (
    get_branch_list,
    get_selector_list,
    get_selector_by_id,
    get_selector_options,
    check_selector_exists,
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


@router.get("/selector_create_setup")
async def selector_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return dropdown options (branches + existing selectors) for create form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        selectors = db.execute(get_selector_options()).fetchall()

        return {
            "data": {
                "branches": [dict(r._mapping) for r in branches],
                "selectors": [dict(r._mapping) for r in selectors],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"selector_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/selector_table")
async def selector_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated selector list with optional search and branch filter."""
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

        rows = db.execute(get_selector_list(branch_id_int), params).fetchall()
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
        print(f"selector_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/selector_create")
async def selector_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new selector record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        selector_name = payload.get("selector_name")
        selector_shr_name = payload.get("selector_shr_name")
        branch_id = payload.get("branch_id")
        under_selector = payload.get("under_selector")

        if not selector_name:
            raise HTTPException(status_code=400, detail="Selector name is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")

        dup_row = db.execute(
            check_selector_exists(),
            {"branch_id": int(branch_id), "selector_name": selector_name},
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Selector with same name already exists for this Branch",
            )

        record = SelectorMst(
            selector_name=selector_name,
            selector_shr_name=selector_shr_name or None,
            branch_id=int(branch_id),
            under_selectror_master=int(under_selector) if under_selector not in (None, "") else None,
            active=int(payload.get("active", 1)),
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Selector created successfully",
            "selector_id": record.tbl_selector_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"selector_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/selector_edit_setup")
async def selector_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + dropdown options for edit form."""
    try:
        co_id = request.query_params.get("co_id")
        selector_id = request.query_params.get("selector_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not selector_id:
            raise HTTPException(status_code=400, detail="selector_id is required")

        row = db.execute(
            get_selector_by_id(), {"selector_id": int(selector_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Selector not found")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        selectors = db.execute(get_selector_options()).fetchall()

        return {
            "data": {
                "selector_details": dict(row._mapping),
                "branches": [dict(r._mapping) for r in branches],
                "selectors": [dict(r._mapping) for r in selectors],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"selector_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/selector_edit", methods=["POST", "PUT"])
async def selector_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing selector record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        selector_id = payload.get("selector_id")
        if not selector_id:
            raise HTTPException(status_code=400, detail="selector_id is required")

        existing = (
            db.query(SelectorMst)
            .filter(SelectorMst.tbl_selector_mst_id == int(selector_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Selector not found")

        selector_name = payload.get("selector_name")
        selector_shr_name = payload.get("selector_shr_name")
        branch_id = payload.get("branch_id")
        under_selector = payload.get("under_selector")

        if under_selector not in (None, "") and int(under_selector) == int(selector_id):
            raise HTTPException(status_code=400, detail="Selector cannot be under itself")

        target_branch = int(branch_id) if branch_id not in (None, "") else existing.branch_id
        target_name = selector_name if selector_name is not None else existing.selector_name

        if target_branch and target_name:
            dup_row = db.execute(
                check_selector_exists(int(selector_id)),
                {
                    "branch_id": target_branch,
                    "selector_name": target_name,
                    "exclude_id": int(selector_id),
                },
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Selector with same name already exists for this Branch",
                )

        if selector_name is not None:
            existing.selector_name = selector_name
        if selector_shr_name is not None:
            existing.selector_shr_name = selector_shr_name or None
        if branch_id not in (None, ""):
            existing.branch_id = int(branch_id)
        # under_selector: "" clears the parent, absent key leaves it unchanged
        if "under_selector" in payload:
            existing.under_selectror_master = (
                int(under_selector) if under_selector not in (None, "") else None
            )
        if payload.get("active") not in (None, ""):
            existing.active = int(payload["active"])
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "message": "Selector updated successfully",
            "selector_id": existing.tbl_selector_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"selector_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
