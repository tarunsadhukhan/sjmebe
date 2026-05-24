"""
Jute Production - Bales Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/balesReports.

Returns per-day (quality, customer) opening / production / issue / closing,
computed from tbl_daily_bales_transaction using running-balance window
functions. See balesReportQueries.py for SQL details.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.balesReportQueries import get_bales_entries_query
from src.juteProduction.schemas import (
    BalesReportParams,
    BalesEntryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> BalesReportParams:
    try:
        return BalesReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


def _run_query(db: Session, query, params: BalesReportParams):
    return db.execute(query, {
        "branch_id": params.branch_id,
        "from_date": params.from_date.isoformat(),
        "to_date": params.to_date.isoformat(),
    }).fetchall()


@router.get("/entries", response_model=BalesEntryResponse)
async def get_bales_entries(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x Quality x Customer bales movement (opening/prod/issue/closing)."""
    try:
        params = _parse_params(request)
        rows = _run_query(db, get_bales_entries_query(), params)
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bales entries: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching bales entries: {str(e)}",
        )
