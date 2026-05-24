"""
Jute Bill Pass API endpoints.
Bill Pass is a view of approved Jute Material Receipts (MRs) with invoice details.
This module provides endpoints for viewing and updating bill pass records from the jute_mr table.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from typing import Optional, List
from pydantic import BaseModel
import logging
from datetime import datetime
from src.common.utils import now_ist
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_bill_pass_table_query,
    get_jute_bill_pass_table_count_query,
    get_jute_bill_pass_by_id_query,
    get_jute_mr_line_items_query,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# CONSTANTS
# =============================================================================

STATUS_APPROVED = 3


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class BillPassUpdate(BaseModel):
    """Model for updating a bill pass record."""
    # Vendor Invoice Details
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None  # YYYY-MM-DD
    invoice_amount: Optional[float] = None
    invoice_received_date: Optional[str] = None  # YYYY-MM-DD
    payment_due_date: Optional[str] = None  # YYYY-MM-DD
    
    # Financial amounts
    total_amount: Optional[float] = None
    claim_amount: Optional[float] = None
    roundoff: Optional[float] = None
    net_total: Optional[float] = None
    tds_amount: Optional[float] = None
    frieght_paid: Optional[float] = None
    
    # File uploads (paths)
    invoice_upload: Optional[str] = None
    challan_upload: Optional[str] = None
    
    # Remarks
    remarks: Optional[str] = None
    
    # Complete flag
    bill_pass_complete: Optional[int] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_bill_pass_list")
async def get_jute_bill_pass_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of jute bill pass records.
    Bill passes are approved MRs (status_id = 3) with bill_pass_no assigned.
    
    Query params:
    - co_id: Company ID (required)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term
    """
    try:
        # Get query parameters
        q_co_id = request.query_params.get("co_id")
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()

        # Validate co_id
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Parse pagination
        try:
            page = max(1, int(q_page))
            limit = max(1, min(100, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit

        # Build search param
        search_param = f"%{q_search}%" if q_search else None

        # Get total count
        count_query = get_jute_bill_pass_table_count_query(co_id, q_search)
        count_params = {"co_id": co_id}
        if search_param:
            count_params["search"] = search_param

        count_result = db.execute(count_query, count_params).fetchone()
        total = count_result[0] if count_result else 0

        # Get data
        data_query = get_jute_bill_pass_table_query(co_id, q_search)
        data_params = {
            "co_id": co_id,
            "limit": limit,
            "offset": offset,
        }
        if search_param:
            data_params["search"] = search_param

        rows = db.execute(data_query, data_params).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute bill pass list: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bill_pass_by_id")
async def get_jute_bill_pass_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute bill pass (approved MR) by ID.
    
    Query params:
    - co_id: Company ID (required)
    - id: Bill Pass / MR ID (required)
    """
    try:
        # Get query parameters
        q_co_id = request.query_params.get("co_id")
        q_id = request.query_params.get("id")

        # Validate required params
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")

        try:
            co_id = int(q_co_id)
            mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id or id")

        # Get bill pass details
        query = get_jute_bill_pass_by_id_query()
        result = db.execute(query, {"co_id": co_id, "jute_mr_id": mr_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Bill pass not found")

        return dict(result._mapping)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching jute bill pass by ID: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_bill_pass_line_items")
async def get_jute_bill_pass_line_items(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get line items for a bill pass (approved MR).
    
    Query params:
    - co_id: Company ID (required)
    - id: Bill Pass / MR ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_id = request.query_params.get("id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")

        try:
            co_id = int(q_co_id)
            mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id or id")

        query = get_jute_mr_line_items_query()
        rows = db.execute(query, {"mr_id": mr_id}).fetchall()
        data = [dict(r._mapping) for r in rows]

        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching bill pass line items: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_bill_pass/{bill_pass_id}")
async def update_jute_bill_pass(
    bill_pass_id: int,
    body: BillPassUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update a bill pass record with invoice details and financial information.
    
    Path params:
    - bill_pass_id: The jute_mr_id of the bill pass to update
    
    Query params:
    - co_id: Company ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")
        user_id = token_data.get("user_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        if not user_id:
            raise HTTPException(status_code=401, detail="User not authenticated")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Verify bill pass exists and is approved
        verify_query = text("""
            SELECT jm.jute_mr_id, jm.status_id
            FROM jute_mr jm
            INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
            WHERE jm.jute_mr_id = :bill_pass_id
            AND bm.co_id = :co_id
            AND jm.status_id = 3
        """)
        result = db.execute(verify_query, {"bill_pass_id": bill_pass_id, "co_id": co_id}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Bill pass not found or not in approved status")

        now = now_ist()

        # Build dynamic update query
        update_fields = ["updated_by = :updated_by", "updated_date_time = :updated_date_time"]
        update_params = {
            "bill_pass_id": bill_pass_id,
            "updated_by": user_id,
            "updated_date_time": now,
        }

        # Add invoice fields if provided
        if body.invoice_no is not None:
            update_fields.append("invoice_no = :invoice_no")
            update_params["invoice_no"] = body.invoice_no

        if body.invoice_date is not None:
            update_fields.append("invoice_date = :invoice_date")
            update_params["invoice_date"] = body.invoice_date if body.invoice_date else None

        if body.invoice_amount is not None:
            update_fields.append("invoice_amount = :invoice_amount")
            update_params["invoice_amount"] = body.invoice_amount

        if body.invoice_received_date is not None:
            update_fields.append("invoice_received_date = :invoice_received_date")
            update_params["invoice_received_date"] = body.invoice_received_date if body.invoice_received_date else None

        if body.payment_due_date is not None:
            update_fields.append("payment_due_date = :payment_due_date")
            update_params["payment_due_date"] = body.payment_due_date if body.payment_due_date else None

        # Add financial fields if provided (round to 2 decimal places for currency precision)
        if body.total_amount is not None:
            update_fields.append("total_amount = :total_amount")
            update_params["total_amount"] = round(body.total_amount, 2)

        if body.claim_amount is not None:
            update_fields.append("claim_amount = :claim_amount")
            update_params["claim_amount"] = round(body.claim_amount, 2)

        if body.roundoff is not None:
            update_fields.append("roundoff = :roundoff")
            update_params["roundoff"] = round(body.roundoff, 2)

        if body.net_total is not None:
            update_fields.append("net_total = :net_total")
            update_params["net_total"] = round(body.net_total, 2)

        if body.tds_amount is not None:
            update_fields.append("tds_amount = :tds_amount")
            update_params["tds_amount"] = round(body.tds_amount, 2)

        if body.frieght_paid is not None:
            update_fields.append("frieght_paid = :frieght_paid")
            update_params["frieght_paid"] = round(body.frieght_paid, 2)

        # Add file upload fields if provided
        if body.invoice_upload is not None:
            update_fields.append("invoice_upload = :invoice_upload")
            update_params["invoice_upload"] = body.invoice_upload

        if body.challan_upload is not None:
            update_fields.append("challan_upload = :challan_upload")
            update_params["challan_upload"] = body.challan_upload

        # Add remarks if provided
        if body.remarks is not None:
            update_fields.append("remarks = :remarks")
            update_params["remarks"] = body.remarks

        # Add complete flag if provided
        if body.bill_pass_complete is not None:
            update_fields.append("bill_pass_complete = :bill_pass_complete")
            update_params["bill_pass_complete"] = body.bill_pass_complete

        update_query = text(f"""
            UPDATE jute_mr
            SET {', '.join(update_fields)}
            WHERE jute_mr_id = :bill_pass_id
        """)
        
        db.execute(update_query, update_params)
        db.commit()

        return {
            "success": True,
            "message": "Bill pass updated successfully",
            "bill_pass_id": bill_pass_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating bill pass")
        raise HTTPException(status_code=500, detail=str(e))
