"""
Jute Production - Spreader Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/spreaderReports.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.reportQueries import (
    get_spreader_summary_query,
    get_spreader_date_production_query,
    get_spreader_date_issue_query,
    get_spreader_quality_details_query,
)
from src.juteProduction.schemas import (
    SpreaderReportParams,
    SpreaderSummaryResponse,
    SpreaderDateProductionResponse,
    SpreaderDateIssueResponse,
    SpreaderQualityDetailsResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> SpreaderReportParams:
    try:
        return SpreaderReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


def _run_query(db: Session, query, params: SpreaderReportParams):
    return db.execute(query, {
        "branch_id": params.branch_id,
        "from_date": params.from_date.isoformat(),
        "to_date": params.to_date.isoformat(),
    }).fetchall()


@router.get("/summary", response_model=SpreaderSummaryResponse)
async def get_spreader_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date-wise totals across all qualities/machines."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spreader_summary_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spreader summary report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spreader summary report: {str(e)}",
        )


@router.get("/date-production", response_model=SpreaderDateProductionResponse)
async def get_spreader_date_production(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x quality production rows (frontend pivots)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spreader_date_production_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spreader date-wise production: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spreader date-wise production: {str(e)}",
        )


@router.get("/date-issue", response_model=SpreaderDateIssueResponse)
async def get_spreader_date_issue(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x quality issue rows (frontend pivots)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spreader_date_issue_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spreader date-wise issue: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spreader date-wise issue: {str(e)}",
        )


@router.get("/quality-details", response_model=SpreaderQualityDetailsResponse)
async def get_spreader_quality_details(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-quality totals (production, issue, balance) over the range."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spreader_quality_details_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spreader quality-wise details: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spreader quality-wise details: {str(e)}",
        )
