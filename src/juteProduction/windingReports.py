"""
Jute Production - Winding Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/windingReports.

Three pivoted views — day, fortnight, month — all share the same row shape
(emp_id, emp_code, emp_name, period_key, period_label, production,
total_hours). The frontend pivots period_key into columns.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.windingReportQueries import (
    get_winding_day_wise_query,
    get_winding_fn_wise_query,
    get_winding_month_wise_query,
    get_winding_daily_query,
)
from src.juteProduction.schemas import (
    WindingReportParams,
    WindingEmpPeriodResponse,
    WindingDailyResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> WindingReportParams:
    try:
        return WindingReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


def _run_query(db: Session, query, params: WindingReportParams):
    return db.execute(query, {
        "branch_id": params.branch_id,
        "from_date": params.from_date.isoformat(),
        "to_date": params.to_date.isoformat(),
    }).fetchall()


@router.get("/day-wise", response_model=WindingEmpPeriodResponse)
async def get_winding_day_wise(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employee x Day winding production."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_winding_day_wise_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching winding day-wise: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching winding day-wise: {str(e)}",
        )


@router.get("/fn-wise", response_model=WindingEmpPeriodResponse)
async def get_winding_fn_wise(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employee x Fortnight winding production."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_winding_fn_wise_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching winding fn-wise: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching winding fn-wise: {str(e)}",
        )


@router.get("/daily", response_model=WindingDailyResponse)
async def get_winding_daily(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x Quality x Shift winding production (No of Winders + Production)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_winding_daily_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching winding daily: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching winding daily: {str(e)}",
        )


@router.get("/month-wise", response_model=WindingEmpPeriodResponse)
async def get_winding_month_wise(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employee x Month winding production."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_winding_month_wise_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching winding month-wise: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching winding month-wise: {str(e)}",
        )
