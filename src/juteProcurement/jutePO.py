from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime
from src.common.utils import now_ist
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_po_table_query,
    get_jute_po_table_count_query,
    get_jute_po_by_id_query,
    get_jute_po_line_items_query,
    get_mukam_list_query,
    get_vehicle_types_query,
    get_jute_items_query,
    get_jute_qualities_by_item_query,
    get_suppliers_by_mukam_query,
    get_parties_by_supplier_query,
    get_branches_query,
    get_all_suppliers_query,
    get_jute_po_with_approval_info,
    update_jute_po_status,
)
from src.common.approval_utils import process_approval, process_rejection
from src.juteProcurement.formatters import format_jute_po_number

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# WEIGHT CALCULATION CONSTANTS
# =============================================================================

# Weight per bale in kg
WEIGHT_PER_BALE_KG = 150
# Weight per loose unit in kg
WEIGHT_PER_LOOSE_KG = 48
# Allowed variance percentage for vehicle weight validation
VEHICLE_WEIGHT_TOLERANCE_PERCENT = 5


def calculate_line_item_weight(quantity: float, jute_unit: str) -> float:
    """
    Calculate weight for a line item based on unit type.
    
    Args:
        quantity: Number of bales or loose units
        jute_unit: "BALE" or "LOOSE"
    
    Returns:
        Weight in kg
    """
    if jute_unit == "BALE":
        return WEIGHT_PER_BALE_KG * quantity
    else:
        # LOOSE
        return WEIGHT_PER_LOOSE_KG * quantity


def validate_vehicle_weight(
    total_weight_kg: float,
    vehicle_capacity_qtl: float,
    vehicle_quantity: int
) -> tuple[bool, str]:
    """
    Validate that total line item weight is within ±5% of vehicle capacity.
    
    Args:
        total_weight_kg: Total weight of all line items in kg
        vehicle_capacity_qtl: Weight capacity of one vehicle in quintals
        vehicle_quantity: Number of vehicles
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Convert total weight to quintals for comparison
    total_weight_qtl = total_weight_kg / 100
    expected_vehicle_weight_qtl = vehicle_capacity_qtl * vehicle_quantity
    
    if expected_vehicle_weight_qtl <= 0:
        return False, "Vehicle capacity not configured"
    
    if total_weight_qtl <= 0:
        return False, "No line items with weight"
    
    variance = total_weight_qtl - expected_vehicle_weight_qtl
    variance_percent = (variance / expected_vehicle_weight_qtl) * 100
    abs_variance_percent = abs(variance_percent)
    
    if abs_variance_percent > VEHICLE_WEIGHT_TOLERANCE_PERCENT:
        direction = "exceeds" if variance_percent > 0 else "is below"
        return False, (
            f"Total weight ({total_weight_qtl:.2f} Qtl) {direction} "
            f"vehicle capacity ({expected_vehicle_weight_qtl:.2f} Qtl) by {abs_variance_percent:.1f}%. "
            f"Must be within ±{VEHICLE_WEIGHT_TOLERANCE_PERCENT}%."
        )
    
    return True, ""


@router.get("/get_jute_po_table")
async def get_jute_po_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of Jute Purchase Orders.
    
    Query params:
    - co_id: Company ID (required)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term for po_num, supplier_name, broker_name, or mukam
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
            limit = min(100, max(1, int(q_limit)))  # Clamp between 1 and 100
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit

        # Build search parameter
        search_param = f"%{q_search}%" if q_search else None

        # Get total count
        count_query = get_jute_po_table_count_query(co_id=co_id, search=q_search if q_search else None)
        count_params = {"co_id": co_id}
        if search_param:
            count_params["search"] = search_param

        count_result = db.execute(count_query, count_params).fetchone()
        total = count_result.total if count_result else 0

        # Get paginated data
        data_query = get_jute_po_table_query(co_id=co_id, search=q_search if q_search else None)
        data_params = {"co_id": co_id, "limit": limit, "offset": offset}
        if search_param:
            data_params["search"] = search_param

        result = db.execute(data_query, data_params).fetchall()
        rows = [dict(r._mapping) for r in result]

        # Format dates for JSON serialization
        for row in rows:
            if row.get("po_date"):
                row["po_date"] = str(row["po_date"])
            if row.get("updated_date_time"):
                row["updated_date_time"] = str(row["updated_date_time"])

        return {
            "data": rows,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if limit > 0 else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Jute PO table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_jute_po_by_id/{jute_po_id}")
async def get_jute_po_by_id(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single Jute PO by ID.
    
    Path params:
    - jute_po_id: Jute PO ID
    
    Query params:
    - co_id: Company ID (required)
    """
    try:
        q_co_id = request.query_params.get("co_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        query = get_jute_po_by_id_query()
        result = db.execute(query, {"jute_po_id": jute_po_id, "co_id": co_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Jute PO not found")

        row = dict(result._mapping)

        # Format dates for JSON serialization
        if row.get("po_date"):
            row["po_date"] = str(row["po_date"])
        if row.get("updated_date_time"):
            row["updated_date_time"] = str(row["updated_date_time"])
        if row.get("mod_on"):
            row["mod_on"] = str(row["mod_on"])
        if row.get("contract_date"):
            row["contract_date"] = str(row["contract_date"])

        # Fetch line items and include in response
        line_items_query = get_jute_po_line_items_query()
        line_items_result = db.execute(line_items_query, {"jute_po_id": jute_po_id}).fetchall()
        row["line_items"] = [dict(r._mapping) for r in line_items_result]

        return row

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Jute PO by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_jute_po_line_items/{jute_po_id}")
async def get_jute_po_line_items(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get line items for a Jute PO."""
    try:
        query = get_jute_po_line_items_query()
        result = db.execute(query, {"jute_po_id": jute_po_id}).fetchall()
        rows = [dict(r._mapping) for r in result]
        return {"line_items": rows}
    except Exception as e:
        logger.exception("Error fetching Jute PO line items")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_po_create_setup")
async def jute_po_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a Jute PO.
    Returns branches, mukams, vehicle types, and jute items.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Get branches
        branches_result = db.execute(get_branches_query(), {"co_id": co_id}).fetchall()
        branches = [dict(r._mapping) for r in branches_result]

        # Get mukams
        mukams_result = db.execute(get_mukam_list_query(), {"co_id": co_id}).fetchall()
        mukams = [dict(r._mapping) for r in mukams_result]

        # Get vehicle types
        vehicle_types_result = db.execute(get_vehicle_types_query(), {"co_id": co_id}).fetchall()
        vehicle_types = [dict(r._mapping) for r in vehicle_types_result]

        # Get jute groups (subgroups with parent item_type_id = 2)
        jute_groups_result = db.execute(get_jute_items_query(), {"co_id": co_id}).fetchall()
        jute_groups = [dict(r._mapping) for r in jute_groups_result]

        # Get all jute suppliers for the company (mandatory field on PO)
        suppliers_result = db.execute(get_all_suppliers_query(), {"co_id": co_id}).fetchall()
        suppliers = [dict(r._mapping) for r in suppliers_result]

        # Static options
        channel_options = [
            {"value": "DOMESTIC", "label": "Domestic"},
            {"value": "IMPORT", "label": "Import"},
            {"value": "JCI", "label": "JCI"},
            {"value": "PTF", "label": "PTF"},
        ]

        unit_options = [
            {"value": "LOOSE", "label": "Loose"},
            {"value": "BALE", "label": "Bale"},
        ]

        # Generate crop year options (current year -1 to +2)
        current_year = now_ist().year % 100  # Get last 2 digits
        crop_year_options = []
        for i in range(-1, 3):
            start_year = current_year + i - 1
            end_year = current_year + i
            crop_year_options.append({
                "value": f"{start_year:02d}-{end_year:02d}",
                "label": f"{start_year:02d}-{end_year:02d}",
            })

        return {
            "branches": branches,
            "mukams": mukams,
            "vehicle_types": vehicle_types,
            "jute_groups": jute_groups,
            "suppliers": suppliers,
            "channel_options": channel_options,
            "unit_options": unit_options,
            "crop_year_options": crop_year_options,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Jute PO create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_suppliers_by_mukam/{mukam_id}")
async def get_suppliers_by_mukam(
    mukam_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get jute suppliers filtered by mukam."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)
        
        query = get_suppliers_by_mukam_query()
        result = db.execute(query, {"mukam_id": mukam_id, "co_id": co_id}).fetchall()
        suppliers = [dict(r._mapping) for r in result]
        
        return {"suppliers": suppliers}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching suppliers by mukam")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_parties_by_supplier/{supplier_id}")
async def get_parties_by_supplier(
    supplier_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get parties mapped to a jute supplier."""
    try:
        query = get_parties_by_supplier_query()
        result = db.execute(query, {"supplier_id": supplier_id}).fetchall()
        parties = [dict(r._mapping) for r in result]
        
        return {"parties": parties}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching parties by supplier")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_qualities_by_item/{item_grp_id}")
async def get_qualities_by_item(
    item_grp_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get items (formerly qualities) for a specific jute subgroup."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)
        
        query = get_jute_qualities_by_item_query()
        result = db.execute(query, {"item_grp_id": item_grp_id}).fetchall()
        qualities = [dict(r._mapping) for r in result]
        
        return {"qualities": qualities}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching qualities by item")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# JUTE PO CREATE / UPDATE MODELS
# =============================================================================

class JutePOLineItemCreate(BaseModel):
    """Schema for a Jute PO line item."""
    item_id: Optional[int] = None
    crop_year: Optional[str] = None
    marka: Optional[str] = None
    quantity: float
    rate: float
    allowable_moisture: Optional[float] = None
    jute_unit: str = "LOOSE"  # "LOOSE" or "BALE", per line item


class JutePOCreate(BaseModel):
    """Schema for creating a Jute PO."""
    co_id: int
    branch_id: int
    po_date: date
    mukam_id: int
    jute_unit: Optional[str] = None  # DEPRECATED: use per-line-item jute_unit
    supplier_id: int
    party_id: Optional[int] = None
    vehicle_type_id: int
    vehicle_quantity: int
    channel_code: str
    credit_term: Optional[int] = None
    delivery_timeline: Optional[int] = None
    freight_charge: Optional[float] = None
    remarks: Optional[str] = None
    line_items: List[JutePOLineItemCreate]


class JutePOUpdate(BaseModel):
    """Schema for updating a Jute PO."""
    branch_id: Optional[int] = None
    po_date: Optional[date] = None
    mukam_id: Optional[int] = None
    jute_unit: Optional[str] = None
    supplier_id: Optional[int] = None
    party_id: Optional[int] = None
    vehicle_type_id: Optional[int] = None
    vehicle_quantity: Optional[int] = None
    channel_code: Optional[str] = None
    credit_term: Optional[int] = None
    delivery_timeline: Optional[int] = None
    freight_charge: Optional[float] = None
    remarks: Optional[str] = None
    line_items: Optional[List[JutePOLineItemCreate]] = None


# =============================================================================
# JUTE PO CREATE / UPDATE ENDPOINTS
# =============================================================================

@router.post("/jute_po_create")
async def jute_po_create(
    payload: JutePOCreate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new Jute PO."""
    try:
        from src.models.jute import JutePo, JutePoLi
        
        user_id = token_data.get("user_id")
        
        # Get vehicle weight for validation
        vehicle_result = db.execute(
            text("SELECT weight FROM jute_lorry_mst WHERE jute_lorry_type_id = :vehicle_type_id"),
            {"vehicle_type_id": payload.vehicle_type_id}
        ).fetchone()
        vehicle_capacity_qtl = vehicle_result.weight if vehicle_result else 0
        
        # Calculate total weight and value from line items FIRST for validation
        total_weight_kg = 0.0
        total_value = 0.0
        line_items_data = []
        
        for li in payload.line_items:
            # Calculate weight based on line item's unit type (fixed weights)
            weight_kg = calculate_line_item_weight(li.quantity, li.jute_unit)

            # Rate is per quintal (100 kg), so convert weight to quintals
            weight_in_quintals = weight_kg / 100
            amount = weight_in_quintals * li.rate
            total_weight_kg += weight_kg
            total_value += amount

            line_items_data.append({
                "li": li,
                "weight_kg": weight_kg,
                "amount": amount,
            })

        # Validate vehicle weight tolerance (±5%)
        is_valid, error_message = validate_vehicle_weight(
            total_weight_kg, vehicle_capacity_qtl, payload.vehicle_quantity
        )
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_message)
        
        # Calculate financial year from po_date
        # Financial year: April 1 to March 31
        # Example: January 20, 2025 → FY 2024-2025, April 15, 2025 → FY 2025-2026
        if payload.po_date.month >= 4:
            fy_start_year = payload.po_date.year
            fy_end_year = payload.po_date.year + 1
        else:
            fy_start_year = payload.po_date.year - 1
            fy_end_year = payload.po_date.year
        
        # Financial year starts on April 1 and ends on March 31
        fy_start_date = date(fy_start_year, 4, 1)
        fy_end_date = date(fy_end_year, 3, 31)
        
        # Generate PO number (get max po_no for branch + financial year and increment)
        max_po_result = db.execute(
            text("""
                SELECT COALESCE(MAX(po_no), 0) + 1 AS next_po 
                FROM jute_po 
                WHERE branch_id = :branch_id 
                  AND po_date >= :fy_start 
                  AND po_date <= :fy_end
            """),
            {
                "branch_id": payload.branch_id,
                "fy_start": fy_start_date,
                "fy_end": fy_end_date
            }
        ).fetchone()
        next_po_no = max_po_result.next_po if max_po_result else 1
        
        # Create header
        jute_po = JutePo(
            branch_id=payload.branch_id,
            po_no=next_po_no,
            po_date=payload.po_date,
            jute_mukam_id=payload.mukam_id,
            jute_uom=None,  # Deprecated: unit now stored per line item
            supplier_id=payload.supplier_id,
            party_id=payload.party_id,
            vehicle_type_id=payload.vehicle_type_id,
            vehicle_quantity=payload.vehicle_quantity,
            channel_code=payload.channel_code,
            credit_term=payload.credit_term,
            delivery_days=payload.delivery_timeline,
            frieght_charge=payload.freight_charge,
            remarks=payload.remarks,
            weight=total_weight_kg,
            jute_po_value=total_value,
            status_id=21,  # Draft status
            updated_by=user_id,
        )
        
        db.add(jute_po)
        db.flush()  # Get the jute_po_id
        
        # Create line items
        for item_data in line_items_data:
            li = item_data["li"]
            line_item = JutePoLi(
                jute_po_id=jute_po.jute_po_id,
                item_id=li.item_id,
                crop_year=int(li.crop_year.split("-")[0]) if li.crop_year else None,
                marka=li.marka,
                quantity=li.quantity,
                rate=li.rate,
                allowable_moisture=li.allowable_moisture,
                jute_uom=li.jute_unit,
                value=item_data["amount"],
                status_id=21,  # Draft status (same as header)
            )
            db.add(line_item)
        
        db.commit()
        
        # Fetch company and branch prefix for formatted PO number
        prefix_result = db.execute(
            text("""
                SELECT cm.co_prefix, bm.branch_prefix
                FROM branch_mst bm
                INNER JOIN co_mst cm ON cm.co_id = bm.co_id
                WHERE bm.branch_id = :branch_id
            """),
            {"branch_id": payload.branch_id}
        ).fetchone()
        
        co_prefix = prefix_result.co_prefix if prefix_result else None
        branch_prefix = prefix_result.branch_prefix if prefix_result else None
        
        # Generate formatted po_num string for response
        po_num = format_jute_po_number(next_po_no, payload.po_date, co_prefix, branch_prefix)
        
        return {
            "success": True,
            "jute_po_id": jute_po.jute_po_id,
            "po_num": po_num,
            "message": "Jute PO created successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jute_po_update/{jute_po_id}")
async def jute_po_update(
    jute_po_id: int,
    payload: JutePOUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing Jute PO."""
    try:
        from src.models.jute import JutePo, JutePoLi
        
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)
        
        user_id = token_data.get("user_id")
        
        # Get existing PO - verify it belongs to a branch under this co_id
        # First get valid branch IDs for this company
        valid_branches_result = db.execute(
            text("SELECT branch_id FROM branch_mst WHERE co_id = :co_id"),
            {"co_id": co_id}
        ).fetchall()
        valid_branch_ids = [r.branch_id for r in valid_branches_result]
        
        if not valid_branch_ids:
            raise HTTPException(status_code=404, detail="No branches found for this company")
        
        jute_po = db.query(JutePo).filter(
            JutePo.jute_po_id == jute_po_id,
            JutePo.branch_id.in_(valid_branch_ids)
        ).first()
        
        if not jute_po:
            raise HTTPException(status_code=404, detail="Jute PO not found")
        
        # Check if PO is editable (Draft or Open status)
        if jute_po.status_id not in [21, 1]:
            raise HTTPException(status_code=400, detail="Jute PO cannot be edited in current status")
        
        # Update header fields
        if payload.branch_id is not None:
            jute_po.branch_id = payload.branch_id
        if payload.po_date is not None:
            jute_po.po_date = payload.po_date
        if payload.mukam_id is not None:
            jute_po.jute_mukam_id = payload.mukam_id
        if payload.supplier_id is not None:
            jute_po.supplier_id = payload.supplier_id
        if payload.party_id is not None:
            jute_po.party_id = payload.party_id
        if payload.vehicle_type_id is not None:
            jute_po.vehicle_type_id = payload.vehicle_type_id
        if payload.vehicle_quantity is not None:
            jute_po.vehicle_quantity = payload.vehicle_quantity
        if payload.channel_code is not None:
            jute_po.channel_code = payload.channel_code
        if payload.credit_term is not None:
            jute_po.credit_term = payload.credit_term
        if payload.delivery_timeline is not None:
            jute_po.delivery_days = payload.delivery_timeline
        if payload.freight_charge is not None:
            jute_po.frieght_charge = payload.freight_charge
        if payload.remarks is not None:
            jute_po.remarks = payload.remarks
        
        jute_po.updated_by = user_id
        jute_po.updated_date_time = now_ist()
        
        # Update line items if provided
        if payload.line_items is not None:
            # Get vehicle weight for validation
            vehicle_result = db.execute(
                text("SELECT weight FROM jute_lorry_mst WHERE jute_lorry_type_id = :vehicle_type_id"),
                {"vehicle_type_id": jute_po.vehicle_type_id}
            ).fetchone()
            vehicle_capacity_qtl = vehicle_result.weight if vehicle_result else 0
            
            # Calculate total weight and value FIRST for validation
            total_weight_kg = 0.0
            total_value = 0.0
            line_items_data = []

            for li in payload.line_items:
                # Calculate weight based on line item's unit type (fixed weights)
                weight_kg = calculate_line_item_weight(li.quantity, li.jute_unit)
                
                # Rate is per quintal (100 kg), so convert weight to quintals
                weight_in_quintals = weight_kg / 100
                amount = weight_in_quintals * li.rate
                total_weight_kg += weight_kg
                total_value += amount
                
                line_items_data.append({
                    "li": li,
                    "weight_kg": weight_kg,
                    "amount": amount,
                })
            
            # Validate vehicle weight tolerance (±5%)
            is_valid, error_message = validate_vehicle_weight(
                total_weight_kg, vehicle_capacity_qtl, jute_po.vehicle_quantity or 0
            )
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_message)
            
            # Delete existing line items (triggers will log the deletions)
            db.query(JutePoLi).filter(JutePoLi.jute_po_id == jute_po_id).delete()
            
            # Create new line items
            for item_data in line_items_data:
                li = item_data["li"]
                line_item = JutePoLi(
                    jute_po_id=jute_po_id,
                    item_id=li.item_id,
                    crop_year=int(li.crop_year.split("-")[0]) if li.crop_year else None,
                    marka=li.marka,
                    quantity=li.quantity,
                    rate=li.rate,
                    allowable_moisture=li.allowable_moisture,
                    jute_uom=li.jute_unit,
                    value=item_data["amount"],
                    status_id=jute_po.status_id,  # Same status as header
                )
                db.add(line_item)
            
            # Update totals
            jute_po.weight = total_weight_kg
            jute_po.jute_po_value = total_value
        
        db.commit()
        
        return {
            "success": True,
            "jute_po_id": jute_po_id,
            "message": "Jute PO updated successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# JUTE PO APPROVAL SCHEMAS
# =============================================================================

class ApprovePayload(BaseModel):
    menu_id: Optional[int] = None  # For multi-level approval via shared utility


class RejectPayload(BaseModel):
    reason: Optional[str] = None
    menu_id: Optional[int] = None  # For multi-level rejection via shared utility


# =============================================================================
# JUTE PO APPROVAL ENDPOINTS
# =============================================================================

@router.post("/open_jute_po/{jute_po_id}")
async def open_jute_po(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a Jute PO (change status from Draft to Open)."""
    try:
        from src.models.jute import JutePo
        from src.models.mst import BranchMst
        
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)
        
        # Join with branch_mst to verify co_id since JutePo doesn't have co_id column
        jute_po = db.query(JutePo).join(
            BranchMst, JutePo.branch_id == BranchMst.branch_id
        ).filter(
            JutePo.jute_po_id == jute_po_id,
            BranchMst.co_id == co_id
        ).first()
        
        if not jute_po:
            raise HTTPException(status_code=404, detail="Jute PO not found")
        
        if jute_po.status_id != 21:  # Must be Draft
            raise HTTPException(status_code=400, detail="Only Draft POs can be opened")
        
        jute_po.status_id = 1  # Open status
        jute_po.updated_by = token_data.get("user_id")
        jute_po.updated_date_time = now_ist()
        
        db.commit()
        
        return {"success": True, "message": "Jute PO opened successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_jute_po/{jute_po_id}")
async def approve_jute_po(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    payload: Optional[ApprovePayload] = None,
):
    """Approve a Jute PO.

    When menu_id is provided (via body or query param), uses the shared approval
    utility for multi-level approval hierarchy support. When omitted, falls back
    to direct approval (backward compatible).
    """
    try:
        from src.models.jute import JutePo
        from src.models.mst import BranchMst

        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)

        user_id = token_data.get("user_id")

        # Determine menu_id from payload body or query param
        menu_id = None
        if payload and payload.menu_id is not None:
            menu_id = payload.menu_id
        elif request.query_params.get("menu_id"):
            menu_id = int(request.query_params.get("menu_id"))

        if menu_id is not None:
            # Use shared approval utility for multi-level approval
            approval_result = process_approval(
                doc_id=jute_po_id,
                user_id=user_id,
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_jute_po_with_approval_info,
                update_status_fn=update_jute_po_status,
                id_param_name="jute_po_id",
                doc_name="Jute PO",
                document_amount=None,  # Jute never checks values
            )
            new_status = approval_result["new_status_id"]
            is_final = new_status == 3
            message = "Jute PO approved successfully" if is_final else approval_result["message"]

            return {"success": True, "message": message, "status_id": new_status}
        else:
            # Backward compatible: direct approval without hierarchy checks
            jute_po = db.query(JutePo).join(
                BranchMst, JutePo.branch_id == BranchMst.branch_id
            ).filter(
                JutePo.jute_po_id == jute_po_id,
                BranchMst.co_id == co_id,
            ).first()

            if not jute_po:
                raise HTTPException(status_code=404, detail="Jute PO not found")

            if jute_po.status_id not in [1, 20]:
                raise HTTPException(
                    status_code=400,
                    detail="Jute PO cannot be approved in current status",
                )

            jute_po.status_id = 3  # Approved status
            jute_po.updated_by = user_id
            jute_po.updated_date_time = now_ist()

            db.commit()

            return {"success": True, "message": "Jute PO approved successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error approving Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_jute_po/{jute_po_id}")
async def reject_jute_po(
    jute_po_id: int,
    payload: RejectPayload,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a Jute PO.

    When menu_id is provided, uses the shared rejection utility for
    level-based permission checks. When omitted, falls back to direct
    rejection (backward compatible).
    """
    try:
        from src.models.jute import JutePo
        from src.models.mst import BranchMst

        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)

        user_id = token_data.get("user_id")
        menu_id = payload.menu_id

        if menu_id is not None:
            # Use shared rejection utility for level-based permission checks
            process_rejection(
                doc_id=jute_po_id,
                user_id=user_id,
                menu_id=menu_id,
                db=db,
                get_doc_fn=get_jute_po_with_approval_info,
                update_status_fn=update_jute_po_status,
                id_param_name="jute_po_id",
                doc_name="Jute PO",
                reason=payload.reason,
            )
        else:
            # Backward compatible: direct rejection without hierarchy checks
            jute_po = db.query(JutePo).join(
                BranchMst, JutePo.branch_id == BranchMst.branch_id
            ).filter(
                JutePo.jute_po_id == jute_po_id,
                BranchMst.co_id == co_id,
            ).first()

            if not jute_po:
                raise HTTPException(status_code=404, detail="Jute PO not found")

            if jute_po.status_id not in [1, 20]:
                raise HTTPException(
                    status_code=400,
                    detail="Jute PO cannot be rejected in current status",
                )

            jute_po.status_id = 4  # Rejected status
            jute_po.approval_level = None
            jute_po.updated_by = user_id
            jute_po.updated_date_time = now_ist()

            db.commit()

        # Store rejection reason in internal_note (both paths)
        if payload.reason:
            note_query = text("""
                UPDATE jute_po
                SET internal_note = CONCAT(
                    COALESCE(internal_note, ''),
                    CASE WHEN internal_note IS NOT NULL AND internal_note != '' THEN ' | ' ELSE '' END,
                    'Rejected: ', :reason
                )
                WHERE jute_po_id = :jute_po_id
            """)
            db.execute(note_query, {"jute_po_id": jute_po_id, "reason": payload.reason})
            db.commit()

        return {"success": True, "message": "Jute PO rejected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error rejecting Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_jute_po/{jute_po_id}")
async def cancel_draft_jute_po(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a Draft Jute PO."""
    try:
        from src.models.jute import JutePo
        from src.models.mst import BranchMst
        
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)
        
        # Join with branch_mst to verify co_id since JutePo doesn't have co_id column
        jute_po = db.query(JutePo).join(
            BranchMst, JutePo.branch_id == BranchMst.branch_id
        ).filter(
            JutePo.jute_po_id == jute_po_id,
            BranchMst.co_id == co_id
        ).first()
        
        if not jute_po:
            raise HTTPException(status_code=404, detail="Jute PO not found")
        
        if jute_po.status_id != 21:  # Must be Draft
            raise HTTPException(status_code=400, detail="Only Draft POs can be cancelled")
        
        jute_po.status_id = 6  # Cancelled status
        jute_po.updated_by = token_data.get("user_id")
        jute_po.updated_date_time = now_ist()
        
        db.commit()
        
        return {"success": True, "message": "Jute PO cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error cancelling Jute PO")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_jute_po/{jute_po_id}")
async def reopen_jute_po(
    jute_po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a rejected or cancelled Jute PO."""
    try:
        from src.models.jute import JutePo
        from src.models.mst import BranchMst
        
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        co_id = int(q_co_id)
        
        # Join with branch_mst to verify co_id since JutePo doesn't have co_id column
        jute_po = db.query(JutePo).join(
            BranchMst, JutePo.branch_id == BranchMst.branch_id
        ).filter(
            JutePo.jute_po_id == jute_po_id,
            BranchMst.co_id == co_id
        ).first()
        
        if not jute_po:
            raise HTTPException(status_code=404, detail="Jute PO not found")
        
        if jute_po.status_id not in [4, 6]:  # Must be Rejected or Cancelled
            raise HTTPException(status_code=400, detail="Only Rejected or Cancelled POs can be reopened")
        
        jute_po.status_id = 21  # Back to Draft
        jute_po.updated_by = token_data.get("user_id")
        jute_po.updated_date_time = now_ist()
        
        db.commit()
        
        return {"success": True, "message": "Jute PO reopened successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error reopening Jute PO")
        raise HTTPException(status_code=500, detail=str(e))
