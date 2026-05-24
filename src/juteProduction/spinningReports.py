"""
Jute Production - Spinning Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/spinningReports.

All queries are currently placeholders (return empty data sets). Replace the
SQL in spinningReportQueries.py once the spinning transaction tables are
finalized — the response shapes here are stable and frontend code already
pivots them correctly.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.spinningReportQueries import (
    get_spinning_production_eff_query,
    get_spinning_mc_date_query,
    get_spinning_emp_date_query,
    get_spinning_frame_running_query,
    get_spinning_running_hours_eff_query,
)
from src.juteProduction.schemas import (
    SpinningReportParams,
    SpinningProductionEffResponse,
    SpinningMcDateResponse,
    SpinningEmpDateResponse,
    SpinningFrameRunningResponse,
    SpinningRunningHoursEffResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> SpinningReportParams:
    try:
        return SpinningReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


def _run_query(db: Session, query, params: SpinningReportParams):
    return db.execute(query, {
        "branch_id": params.branch_id,
        "from_date": params.from_date.isoformat(),
        "to_date": params.to_date.isoformat(),
    }).fetchall()


@router.get("/production-eff", response_model=SpinningProductionEffResponse)
async def get_spinning_production_eff(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x Quality x Shift production and efficiency."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spinning_production_eff_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning production-eff: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning production-eff: {str(e)}",
        )


@router.get("/mc-date", response_model=SpinningMcDateResponse)
async def get_spinning_mc_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Machine x Date production and efficiency."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spinning_mc_date_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning mc-date: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning mc-date: {str(e)}",
        )


@router.get("/emp-date", response_model=SpinningEmpDateResponse)
async def get_spinning_emp_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Employee x Date production and efficiency."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spinning_emp_date_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning emp-date: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning emp-date: {str(e)}",
        )


@router.get("/frame-running", response_model=SpinningFrameRunningResponse)
async def get_spinning_frame_running(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Frame-wise running hours / efficiency over the range."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spinning_frame_running_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning frame-running: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning frame-running: {str(e)}",
        )


@router.get("/running-hours-eff", response_model=SpinningRunningHoursEffResponse)
async def get_spinning_running_hours_eff(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per (machine, quality) production efficiency on running-hours basis."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_spinning_running_hours_eff_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning running-hours-eff: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning running-hours-eff: {str(e)}",
        )
