from fastapi import Depends, Request, HTTPException, APIRouter, Response, Cookie
import os
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import  get_current_user_with_refresh
# from src.masters.schemas import MenuResponse
from src.masters.models import ItemGrpMst, ItemTypeMaster, ItemMst, ItemMake
from src.masters.query import get_item_group, get_item_group_drodown, india_gst_applicable, get_item_table, check_item_group_code_and_name
from src.masters.query import get_item_group_details_by_id, get_item_minmax_mapping, get_item, get_item_uom_mapping, get_uom_list, get_item_by_id
from src.masters.query import get_item_group_path, get_item_make
from datetime import datetime
from src.common.utils import now_ist

router = APIRouter()


def optional_auth(request: Request, response: Response, access_token: str = Cookie(None, alias="access_token")) -> dict:
    """Dev-toggle auth dependency.
    If BYPASS_AUTH=1 or ENV=development, return a dummy user dict. Otherwise delegate to the real auth helper.
    """
    BYPASS = os.getenv("BYPASS_AUTH", "0")
    ENV = os.getenv("ENV", "development")
    if BYPASS == "1" or ENV == "development":
        return {"user_id": None}
    # Delegate to the real auth function which will raise HTTPException if token invalid
    return get_current_user_with_refresh(request, response, access_token)


@router.get("/get_all_item_groups")
async def get_item_groups(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_item_group(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    


@router.get("/createItemGroupSetup")
async def create_item_group_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    is_india_gst_applicable = False  # Ensure variable is always defined
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # No search param for setup, just get all item groups for dropdown
        query = get_item_group_drodown(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": None}).fetchall()
        item_groups = [dict(row._mapping) for row in result]
        # Get all item types for dropdown
        item_types = db.query(ItemTypeMaster).all()
        item_type_list = [
            {"item_type_id": t.item_type_id, "item_type_name": t.item_type_name}
            for t in item_types
        ]
        # Check if India GST is applicable for the company
        india_gst_query = india_gst_applicable()
        result = db.execute(india_gst_query, {"co_id": int(co_id)}).fetchone()
        if result and result[0] is not None:
            is_india_gst_applicable = result[0]
        return {"item_groups": item_groups, "item_types": item_type_list, "india_gst_applicable": is_india_gst_applicable}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/createItemGroup")
async def create_item_group(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        def sanitize_int(value):
            return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None

        parent_grp_id = sanitize_int(payload.get("parent_grp_id"))
        item_type_id = sanitize_int(payload.get("item_type_id"))
        co_id = payload.get("co_id")
        item_grp_code = payload.get("item_grp_code")
        item_grp_name = payload.get("item_grp_name")
        updated_by = payload.get("updated_by") or str(token_data.get("user_id"))

        
        new_group = ItemGrpMst(
            co_id=co_id,
            active=1,
            updated_by=updated_by,
            updated_date_time=payload.get("updated_date_time", now_ist()),
            item_grp_name=item_grp_name,
            item_grp_code=item_grp_code,
            item_type_id=item_type_id,
            parent_grp_id=parent_grp_id
        )
        db.add(new_group)
        db.commit()
        db.refresh(new_group)
        return {"message": "Item group created successfully", "item_grp_id": new_group.item_grp_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    


@router.post("/updateItemGroupActive")
async def update_item_group_active_status(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        item_grp_id = payload.get("item_grp_id")
        active_status = payload.get("active")
        co_id = payload.get("co_id")

        if item_grp_id is None or active_status is None or co_id is None:
            raise HTTPException(status_code=400, detail="Item group ID, active status, and company ID are required")

        # Fetch the item group by id and company
        item_group = db.query(ItemGrpMst).filter_by(item_grp_id=item_grp_id, co_id=co_id).first()
        if not item_group:
            raise HTTPException(status_code=404, detail="Item group not found")

        item_group.active = active_status
        db.commit()
        return {"message": "Item group active status updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/itemGroupDetails")
async def get_item_group_details(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        item_grp_id = payload.get("itemgroupid")
        if not item_grp_id:
            raise HTTPException(status_code=400, detail="Item group ID (itemgroupid) is required")
        from src.masters.query import get_item_group_details_by_id
        query = get_item_group_details_by_id()
        result = db.execute(query, {"item_grp_id": int(item_grp_id)}).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Item group not found")
        return dict(result._mapping)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/get_item_table")
async def get_item(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_item_table(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/item_create_setup")
async def get_item_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    item_id: int = None
):
    try:
        co_id = request.query_params.get("co_id")

        itemgroup_query = get_item_group_drodown(int(co_id))
        itemgroups = db.execute(itemgroup_query, {"co_id": int(co_id)}).fetchall()
        uomgroup_query = get_uom_list()
        uomgroups = db.execute(uomgroup_query, {"co_id": int(co_id)}).fetchall()
        minmax_query = get_item_minmax_mapping(None, int(co_id))
        minmax_mapping = db.execute(minmax_query, {"item_id": None, "co_id": int(co_id)}).fetchall()
        if not itemgroups:
            raise HTTPException(status_code=404, detail="Item groups not found")
        return {
            "itemgroups": [dict(row._mapping) for row in itemgroups], 
            "uomgroups": [dict(row._mapping) for row in uomgroups],
            "minmax_mapping": [dict(row._mapping) for row in minmax_mapping]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/item_edit_setup")
async def get_item_edit_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # read required query params
        co_id = request.query_params.get("co_id")
        item_id = request.query_params.get("item_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not item_id:
            raise HTTPException(status_code=400, detail="Item ID (item_id) is required")

        co_id = int(co_id)
        item_id = int(item_id)


        # uom list
        uomgroup_query = get_uom_list()
        uomgroups = db.execute(uomgroup_query).fetchall()

        # item details
        item_query = get_item_by_id(item_id)
        item_row = db.execute(item_query, {"item_id": item_id}).fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail="Item not found")
        item_details = dict(item_row._mapping)

        # uom mappings for the item
        uom_map_query = get_item_uom_mapping(item_id)
        uom_mappings = db.execute(uom_map_query, {"item_id": item_id}).fetchall()

        # minmax mapping for the item and company
        minmax_query = get_item_minmax_mapping(item_id, co_id)
        minmax_mapping = db.execute(minmax_query, {"item_id": item_id, "co_id": co_id}).fetchall()

        # item group path for the item's group
        item_grp_id = item_details.get("item_grp_id")
        group_path = None
        if item_grp_id:
            group_path_query = get_item_group_path(item_grp_id)
            group_path_row = db.execute(group_path_query).fetchone()
            group_path = dict(group_path_row._mapping) if group_path_row else None

        return {
            "uomgroups": [dict(row._mapping) for row in uomgroups],
            "item_details": item_details,
            "uom_mappings": [dict(row._mapping) for row in uom_mappings],
            "minmax_mapping": [dict(row._mapping) for row in minmax_mapping],
            "item_group_path": group_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


    
@router.post("/item_create")
async def create_item(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        def sanitize_int(value):
            return int(value) if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else None

        # Map incoming camelCase payload to local variables
        co_id = sanitize_int(payload.get("co_id"))
        item_grp_id = sanitize_int(payload.get("itemGroupId") or payload.get("item_grp_id"))
        item_code = payload.get("itemCode") or payload.get("item_code")
        item_name = payload.get("itemName") or payload.get("item_name")
        uom_id = sanitize_int(payload.get("uomId") or payload.get("uom_id"))
        hsn_code = payload.get("hsnCode") or payload.get("hsn_code")
        tax_percentage = float(payload.get("taxPercent") or payload.get("tax_percentage") or 0.0)
        uom_rounding = sanitize_int(payload.get("uomRounding") or payload.get("uom_rounding"))
        rate_rounding = sanitize_int(payload.get("rateRounding") or payload.get("rate_rounding"))
        good_or_service = payload.get("goodOrService")
        saleable = payload.get("saleable")
        consumable = payload.get("consumable")
        purchaseable = payload.get("purchaseable")
        manufacturable = payload.get("manufacturable")
        assembly = payload.get("assembly")
        updated_by = payload.get("updated_by") or str(token_data.get("user_id"))

        # Basic validation
        if co_id is None:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        if not item_code or not item_name:
            raise HTTPException(status_code=400, detail="itemCode and itemName are required")

        # Company maps items via item groups; fetch group's ids for this company
        groups = db.query(ItemGrpMst).filter(ItemGrpMst.co_id == co_id).all()
        group_ids = [g.item_grp_id for g in groups]

        # Enforce code uniqueness within the same item group only (allow same code in different groups)
        if item_grp_id:
            existing_code = db.query(ItemMst).filter(ItemMst.item_grp_id == item_grp_id, ItemMst.item_code == item_code).first()
        else:
            # If no group provided, conservatively check across company groups
            existing_code = db.query(ItemMst).filter(ItemMst.item_grp_id.in_(group_ids), ItemMst.item_code == item_code).first() if group_ids else None

        # Item name uniqueness remains company-scoped (across all groups)
        existing_name = db.query(ItemMst).filter(ItemMst.item_grp_id.in_(group_ids), ItemMst.item_name == item_name).first() if group_ids else None

        if existing_code:
            raise HTTPException(status_code=409, detail="Item code already exists in the specified item group")
        if existing_name:
            raise HTTPException(status_code=409, detail="Item name already exists")

        # Build ItemMst instance — ignore uom_mappings and minmax_mappings per request
        tangible = True if (isinstance(good_or_service, str) and good_or_service.lower().startswith('g')) or good_or_service == 'Good' else False

        new_item = ItemMst(
            # co_id may or may not exist on the model; set if attribute is present
            **({"co_id": co_id} if hasattr(ItemMst, 'co_id') else {}),
            active=1,
            updated_by=int(updated_by) if str(updated_by).isdigit() else None,
            item_grp_id=item_grp_id,
            item_code=item_code,
            tangible=tangible,
            item_name=item_name,
            hsn_code=hsn_code,
            uom_id=uom_id,
            tax_percentage=tax_percentage,
            saleable=bool(saleable),
            consumable=bool(consumable),
            purchaseable=bool(purchaseable),
            manufacturable=bool(manufacturable),
            assembly=bool(assembly),
            uom_rounding=uom_rounding,
            rate_rounding=rate_rounding
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        response.status_code = 201
        return {"message": "Item created successfully", "item_id": getattr(new_item, 'item_id', None)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    


@router.api_route("/item_edit", methods=["POST", "PUT"])
async def item_update_full(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Update ItemMst, ItemMinmaxMst and UomItemMapMst from the provided payload.

    Expected payload keys: item_id, itemGroupId, itemCode, itemName, taxPercent, uomId,
    uomRounding, rateRounding, goodOrService, saleable, consumable, purchaseable,
    manufacturable, assembly, uom_mappings (list), minmax_mappings (list)
    """
    def sanitize_int(value):
        return int(value) if isinstance(value, int) or (isinstance(value, str) and str(value).isdigit()) else None

    def sanitize_float(value):
        try:
            return float(value)
        except Exception:
            return None

    item_id = sanitize_int(payload.get("item_id"))
    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    # load existing item
    existing = db.query(ItemMst).filter(ItemMst.item_id == item_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Item not found")

    # map fields
    item_grp_id = sanitize_int(payload.get("itemGroupId") or payload.get("item_grp_id") )
    item_code = payload.get("itemCode") or payload.get("item_code")
    item_name = payload.get("itemName") or payload.get("item_name")
    uom_id = sanitize_int(payload.get("uomId") or payload.get("uom_id"))
    tax_percentage = sanitize_float(payload.get("taxPercent") or payload.get("tax_percentage")) or (existing.tax_percentage or 0.0)
    uom_rounding = sanitize_int(payload.get("uomRounding") or payload.get("uom_rounding"))
    rate_rounding = sanitize_int(payload.get("rateRounding") or payload.get("rate_rounding"))
    good_or_service = payload.get("goodOrService")
    saleable = payload.get("saleable") if "saleable" in payload else existing.saleable
    consumable = payload.get("consumable") if "consumable" in payload else existing.consumable
    purchaseable = payload.get("purchaseable") if "purchaseable" in payload else existing.purchaseable
    manufacturable = payload.get("manufacturable") if "manufacturable" in payload else existing.manufacturable
    assembly = payload.get("assembly") if "assembly" in payload else existing.assembly

    # Prefer user id from token for updated_by; fall back to payload.updated_by if token missing
    user_id = None
    if token_data and token_data.get("user_id"):
        user_id = token_data.get("user_id")
    else:
        user_id = payload.get("updated_by")

    # perform update inside transaction
    try:
        # update item_mst
        if item_grp_id is not None:
            existing.item_grp_id = item_grp_id
        if item_code is not None:
            existing.item_code = item_code
        if item_name is not None:
            existing.item_name = item_name
        if uom_id is not None:
            existing.uom_id = uom_id
        existing.hsn_code = payload.get("hsnCode") or existing.hsn_code
        existing.tax_percentage = float(tax_percentage)
        if uom_rounding is not None:
            existing.uom_rounding = uom_rounding
        if rate_rounding is not None:
            existing.rate_rounding = rate_rounding
        existing.tangible = True if (isinstance(good_or_service, str) and good_or_service.lower().startswith('g')) or good_or_service == 'Good' else existing.tangible
        existing.saleable = bool(saleable)
        existing.consumable = bool(consumable)
        existing.purchaseable = bool(purchaseable)
        existing.manufacturable = bool(manufacturable)
        existing.assembly = bool(assembly)
        existing.updated_by = int(user_id) if user_id and str(user_id).isdigit() else existing.updated_by
        existing.updated_date_time = now_ist()

        # UOM mappings: replace existing
        uom_mappings = payload.get("uom_mappings") or []
        delete_uom_sql = text("DELETE FROM uom_item_map_mst WHERE item_id = :item_id")
        db.execute(delete_uom_sql, {"item_id": item_id})
        for m in uom_mappings:
            map_from = sanitize_int(m.get("map_from_id") or m.get("mapFromUom") or m.get("map_from_uom")) or existing.uom_id
            map_to = sanitize_int(m.get("map_to_id") or m.get("mapToUom") or m.get("map_to_uom"))
            is_fixed = 1 if m.get("isFixed") or m.get("is_fixed") else 0
            relation_value = sanitize_float(m.get("relationValue") or m.get("relation_value"))
            rounding = sanitize_int(m.get("rounding"))
            insert_uom_sql = text(
                "INSERT INTO uom_item_map_mst (item_id, map_from_id, map_to_id, is_fixed, relation_value, rounding, updated_by, updated_date_time) VALUES (:item_id, :map_from, :map_to, :is_fixed, :relation_value, :rounding, :updated_by, :updated_date_time)"
            )
            db.execute(insert_uom_sql, {
                "item_id": item_id,
                "map_from": map_from,
                "map_to": map_to,
                "is_fixed": is_fixed,
                "relation_value": relation_value,
                "rounding": rounding,
                "updated_by": int(user_id) if user_id and str(user_id).isdigit() else None,
                "updated_date_time": now_ist()
            })

        # Minmax mappings: replace existing
        minmax_mappings = payload.get("minmax_mappings") or []
        delete_minmax_sql = text("DELETE FROM item_minmax_mst WHERE item_id = :item_id")
        db.execute(delete_minmax_sql, {"item_id": item_id})
        for mm in minmax_mappings:
            branch_id = sanitize_int(mm.get("branch_id"))
            minqty = sanitize_float(mm.get("minqty"))
            maxqty = sanitize_float(mm.get("maxqty"))
            min_order_qty = sanitize_float(mm.get("min_order_qty") or mm.get("min_order_qty"))
            lead_time = sanitize_int(mm.get("lead_time"))
            insert_minmax_sql = text(
                "INSERT INTO item_minmax_mst (branch_id, item_id, minqty, maxqty, min_order_qty, lead_time, updated_by, updated_date_time, active) VALUES (:branch_id, :item_id, :minqty, :maxqty, :min_order_qty, :lead_time, :updated_by, :updated_date_time, :active)"
            )
            db.execute(insert_minmax_sql, {
                "branch_id": branch_id,
                "item_id": item_id,
                "minqty": minqty,
                "maxqty": maxqty,
                "min_order_qty": min_order_qty,
                "lead_time": lead_time,
                "updated_by": int(user_id) if user_id and str(user_id).isdigit() else None,
                "updated_date_time": now_ist(),
                "active": 1
            })

        db.commit()
        db.refresh(existing)
        return {"message": "Item updated successfully", "item_id": item_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/item_make_table")
async def item_make_table(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    search: str = None
):
    try:
        # Get the item groups for the company specified in the request received
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        # Prepare search parameter for LIKE if provided
        search_param = f"%{search}%" if search else None
        query = get_item_make(int(co_id))
        result = db.execute(query, {"co_id": int(co_id), "search": search_param}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/item_make_create_setup")
async def item_make_create_setup(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="Company ID (co_id) is required")
        query = get_item_group_drodown(int(co_id))
        result = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(row._mapping) for row in result]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/item_make_create")
async def item_make_create(
    payload: dict,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(optional_auth)
):
    """Create an ItemMake. Derive updated_by from token when available.

    Accepts payload keys: item_grp_id, item_make or item_make_name, (optional) co_id.
    """
    try:
        item_grp_id = payload.get("item_grp_id")
        # accept either `item_make` or `item_make_name` from clients
        item_make_name = payload.get("item_make") or payload.get("item_make_name")

        # Prefer user id from token_data; fall back to payload.updated_by if token missing
        user_id = None
        if token_data and token_data.get("user_id"):
            user_id = token_data.get("user_id")
        else:
            user_id = payload.get("updated_by")

        if not item_grp_id or not item_make_name:
            raise HTTPException(status_code=400, detail="Item group ID and item make name are required")

        new_item_make = ItemMake(
            item_grp_id=item_grp_id,
            item_make_name=item_make_name,
            updated_by=int(user_id) if user_id and str(user_id).isdigit() else None,
            updated_date_time=now_ist()
        )
        db.add(new_item_make)
        db.commit()
        db.refresh(new_item_make)
        response.status_code = 201
        return {"message": "Item make created successfully", "item_make_id": new_item_make.item_make_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

