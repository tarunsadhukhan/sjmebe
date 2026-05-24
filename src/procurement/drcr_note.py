"""
DRCR Note (Debit/Credit Note) API endpoints.
Handles manual and auto-generated debit/credit notes for rate differences and rejections.
"""
import logging
from datetime import datetime, date
from src.common.utils import now_ist
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import (
    get_drcr_note_list_query,
    get_drcr_note_count_query,
    get_drcr_note_by_id_query,
    get_drcr_note_dtl_query,
    insert_drcr_note,
    insert_drcr_note_dtl,
    update_drcr_note_status,
)
from src.procurement.inward import format_inward_no
from src.procurement.po import extract_formatted_po_no

logger = logging.getLogger(__name__)

router = APIRouter()


# Status IDs for approval workflow
STATUS_DRAFT = 21
STATUS_OPEN = 1
STATUS_PENDING_APPROVAL = 20
STATUS_APPROVED = 3
STATUS_REJECTED = 4

# DRCR Note types
DRCR_TYPE_DEBIT = 1  # Supplier owes us (rate decrease, rejected qty)
DRCR_TYPE_CREDIT = 2  # We owe supplier (rate increase)

# Debit Note reason types
DEBITNOTE_TYPE_QTY_REJECTION = 1
DEBITNOTE_TYPE_RATE_DIFF = 2


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class DrcrNoteLineItem(BaseModel):
    """Model for a single line item in a DRCR Note."""
    inward_dtl_id: int
    debitnote_type: int  # 1=qty rejection, 2=rate difference
    quantity: float
    rate: float
    discount_mode: Optional[int] = None
    discount_value: Optional[float] = None
    discount_amount: Optional[float] = None


class DrcrNoteCreateRequest(BaseModel):
    """Request body for creating a DRCR Note."""
    inward_id: int
    note_date: str
    adjustment_type: int  # 1=Debit, 2=Credit
    remarks: Optional[str] = None
    line_items: List[DrcrNoteLineItem]


class DrcrNoteStatusRequest(BaseModel):
    """Request body for status updates."""
    drcr_note_id: int


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def calculate_line_amount(line: DrcrNoteLineItem) -> float:
    """Calculate line item amount after discount."""
    gross = (line.quantity or 0) * (line.rate or 0)
    discount = line.discount_amount or 0
    return gross - discount


def format_drcr_note_no(note_id, adjustment_type, note_date) -> str:
    """Format DRCR Note number."""
    if note_id is None:
        return ""
    prefix = "DN" if adjustment_type == DRCR_TYPE_DEBIT else "CN"
    year = note_date.year if hasattr(note_date, 'year') else now_ist().year
    return f"{prefix}-{year}-{int(note_id):05d}"


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/get_drcr_note_list")
async def get_drcr_note_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
    adjustment_type: int | None = None,  # 1=Debit, 2=Credit, None=All
):
    """Return paginated list of DRCR Notes."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {
            "co_id": co_id,
            "search_like": search_like,
            "adjustment_type": adjustment_type,
            "limit": limit,
            "offset": offset,
        }

        list_query = get_drcr_note_list_query()
        rows = db.execute(list_query, params).fetchall()
        
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            
            # Format dates
            note_date_obj = mapped.get("note_date")
            note_date = note_date_obj.isoformat() if hasattr(note_date_obj, "isoformat") else note_date_obj
            
            inward_date_obj = mapped.get("inward_date")
            inward_date = inward_date_obj.isoformat() if inward_date_obj and hasattr(inward_date_obj, "isoformat") else None
            
            # Format GRN/Inward number
            raw_inward_no = mapped.get("inward_sequence_no")
            formatted_inward_no = ""
            if raw_inward_no is not None and raw_inward_no != 0:
                try:
                    formatted_inward_no = format_inward_no(
                        inward_sequence_no=int(raw_inward_no),
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        inward_date=inward_date_obj,
                    )
                except Exception:
                    formatted_inward_no = str(raw_inward_no)
            
            # Determine type label
            adj_type = mapped.get("adjustment_type")
            type_label = "Debit Note" if adj_type == DRCR_TYPE_DEBIT else "Credit Note"
            
            note_id = mapped.get("debit_credit_note_id")
            data.append({
                "drcr_note_id": note_id,
                "note_no": format_drcr_note_no(note_id, adj_type, note_date_obj),
                "note_date": note_date,
                "adjustment_type": adj_type,
                "adjustment_type_label": type_label,
                "inward_id": mapped.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": inward_date,
                "supplier_id": mapped.get("supplier_id"),
                "supplier_name": mapped.get("supplier_name") or "",
                "gross_amount": mapped.get("gross_amount") or 0,
                "net_amount": mapped.get("net_amount") or 0,
                "status_id": mapped.get("status_id"),
                "status_name": mapped.get("status_name") or "Draft",
                "auto_create": mapped.get("auto_create") == 1,
                "remarks": mapped.get("remarks") or "",
            })

        count_query = get_drcr_note_count_query()
        count_result = db.execute(count_query, params).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching DRCR Note list")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_drcr_note_by_id/{drcr_note_id}")
async def get_drcr_note_by_id(
    drcr_note_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
):
    """Get DRCR Note header and line items."""
    try:
        # Get header
        header_query = get_drcr_note_by_id_query()
        header_result = db.execute(header_query, {"drcr_note_id": drcr_note_id, "co_id": co_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="DRCR Note not found")
        
        header = dict(header_result._mapping)
        
        # Format dates
        def format_date(date_obj):
            if date_obj and hasattr(date_obj, "isoformat"):
                return date_obj.isoformat()
            return None
        
        # Format inward number
        inward_date_obj = header.get("inward_date")
        raw_inward_no = header.get("inward_sequence_no")
        formatted_inward_no = ""
        if raw_inward_no is not None and raw_inward_no != 0:
            formatted_inward_no = format_inward_no(
                inward_sequence_no=int(raw_inward_no),
                co_prefix=header.get("co_prefix"),
                branch_prefix=header.get("branch_prefix"),
                inward_date=inward_date_obj,
            )
        
        adj_type = header.get("adjustment_type")
        type_label = "Debit Note" if adj_type == DRCR_TYPE_DEBIT else "Credit Note"
        
        # Get line items
        dtl_query = get_drcr_note_dtl_query()
        dtl_result = db.execute(dtl_query, {"drcr_note_id": drcr_note_id}).fetchall()
        
        line_items = []
        for row in dtl_result:
            item = dict(row._mapping)
            item["po_no_formatted"] = extract_formatted_po_no(item) if item.get("po_no") else ""

            # Add type label
            debit_type = item.get("debitnote_type")
            if debit_type == DEBITNOTE_TYPE_QTY_REJECTION:
                item["debitnote_type_label"] = "Quantity Rejection"
            elif debit_type == DEBITNOTE_TYPE_RATE_DIFF:
                item["debitnote_type_label"] = "Rate Difference"
            else:
                item["debitnote_type_label"] = "Other"
            
            line_items.append(item)
        
        hdr_note_id = header.get("debit_credit_note_id")
        return {
            "header": {
                "drcr_note_id": hdr_note_id,
                "note_no": format_drcr_note_no(hdr_note_id, adj_type, header.get("note_date")),
                "note_date": format_date(header.get("note_date")),
                "adjustment_type": adj_type,
                "adjustment_type_label": type_label,
                "inward_id": header.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": format_date(inward_date_obj),
                "branch_id": header.get("branch_id"),
                "branch_name": header.get("branch_name") or "",
                "supplier_id": header.get("supplier_id"),
                "supplier_name": header.get("supplier_name") or "",
                "gross_amount": header.get("gross_amount") or 0,
                "net_amount": header.get("net_amount") or 0,
                "status_id": header.get("status_id"),
                "status_name": header.get("status_name") or "Draft",
                "auto_create": header.get("auto_create") == 1,
                "remarks": header.get("remarks") or "",
                "challan_no": header.get("challan_no") or "",
                "challan_date": format_date(header.get("challan_date")),
                "sr_no": header.get("sr_no") or "",
                "sr_date": format_date(header.get("sr_date")),
            },
            "line_items": line_items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/create_drcr_note")
async def create_drcr_note(
    request_body: DrcrNoteCreateRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new DRCR Note manually."""
    try:
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")
        
        now = now_ist()
        note_date = datetime.strptime(request_body.note_date, '%Y-%m-%d').date()
        
        # Calculate totals
        gross_amount = 0.0
        net_amount = 0.0
        for line in request_body.line_items:
            line_gross = (line.quantity or 0) * (line.rate or 0)
            line_net = line_gross - (line.discount_amount or 0)
            gross_amount += line_gross
            net_amount += line_net
        
        # Insert header
        insert_note = insert_drcr_note()
        db.execute(insert_note, {
            "note_date": note_date,
            "adjustment_type": request_body.adjustment_type,
            "inward_id": request_body.inward_id,
            "remarks": request_body.remarks,
            "status_id": STATUS_DRAFT,
            "auto_create": 0,  # Manual creation
            "updated_by": user_id,
            "updated_date_time": now,
            "gross_amount": gross_amount,
            "net_amount": net_amount,
        })
        
        # Get the inserted note ID
        note_id_result = db.execute(text("SELECT LAST_INSERT_ID() as id")).fetchone()
        note_id = note_id_result.id if note_id_result else None
        
        if not note_id:
            raise HTTPException(status_code=500, detail="Failed to create DRCR Note")
        
        # Insert line items
        insert_dtl = insert_drcr_note_dtl()
        for line in request_body.line_items:
            db.execute(insert_dtl, {
                "debit_credit_note_id": note_id,
                "inward_dtl_id": line.inward_dtl_id,
                "debitnote_type": line.debitnote_type,
                "quantity": line.quantity,
                "rate": line.rate,
                "discount_mode": line.discount_mode,
                "discount_value": line.discount_value,
                "discount_amount": line.discount_amount,
                "updated_by": user_id,
                "updated_date_time": now,
            })
        
        db.commit()
        
        type_label = "Debit Note" if request_body.adjustment_type == DRCR_TYPE_DEBIT else "Credit Note"
        
        return {
            "success": True,
            "message": f"{type_label} created successfully",
            "drcr_note_id": note_id,
            "note_no": format_drcr_note_no(note_id, request_body.adjustment_type, note_date),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/open_drcr_note")
async def open_drcr_note(
    request_body: DrcrNoteStatusRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open DRCR Note for approval."""
    try:
        user_id = token_data.get("user_id")
        now = now_ist()
        
        update_query = update_drcr_note_status()
        db.execute(update_query, {
            "drcr_note_id": request_body.drcr_note_id,
            "status_id": STATUS_OPEN,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {"success": True, "message": "DRCR Note opened successfully"}
    except Exception as e:
        db.rollback()
        logger.exception("Error opening DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/approve_drcr_note")
async def approve_drcr_note(
    request_body: DrcrNoteStatusRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve DRCR Note."""
    try:
        user_id = token_data.get("user_id")
        now = now_ist()
        
        # Update status to approved
        query = text("""
            UPDATE drcr_note
            SET status_id = :status_id, approved_by = :approved_by, updated_by = :updated_by, updated_date_time = :updated_date_time
            WHERE drcr_note_id = :drcr_note_id
        """)
        db.execute(query, {
            "drcr_note_id": request_body.drcr_note_id,
            "status_id": STATUS_APPROVED,
            "approved_by": user_id,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {"success": True, "message": "DRCR Note approved successfully"}
    except Exception as e:
        db.rollback()
        logger.exception("Error approving DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/reject_drcr_note")
async def reject_drcr_note(
    request_body: DrcrNoteStatusRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject DRCR Note."""
    try:
        user_id = token_data.get("user_id")
        now = now_ist()
        
        update_query = update_drcr_note_status()
        db.execute(update_query, {
            "drcr_note_id": request_body.drcr_note_id,
            "status_id": STATUS_REJECTED,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        
        db.commit()
        
        return {"success": True, "message": "DRCR Note rejected"}
    except Exception as e:
        db.rollback()
        logger.exception("Error rejecting DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/get_inward_for_drcr_note/{inward_id}")
async def get_inward_for_drcr_note(
    inward_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    co_id: int | None = None,
):
    """Get inward details for creating a manual DRCR Note."""
    try:
        # Get inward header
        header_query = text("""
            SELECT 
                i.inward_id, i.inward_sequence_no, i.inward_date,
                i.branch_id, b.branch_name,
                i.supplier_id, s.supplier_name,
                i.sr_no, i.sr_date, i.sr_status,
                i.challan_no, i.challan_date,
                c.co_prefix, b.branch_prefix
            FROM proc_inward i
            LEFT JOIN branch_master b ON i.branch_id = b.branch_id
            LEFT JOIN con_supplier_master s ON i.supplier_id = s.supplier_id
            LEFT JOIN con_company_info c ON c.co_id = :co_id
            WHERE i.inward_id = :inward_id
        """)
        header_result = db.execute(header_query, {"inward_id": inward_id, "co_id": co_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="Inward not found")
        
        header = dict(header_result._mapping)
        
        # Check SR is approved
        sr_status = header.get("sr_status")
        if sr_status != STATUS_APPROVED:
            raise HTTPException(status_code=400, detail="SR must be approved before creating DRCR Note")
        
        # Format inward number
        def format_date(date_obj):
            if date_obj and hasattr(date_obj, "isoformat"):
                return date_obj.isoformat()
            return None
        
        inward_date_obj = header.get("inward_date")
        raw_inward_no = header.get("inward_sequence_no")
        formatted_inward_no = ""
        if raw_inward_no is not None and raw_inward_no != 0:
            formatted_inward_no = format_inward_no(
                inward_sequence_no=int(raw_inward_no),
                co_prefix=header.get("co_prefix"),
                branch_prefix=header.get("branch_prefix"),
                inward_date=inward_date_obj,
            )
        
        # Get line items
        dtl_query = text("""
            SELECT 
                d.inward_dtl_id, d.item_id, d.item_make_id, d.accepted_item_make_id,
                d.inward_qty, d.rejected_qty, d.approved_qty,
                d.rate, d.accepted_rate, d.amount,
                im.item_desc, ig.item_group_desc,
                mk.make_desc,
                u.uom_name
            FROM proc_inward_dtl d
            LEFT JOIN con_item_master im ON d.item_id = im.item_id
            LEFT JOIN con_item_group ig ON im.item_group_id = ig.item_group_id
            LEFT JOIN con_item_make mk ON COALESCE(d.accepted_item_make_id, d.item_make_id) = mk.item_make_id
            LEFT JOIN con_uom_master u ON d.uom_id = u.uom_id
            WHERE d.inward_id = :inward_id
        """)
        dtl_result = db.execute(dtl_query, {"inward_id": inward_id}).fetchall()
        
        line_items = []
        for row in dtl_result:
            item = dict(row._mapping)
            line_items.append(item)
        
        return {
            "header": {
                "inward_id": header.get("inward_id"),
                "inward_no": formatted_inward_no,
                "inward_date": format_date(inward_date_obj),
                "branch_id": header.get("branch_id"),
                "branch_name": header.get("branch_name") or "",
                "supplier_id": header.get("supplier_id"),
                "supplier_name": header.get("supplier_name") or "",
                "sr_no": header.get("sr_no") or "",
                "sr_date": format_date(header.get("sr_date")),
                "challan_no": header.get("challan_no") or "",
                "challan_date": format_date(header.get("challan_date")),
            },
            "line_items": line_items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching inward for DRCR Note")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
