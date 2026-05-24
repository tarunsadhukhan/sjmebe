"""
Inventory Report endpoints.
Provides endpoints for inventory stock position and item-wise issue reports.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.inventory.reportQueries import (
    get_inventory_stock_report_query,
    get_inventory_stock_report_count_query,
    get_issue_itemwise_report_query,
    get_issue_itemwise_report_count_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/inventory-stock")
async def get_inventory_stock_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    item_grp_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """
    Inventory stock position report.

    Returns one row per item with opening, receipt, issue, and closing
    quantities over a date range.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional)
    - item_grp_id: Item Group ID (optional)
    - date_from: Start date YYYY-MM-DD (required)
    - date_to: End date YYYY-MM-DD (required)
    - search: Search term for item name, item group
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not date_from:
            raise HTTPException(status_code=400, detail="date_from is required")
        if not date_to:
            raise HTTPException(status_code=400, detail="date_to is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from,
            "date_to": date_to,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_inventory_stock_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            data.append({
                "item_id": mapped.get("item_id"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "opening_qty": mapped.get("opening_qty"),
                "receipt_qty": mapped.get("receipt_qty"),
                "issue_qty": mapped.get("issue_qty"),
                "closing_qty": mapped.get("closing_qty"),
            })

        count_query = get_inventory_stock_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from,
            "date_to": date_to,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching inventory stock report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/issue-itemwise")
async def get_issue_itemwise_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    co_id: int | None = None,
    branch_id: int | None = None,
    item_grp_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    """
    Item-wise issue report.

    Returns one row per issue line item with issue header info,
    item details, department, cost factor, and machine.

    Query params:
    - co_id: Company ID (required)
    - branch_id: Branch ID (optional)
    - item_grp_id: Item Group ID (optional)
    - date_from: Start date YYYY-MM-DD (optional)
    - date_to: End date YYYY-MM-DD (optional)
    - search: Search term for item name, branch name, item group, department
    - page: Page number (default 1)
    - limit: Page size (default 10, max 10000)
    """
    try:
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(page, 1)
        limit = max(min(limit, 10000), 1)
        offset = (page - 1) * limit

        search_like = None
        if search:
            search_like = f"%{search.strip()}%"

        params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_issue_itemwise_report_query()
        rows = db.execute(list_query, params).fetchall()

        data = []
        for row in rows:
            mapped = dict(row._mapping)
            issue_date_obj = mapped.get("issue_date")
            issue_date = issue_date_obj
            if hasattr(issue_date_obj, "isoformat"):
                issue_date = issue_date_obj.isoformat()

            # Format issue number using print_no if available, else pass_no
            issue_no = mapped.get("issue_pass_print_no") or ""
            if not issue_no:
                raw_no = mapped.get("issue_pass_no")
                if raw_no is not None:
                    issue_no = str(raw_no)

            data.append({
                "issue_li_id": mapped.get("issue_li_id"),
                "issue_id": mapped.get("issue_id"),
                "issue_no": issue_no,
                "issue_date": issue_date,
                "branch_name": mapped.get("branch_name"),
                "department": mapped.get("department"),
                "item_name": mapped.get("item_name"),
                "item_grp_name": mapped.get("item_grp_name"),
                "uom_name": mapped.get("uom_name"),
                "req_quantity": mapped.get("req_quantity"),
                "issue_qty": mapped.get("issue_qty"),
                "expense_type_name": mapped.get("expense_type_name"),
                "cost_factor_name": mapped.get("cost_factor_name"),
                "machine_name": mapped.get("machine_name"),
                "status_name": mapped.get("status_name"),
            })

        count_query = get_issue_itemwise_report_count_query()
        count_params = {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "item_grp_id": int(item_grp_id) if item_grp_id else None,
            "date_from": date_from if date_from else None,
            "date_to": date_to if date_to else None,
            "search_like": search_like,
        }
        count_result = db.execute(count_query, count_params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching issue itemwise report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
