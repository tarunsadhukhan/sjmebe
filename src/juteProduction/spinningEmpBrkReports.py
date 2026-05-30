"""
Jute Production - Spinning Employee/Frame Break-up Efficiency Report endpoint.

Backs the frontend page at
    /dashboardportal/productionReports/spinningempbrkReports

A single flat detail listing (one row per date / shift / frame). See
spinningEmpBrkReportQueries.py for the SQL and the best-effort column TODOs.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import ValidationError

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.spinningEmpBrkReportQueries import (
    get_spinning_emp_brk_detail_query,
)
from src.juteProduction.schemas import (
    SpinningEmpBrkParams,
    SpinningEmpBrkResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_params(request: Request) -> SpinningEmpBrkParams:
    try:
        return SpinningEmpBrkParams(
            branch_id=request.query_params.get("branch_id"),
            from_date=request.query_params.get("from_date"),
            to_date=request.query_params.get("to_date"),
            shift_id=request.query_params.get("shift_id") or None,
        )
    except ValidationError as ve:
        raise HTTPException(status_code=400, detail=ve.errors())


@router.get("/detail", response_model=SpinningEmpBrkResponse)
async def get_spinning_emp_brk_detail(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Date x Shift x Frame employee break-up efficiency detail."""
    try:
        params = _parse_params(request)
        rows = db.execute(
            get_spinning_emp_brk_detail_query(),
            {
                "branch_id": params.branch_id,
                "from_date": params.from_date.isoformat(),
                "to_date": params.to_date.isoformat(),
                "shift_id": params.shift_id,
            },
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching spinning emp-brk detail: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching spinning emp-brk detail: {str(e)}",
        )
