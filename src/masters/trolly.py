"""Trolly Master API endpoints.

CRUD endpoints for trolly_mst, modeled after spinningQuality.py.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import TrollyMst
from src.masters.query import (
    get_branch_list,
    get_dept_list,
    get_trolly_list,
    get_trolly_by_id,
    check_trolly_exists,
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


@router.get("/trolly_create_setup")
async def trolly_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return dropdown options (branches + departments) for create form."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        depts = db.execute(get_dept_list()).fetchall()

        return {
            "data": {
                "branches": [dict(r._mapping) for r in branches],
                "departments": [dict(r._mapping) for r in depts],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"trolly_create_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trolly_table")
async def trolly_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated trolly list with optional search and branch filter."""
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

        rows = db.execute(get_trolly_list(branch_id_int), params).fetchall()
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
        print(f"trolly_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trolly_create")
async def trolly_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new trolly record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        trolly_name = payload.get("trolly_name")
        branch_id = payload.get("branch_id")
        dept_id = payload.get("dept_id")
        trolly_weight = payload.get("trolly_weight")
        busket_weight = payload.get("busket_weight")

        if not trolly_name:
            raise HTTPException(status_code=400, detail="Trolly name is required")
        if not branch_id:
            raise HTTPException(status_code=400, detail="Branch is required")
        if not dept_id:
            raise HTTPException(status_code=400, detail="Department is required")

        dup_row = db.execute(
            check_trolly_exists(int(branch_id), int(dept_id), trolly_name),
            {
                "branch_id": int(branch_id),
                "dept_id": int(dept_id),
                "trolly_name": trolly_name,
            },
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Trolly with same name already exists for this Branch and Department",
            )

        record = TrollyMst(
            trolly_name=trolly_name,
            trolly_weight=float(trolly_weight) if trolly_weight not in (None, "") else None,
            busket_weight=float(busket_weight) if busket_weight not in (None, "") else None,
            branch_id=int(branch_id),
            dept_id=int(dept_id),
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Trolly created successfully",
            "trolly_id": record.trolly_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"trolly_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trolly_edit_setup")
async def trolly_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details + dropdown options for edit form."""
    try:
        co_id = request.query_params.get("co_id")
        trolly_id = request.query_params.get("trolly_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not trolly_id:
            raise HTTPException(status_code=400, detail="trolly_id is required")

        row = db.execute(
            get_trolly_by_id(), {"trolly_id": int(trolly_id)}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Trolly not found")

        branches = db.execute(
            get_branch_list(co_id=int(co_id)), {"co_id": int(co_id)}
        ).fetchall()
        depts = db.execute(get_dept_list()).fetchall()

        return {
            "data": {
                "trolly_details": dict(row._mapping),
                "branches": [dict(r._mapping) for r in branches],
                "departments": [dict(r._mapping) for r in depts],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"trolly_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/trolly_edit", methods=["POST", "PUT"])
async def trolly_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing trolly record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        trolly_id = payload.get("trolly_id")
        if not trolly_id:
            raise HTTPException(status_code=400, detail="trolly_id is required")

        existing = (
            db.query(TrollyMst).filter(TrollyMst.trolly_id == int(trolly_id)).first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Trolly not found")

        trolly_name = payload.get("trolly_name")
        branch_id = payload.get("branch_id")
        dept_id = payload.get("dept_id")
        trolly_weight = payload.get("trolly_weight")
        busket_weight = payload.get("busket_weight")

        target_branch = int(branch_id) if branch_id not in (None, "") else existing.branch_id
        target_dept = int(dept_id) if dept_id not in (None, "") else existing.dept_id
        target_name = trolly_name if trolly_name is not None else existing.trolly_name

        if target_branch and target_dept and target_name:
            dup_row = db.execute(
                check_trolly_exists(target_branch, target_dept, target_name, int(trolly_id)),
                {
                    "branch_id": target_branch,
                    "dept_id": target_dept,
                    "trolly_name": target_name,
                    "exclude_id": int(trolly_id),
                },
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Trolly with same name already exists for this Branch and Department",
                )

        if trolly_name is not None:
            existing.trolly_name = trolly_name
        if branch_id not in (None, ""):
            existing.branch_id = int(branch_id)
        if dept_id not in (None, ""):
            existing.dept_id = int(dept_id)
        if trolly_weight not in (None, ""):
            existing.trolly_weight = float(trolly_weight)
        if busket_weight not in (None, ""):
            existing.busket_weight = float(busket_weight)
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "message": "Trolly updated successfully",
            "trolly_id": existing.trolly_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"trolly_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
