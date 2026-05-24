"""
Jute Procurement Report endpoints.
Provides endpoints for jute stock and related reports.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.reportQueries import (
    get_jute_stock_report_query,
    get_batch_cost_report_query,
    get_jute_summary_report_query,
    get_jute_details_report_query,
)
from src.juteProcurement.schemas import (
    JuteSummaryReportParams,
    JuteSummaryReportResponse,
    JuteDetailsReportResponse,
)
from pydantic import ValidationError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stock")
async def get_jute_stock_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get daily jute stock position report for a given branch and date.

    Returns opening stock, receipt, issue, closing stock, and MTD receipt/issue
    grouped by item group and item.

    Query params:
    - branch_id: Branch ID (required)
    - date: Report date in YYYY-MM-DD format (required)
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_date = request.query_params.get("date")

        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not q_date:
            raise HTTPException(status_code=400, detail="date is required")

        try:
            branch_id = int(q_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        query = get_jute_stock_report_query()
        rows = db.execute(query, {
            "branch_id": branch_id,
            "report_date": q_date,
        }).fetchall()

        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute stock report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching jute stock report: {str(e)}",
        )


@router.get("/batch-cost")
async def get_batch_cost_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get batch cost report: yarn quality-wise planned vs actual jute issue.

    Compares planned issue (from batch daily assignments + batch plan percentages)
    against actual issue for a given branch and date. Returns planned weight,
    actual weight, average rate, issue value, and variance per quality.

    Query params:
    - branch_id: Branch ID (required)
    - date: Report date in YYYY-MM-DD format (required)
    """
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_date = request.query_params.get("date")

        if not q_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not q_date:
            raise HTTPException(status_code=400, detail="date is required")

        try:
            branch_id = int(q_branch_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid branch_id")

        query = get_batch_cost_report_query()
        rows = db.execute(query, {
            "branch_id": branch_id,
            "report_date": q_date,
        }).fetchall()

        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch cost report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching batch cost report: {str(e)}",
        )


@router.get("/summary", response_model=JuteSummaryReportResponse)
async def get_jute_summary_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Date-wise jute summary report for a given branch and date range.

    Sources:
      - tbl_jute_received (recv_date, weight, branch_id) for Purchase.
      - tbl_daily_sperder (tran_date, issue, branch_id) for Issue; weight = issue * 60.

    Query params:
    - branch_id: Branch ID (required, > 0)
    - from_date: Start date YYYY-MM-DD (required)
    - to_date:   End date   YYYY-MM-DD (required)
    """
    try:
        try:
            params = JuteSummaryReportParams(
                branch_id=request.query_params.get("branch_id"),
                from_date=request.query_params.get("from_date"),
                to_date=request.query_params.get("to_date"),
            )
        except ValidationError as ve:
            raise HTTPException(status_code=400, detail=ve.errors())

        rows = db.execute(get_jute_summary_report_query(), {
            "branch_id": params.branch_id,
            "from_date": params.from_date.isoformat(),
            "to_date": params.to_date.isoformat(),
        }).fetchall()

        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute summary report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching jute summary report: {str(e)}",
        )


@router.get("/details", response_model=JuteDetailsReportResponse)
async def get_jute_details_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Date + quality-wise jute details report for a given branch and date range.

    Returns one row per (date, quality) with opening, purchase, issue and closing
    weights. Frontend groups by date and adds per-day total rows.

    Query params:
    - branch_id: Branch ID (required, > 0)
    - from_date: Start date YYYY-MM-DD (required)
    - to_date:   End date   YYYY-MM-DD (required)
    """
    try:
        try:
            params = JuteSummaryReportParams(
                branch_id=request.query_params.get("branch_id"),
                from_date=request.query_params.get("from_date"),
                to_date=request.query_params.get("to_date"),
            )
        except ValidationError as ve:
            raise HTTPException(status_code=400, detail=ve.errors())

        rows = db.execute(get_jute_details_report_query(), {
            "branch_id": params.branch_id,
            "from_date": params.from_date.isoformat(),
            "to_date": params.to_date.isoformat(),
        }).fetchall()

        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute details report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching jute details report: {str(e)}",
        )
