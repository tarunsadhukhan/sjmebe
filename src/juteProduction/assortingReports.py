"""
Jute Production - Assorting Report endpoints.

Backs the frontend page at /dashboardportal/productionReports/assortingReports.

Returns per-entry assorting weighments (date, shed, machine, selector,
quality, trolly, gross/tare/net) from assorting_entry. See
assortingReportQueries.py for SQL details.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.assortingReportQueries import get_assorting_entries_query
from src.juteProduction.schemas import (
    AssortingReportParams,
    AssortingEntryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> AssortingReportParams:
    try:
        return AssortingReportParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


@router.get("/entries", response_model=AssortingEntryResponse)
async def get_assorting_entries(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Entry-wise assorting weighments for a branch and date range."""
    try:
        params = _parse_params(request)
        rows = db.execute(get_assorting_entries_query(), {
            "branch_id": params.branch_id,
            "from_date": params.from_date.isoformat(),
            "to_date": params.to_date.isoformat(),
        }).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assorting entries: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching assorting entries: {str(e)}",
        )
