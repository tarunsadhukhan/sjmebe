"""
Jute Production - Drawing Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/drawingReports.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.drawingReportQueries import (
    get_drawing_summary_query,
    get_drawing_date_production_query,
    get_drawing_date_issue_query,
    get_drawing_quality_details_query,
    get_drawing_shift_matrix_query,
)
from src.juteProduction.schemas import (
    DrawingReportParams,
    DrawingSummaryResponse,
    DrawingDateProductionResponse,
    DrawingDateIssueResponse,
    DrawingQualityDetailsResponse,
    DrawingShiftMatrixResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> DrawingReportParams:
    try:
        return DrawingReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


def _run_query(db: Session, query, params: DrawingReportParams):
    return db.execute(query, {
        "branch_id": params.branch_id,
        "from_date": params.from_date.isoformat(),
        "to_date": params.to_date.isoformat(),
    }).fetchall()


@router.get("/summary", response_model=DrawingSummaryResponse)
async def get_drawing_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-wise totals across all drawing machines."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_drawing_summary_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drawing summary report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching drawing summary report: {str(e)}",
        )


@router.get("/date-production", response_model=DrawingDateProductionResponse)
async def get_drawing_date_production(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x machine production rows (frontend pivots)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_drawing_date_production_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drawing date-wise production: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching drawing date-wise production: {str(e)}",
        )


@router.get("/date-issue", response_model=DrawingDateIssueResponse)
async def get_drawing_date_issue(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x machine output rows for the pivot view."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_drawing_date_issue_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drawing date-wise issue: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching drawing date-wise issue: {str(e)}",
        )


@router.get("/shift-matrix", response_model=DrawingShiftMatrixResponse)
async def get_drawing_shift_matrix(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Machine x shift matrix (OP / CL / Unit / Eff per shift, plus Overall)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_drawing_shift_matrix_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drawing shift matrix: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching drawing shift matrix: {str(e)}",
        )


@router.get("/quality-details", response_model=DrawingQualityDetailsResponse)
async def get_drawing_quality_details(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-machine totals over the range."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_drawing_quality_details_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching drawing machine-wise details: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching drawing machine-wise details: {str(e)}",
        )
