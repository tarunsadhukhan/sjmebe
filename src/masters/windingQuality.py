"""Winding Quality Master API endpoints.

CRUD endpoints for winding_quality_master, modeled after spinningQuality.py.
No branch/company scoping — the table is a flat quality list.
"""

import os
from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.common.utils import now_ist
from src.models.jute import WindingQualityMst
from src.masters.query import (
    get_winding_quality_list,
    get_winding_quality_by_id,
    check_winding_quality_exists,
)

router = APIRouter()

SPOOL_COP_VALUES = ("S", "C")


def optional_auth(
    request: Request,
    response: Response,
    access_token: str = Cookie(None, alias="access_token"),
) -> dict:
    """Dev-toggle auth dependency (matches spinningQuality.optional_auth)."""
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/winding_quality_table")
async def winding_quality_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str = None,
):
    """Paginated winding quality list with optional search."""
    try:
        search_param = f"%{search}%" if search else None
        rows = db.execute(
            get_winding_quality_list(), {"search": search_param}
        ).fetchall()
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
        print(f"winding_quality_table error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/winding_quality_create")
async def winding_quality_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Create a new winding quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        wng_quality = payload.get("wng_quality")
        target_prod = payload.get("target_prod")
        spool_cop = payload.get("spool_cop")

        if not wng_quality:
            raise HTTPException(status_code=400, detail="Winding quality is required")
        if spool_cop and spool_cop not in SPOOL_COP_VALUES:
            raise HTTPException(status_code=400, detail="Spool/Cop must be 'S' or 'C'")

        dup_row = db.execute(
            check_winding_quality_exists(),
            {"wng_quality": wng_quality, "spool_cop": spool_cop},
        ).fetchone()
        if dup_row and dup_row._mapping.get("count", 0) > 0:
            raise HTTPException(
                status_code=409,
                detail="Winding quality with same name and Spool/Cop already exists",
            )

        record = WindingQualityMst(
            wng_quality=wng_quality,
            target_prod=int(target_prod) if target_prod not in (None, "") else None,
            spool_cop=spool_cop or None,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        response.status_code = 201
        return {
            "message": "Winding quality created successfully",
            "wng_quality_mst_id": record.wng_quality_mst_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"winding_quality_create error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/winding_quality_edit_setup")
async def winding_quality_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return record details for the edit form."""
    try:
        wng_quality_mst_id = request.query_params.get("wng_quality_mst_id")
        if not wng_quality_mst_id:
            raise HTTPException(status_code=400, detail="wng_quality_mst_id is required")

        row = db.execute(
            get_winding_quality_by_id(),
            {"wng_quality_mst_id": int(wng_quality_mst_id)},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Winding quality not found")

        return {"data": {"winding_quality_details": dict(row._mapping)}}
    except HTTPException:
        raise
    except Exception as e:
        print(f"winding_quality_edit_setup error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.api_route("/winding_quality_edit", methods=["POST", "PUT"])
async def winding_quality_edit(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth),
):
    """Edit an existing winding quality record."""
    try:
        user_id = (token_data or {}).get("user_id") or payload.get("updated_by")

        wng_quality_mst_id = payload.get("wng_quality_mst_id")
        if not wng_quality_mst_id:
            raise HTTPException(status_code=400, detail="wng_quality_mst_id is required")

        existing = (
            db.query(WindingQualityMst)
            .filter(WindingQualityMst.wng_quality_mst_id == int(wng_quality_mst_id))
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Winding quality not found")

        wng_quality = payload.get("wng_quality")
        target_prod = payload.get("target_prod")
        spool_cop = payload.get("spool_cop")

        if spool_cop and spool_cop not in SPOOL_COP_VALUES:
            raise HTTPException(status_code=400, detail="Spool/Cop must be 'S' or 'C'")

        target_name = wng_quality if wng_quality is not None else existing.wng_quality
        target_spool = spool_cop if spool_cop is not None else existing.spool_cop

        if target_name is not None:
            dup_row = db.execute(
                check_winding_quality_exists(int(wng_quality_mst_id)),
                {
                    "wng_quality": target_name,
                    "spool_cop": target_spool,
                    "exclude_id": int(wng_quality_mst_id),
                },
            ).fetchone()
            if dup_row and dup_row._mapping.get("count", 0) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="Winding quality with same name and Spool/Cop already exists",
                )

        if wng_quality is not None:
            existing.wng_quality = wng_quality
        if target_prod not in (None, ""):
            existing.target_prod = int(target_prod)
        if spool_cop is not None:
            existing.spool_cop = spool_cop or None
        if user_id and str(user_id).isdigit():
            existing.updated_by = int(user_id)
        existing.updated_date_time = now_ist()

        db.commit()
        db.refresh(existing)
        return {
            "data": {
                "message": "Winding quality updated successfully",
                "wng_quality_mst_id": existing.wng_quality_mst_id,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"winding_quality_edit error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))
