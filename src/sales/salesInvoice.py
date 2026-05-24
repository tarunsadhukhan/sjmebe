from fastapi import Depends, Request, HTTPException, APIRouter
import logging
from sqlalchemy.orm import Session
from sqlalchemy.sql import text
from datetime import datetime
from src.common.utils import now_ist
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.query import get_branch_list, get_item_group_drodown
from src.procurement.indent import (
    calculate_financial_year,
    format_indent_no,
)
from src.procurement.query import (
    get_item_by_group_id_purchaseable,
    get_item_make_by_group_id,
    get_item_uom_by_group_id,
)
from src.sales.quotation import (
    to_int,
    to_float,
    to_positive_float,
    format_date,
    get_fy_boundaries,
)
from src.common.approval_utils import (
    process_approval,
    process_rejection,
    calculate_approval_permissions,
)
from src.sales.query import (
    get_customers_for_sales,
    get_customer_branches_bulk,
    get_brokers_for_sales,
    get_transporters_for_sales,
    get_approved_delivery_orders_query,
    get_delivery_order_lines_for_invoice,
    get_invoice_table_query,
    get_invoice_table_count_query,
    get_invoice_by_id_query,
    get_invoice_dtl_by_id_query,
    insert_sales_invoice,
    insert_invoice_line_item,
    update_sales_invoice,
    delete_invoice_line_items,
    insert_invoice_dtl_gst,
    delete_invoice_dtl_gst,
    get_invoice_dtl_gst_by_id_query,
    update_invoice_status,
    get_invoice_with_approval_info,
    get_max_invoice_no_for_branch_fy,
    get_mukam_list,
    get_sale_invoice_jute_by_id,
)
from src.sales.constants import SALES_DOC_TYPES

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# SETUP ENDPOINTS
# =============================================================================


@router.get("/get_sales_invoice_setup_1")
async def get_sales_invoice_setup_1(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return branches, customers, transporters, approved DOs, and item groups for invoice creation."""
    try:
        q_branch_id = request.query_params.get("branch_id")
        q_co_id = request.query_params.get("co_id")
        branch_id = None
        co_id = None

        if q_branch_id is not None:
            try:
                branch_id = int(q_branch_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid branch_id")
        if q_co_id is not None:
            try:
                co_id = int(q_co_id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid co_id")

        if co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        # Branches
        branch_ids_list = [branch_id] if branch_id is not None else None
        branchquery = get_branch_list(branch_ids=branch_ids_list) if branch_ids_list else get_branch_list()
        branch_result = db.execute(branchquery, {"branch_ids": branch_ids_list} if branch_ids_list else {}).fetchall()
        branches = [dict(r._mapping) for r in branch_result]

        # Customers
        customer_query = get_customers_for_sales(co_id=co_id)
        customer_result = db.execute(customer_query, {"co_id": co_id}).fetchall()
        customers = [dict(r._mapping) for r in customer_result]

        # Customer branches in bulk
        cust_branches_query = get_customer_branches_bulk(co_id=co_id)
        cust_branches_result = db.execute(cust_branches_query, {"co_id": co_id}).fetchall()
        branches_by_party: dict[int, list[dict]] = {}
        for row in cust_branches_result:
            bd = dict(row._mapping)
            pid = bd.get("party_id")
            if pid is not None:
                if pid not in branches_by_party:
                    branches_by_party[pid] = []
                branches_by_party[pid].append(bd)
        for cust in customers:
            cust["branches"] = branches_by_party.get(cust.get("party_id"), [])

        # Brokers
        broker_query = get_brokers_for_sales(co_id=co_id)
        broker_result = db.execute(broker_query, {"co_id": co_id}).fetchall()
        brokers = [dict(r._mapping) for r in broker_result]

        # Transporters
        transporter_query = get_transporters_for_sales(co_id=co_id)
        transporter_result = db.execute(transporter_query, {"co_id": co_id}).fetchall()
        transporters = [dict(r._mapping) for r in transporter_result]

        # Approved delivery orders for dropdown (optional reference)
        ado_query = get_approved_delivery_orders_query()
        ado_result = db.execute(ado_query, {"branch_id": branch_id, "co_id": co_id}).fetchall()
        approved_delivery_orders = []
        for row in ado_result:
            mapped = dict(row._mapping)
            raw_no = mapped.get("delivery_order_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("delivery_order_date"),
                        document_type=SALES_DOC_TYPES.get("DELIVERY_ORDER", "DO"),
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""
            approved_delivery_orders.append({
                "sales_delivery_order_id": mapped.get("sales_delivery_order_id"),
                "delivery_order_no": formatted_no,
                "delivery_order_date": format_date(mapped.get("delivery_order_date")),
                "party_name": mapped.get("party_name"),
                "net_amount": mapped.get("net_amount"),
            })

        # Item groups (for manual entry without delivery order)
        itemgrp_query = get_item_group_drodown(co_id=co_id)
        itemgrp_result = db.execute(itemgrp_query, {"co_id": co_id}).fetchall()
        item_groups = [dict(r._mapping) for r in itemgrp_result]

        # Invoice types mapped to company
        invoice_types_result = db.execute(
            text("""
                SELECT itm.invoice_type_id, itm.invoice_type_name
                FROM invoice_type_co_map itcm
                JOIN invoice_type_mst itm ON itm.invoice_type_id = itcm.invoice_type_id
                WHERE itcm.co_id = :co_id AND itcm.active = 1
                ORDER BY itm.invoice_type_name
            """),
            {"co_id": co_id},
        ).fetchall()
        invoice_types = [dict(r._mapping) for r in invoice_types_result]

        # Mukam list (for jute invoices)
        mukam_query = get_mukam_list()
        mukam_result = db.execute(mukam_query).fetchall()
        mukam_list = [dict(r._mapping) for r in mukam_result]

        return {
            "branches": branches,
            "customers": customers,
            "brokers": brokers,
            "transporters": transporters,
            "approved_delivery_orders": approved_delivery_orders,
            "item_groups": item_groups,
            "invoice_types": invoice_types,
            "mukam_list": mukam_list,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice setup 1")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_invoice_setup_2")
async def get_sales_invoice_setup_2(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return items, makes, and UOMs by item_group_id."""
    try:
        q_item_group = request.query_params.get("item_group")
        if q_item_group is None:
            raise HTTPException(status_code=400, detail="item_group is required")

        try:
            item_group_id = int(q_item_group)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid item_group")

        items_query = get_item_by_group_id_purchaseable(item_group_id=item_group_id)
        items_result = db.execute(items_query, {"item_group_id": item_group_id}).fetchall()
        items = [dict(r._mapping) for r in items_result]

        makes_query = get_item_make_by_group_id(item_group_id=item_group_id)
        makes_result = db.execute(makes_query, {"item_group_id": item_group_id}).fetchall()
        makes = [dict(r._mapping) for r in makes_result]

        uoms_query = get_item_uom_by_group_id(item_group_id=item_group_id)
        uoms_result = db.execute(uoms_query, {"item_group_id": item_group_id}).fetchall()
        uoms = [dict(r._mapping) for r in uoms_result]

        return {"items": items, "makes": makes, "uoms": uoms}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_delivery_order_lines")
async def get_delivery_order_lines(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get delivery order line items to pre-fill a new invoice."""
    try:
        q_id = request.query_params.get("sales_delivery_order_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="sales_delivery_order_id is required")

        sales_delivery_order_id = int(q_id)
        query = get_delivery_order_lines_for_invoice()
        result = db.execute(query, {"sales_delivery_order_id": sales_delivery_order_id}).fetchall()
        data = [dict(r._mapping) for r in result]
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================


@router.get("/get_sales_invoice_table")
async def get_sales_invoice_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    page: int = 1,
    limit: int = 10,
    search: str | None = None,
    co_id: int | None = None,
):
    """Return paginated sales invoice list."""
    try:
        page = max(page, 1)
        limit = max(min(limit, 100), 1)
        offset = (page - 1) * limit
        search_like = f"%{search.strip()}%" if search else None

        params = {"co_id": co_id, "search_like": search_like, "limit": limit, "offset": offset}

        list_query = get_invoice_table_query()
        rows = db.execute(list_query, params).fetchall()
        data = []
        for row in rows:
            mapped = dict(row._mapping)
            raw_no = mapped.get("invoice_no")
            formatted_no = ""
            if raw_no is not None:
                try:
                    formatted_no = format_indent_no(
                        indent_no=int(raw_no) if raw_no else None,
                        co_prefix=mapped.get("co_prefix"),
                        branch_prefix=mapped.get("branch_prefix"),
                        indent_date=mapped.get("invoice_date"),
                        document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                    )
                except Exception:
                    formatted_no = str(raw_no) if raw_no else ""

            data.append({
                "invoice_id": mapped.get("invoice_id"),
                "invoice_no": formatted_no,
                "invoice_date": format_date(mapped.get("invoice_date")),
                "branch_id": mapped.get("branch_id"),
                "branch_name": mapped.get("branch_name"),
                "party_name": mapped.get("party_name"),
                "sales_delivery_order_id": mapped.get("sales_delivery_order_id"),
                "invoice_amount": mapped.get("invoice_amount"),
                "status": mapped.get("status_name"),
                "status_id": mapped.get("status_id"),
            })

        count_query = get_invoice_table_count_query()
        count_result = db.execute(count_query, {"co_id": co_id, "search_like": search_like}).scalar()
        total = int(count_result) if count_result is not None else 0

        return {"data": data, "total": total}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_sales_invoice_by_id")
async def get_sales_invoice_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return invoice details by ID with line items."""
    try:
        q_id = request.query_params.get("invoice_id")
        q_co_id = request.query_params.get("co_id")
        if q_id is None:
            raise HTTPException(status_code=400, detail="invoice_id is required")
        if q_co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            invoice_id = int(q_id)
            co_id = int(q_co_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid invoice_id or co_id")

        # Header
        header_query = get_invoice_by_id_query()
        header_result = db.execute(header_query, {"invoice_id": invoice_id, "co_id": co_id}).fetchone()
        if not header_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found or access denied")
        header = dict(header_result._mapping)

        # Details
        detail_query = get_invoice_dtl_by_id_query()
        detail_results = db.execute(detail_query, {"invoice_id": invoice_id}).fetchall()
        details = [dict(r._mapping) for r in detail_results]

        # Format invoice number
        raw_no = header.get("invoice_no")
        formatted_no = ""
        if raw_no is not None:
            try:
                formatted_no = format_indent_no(
                    indent_no=int(raw_no) if raw_no else None,
                    co_prefix=header.get("co_prefix"),
                    branch_prefix=header.get("branch_prefix"),
                    indent_date=header.get("invoice_date"),
                    document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                )
            except Exception:
                formatted_no = str(raw_no) if raw_no else ""

        status_id = header.get("status_id")
        branch_id = header.get("branch_id")

        # Permissions
        q_menu_id = request.query_params.get("menu_id")
        permissions = None
        if q_menu_id is not None and branch_id is not None and status_id is not None:
            try:
                permissions = calculate_approval_permissions(
                    user_id=int(token_data.get("user_id")),
                    menu_id=int(q_menu_id),
                    branch_id=branch_id,
                    status_id=status_id,
                    current_approval_level=None,
                    db=db,
                )
            except Exception:
                logger.exception("Error calculating permissions")

        response = {
            "id": str(header.get("invoice_id", "")),
            "invoiceNo": formatted_no,
            "invoiceDate": format_date(header.get("invoice_date")),
            "challanNo": header.get("challan_no"),
            "challanDate": format_date(header.get("challan_date")),
            "branch": str(header.get("branch_id", "")) if header.get("branch_id") else "",
            "salesDeliveryOrderId": header.get("sales_delivery_order_id"),
            "brokerId": header.get("broker_id"),
            "billingToId": header.get("billing_to_id"),
            "shippingToId": header.get("shipping_to_id"),
            "party": str(header.get("party_id", "")) if header.get("party_id") else "",
            "partyName": header.get("party_name"),
            "shippingStateCode": header.get("shipping_state_code"),
            "transporter": str(header.get("transporter_id", "")) if header.get("transporter_id") else None,
            "transporterName": header.get("transporter_name"),
            "transporterNameStored": header.get("transporter_name_stored"),
            "transporterAddress": header.get("transporter_address"),
            "transporterStateCode": header.get("transporter_state_code"),
            "transporterStateName": header.get("transporter_state_name"),
            "vehicleNo": header.get("vehicle_no"),
            "ewayBillNo": header.get("eway_bill_no"),
            "ewayBillDate": format_date(header.get("eway_bill_date")),
            "invoiceType": header.get("invoice_type"),
            "footerNote": header.get("footer_notes"),
            "internalNote": header.get("internal_note"),
            "termsConditions": header.get("terms_conditions"),
            "grossAmount": header.get("invoice_amount"),
            "taxAmount": header.get("tax_amount"),
            "taxPayable": header.get("tax_payable"),
            "freightCharges": header.get("freight_charges"),
            "roundOff": header.get("round_off"),
            "intraInterState": header.get("intra_inter_state"),
            "dueDate": format_date(header.get("due_date")),
            "typeOfSale": header.get("type_of_sale"),
            "taxId": header.get("tax_id"),
            "containerNo": header.get("container_no"),
            "contractNo": header.get("contract_no"),
            "contractDate": format_date(header.get("contract_date")),
            "consignmentNo": header.get("consignment_no"),
            "consignmentDate": format_date(header.get("consignment_date")),
            "status": header.get("status_name"),
            "statusId": status_id,
            "updatedBy": str(header.get("updated_by", "")) if header.get("updated_by") else None,
            "updatedAt": str(header.get("updated_date_time")) if header.get("updated_date_time") else None,
            "lines": [],
        }

        if permissions is not None:
            response["permissions"] = permissions

        # Fetch jute-specific data if present (table may not exist in all tenants)
        try:
            jute_query = get_sale_invoice_jute_by_id()
            jute_result = db.execute(jute_query, {"invoice_id": invoice_id}).fetchone()
            if jute_result:
                jute = dict(jute_result._mapping)
                response["jute"] = {
                    "mrNo": jute.get("mr_no"),
                    "mrId": jute.get("mr_id"),
                    "claimAmount": float(jute["claim_amount"]) if jute.get("claim_amount") is not None else None,
                    "otherReference": jute.get("other_reference"),
                    "unitConversion": jute.get("unit_conversion"),
                    "despatchDocNo": jute.get("despatch_doc_no"),
                    "despatchedThrough": jute.get("despatched_through"),
                    "mukamId": jute.get("mukam_id"),
                    "mukamName": jute.get("mukam_name"),
                    "claimNote": jute.get("claim_note"),
                }
        except Exception:
            pass

        # Fetch GST data for all line items
        gst_query = get_invoice_dtl_gst_by_id_query()
        gst_results = db.execute(gst_query, {"invoice_id": invoice_id}).fetchall()
        gst_by_line = {}
        for g in gst_results:
            gm = dict(g._mapping)
            gst_by_line[gm["invoice_line_item_id"]] = {
                "igstAmount": gm.get("igst_amount"),
                "igstPercent": gm.get("igst_percent"),
                "cgstAmount": gm.get("cgst_amount"),
                "cgstPercent": gm.get("cgst_percent"),
                "sgstAmount": gm.get("sgst_amount"),
                "sgstPercent": gm.get("sgst_percent"),
                "gstTotal": gm.get("gst_total"),
            }

        for detail in details:
            line_id = detail.get("invoice_line_item_id")
            line = {
                "id": str(line_id) if line_id else "",
                "hsnCode": detail.get("hsn_code"),
                "itemGroup": str(detail.get("item_grp_id", "")) if detail.get("item_grp_id") else "",
                "item": str(detail.get("item_id", "")) if detail.get("item_id") else "",
                "itemName": detail.get("item_name"),
                "itemMake": str(detail.get("item_make_id", "")) if detail.get("item_make_id") else None,
                "quantity": float(detail.get("quantity", 0)) if detail.get("quantity") is not None else 0,
                "uom": str(detail.get("uom_id", "")) if detail.get("uom_id") else "",
                "uomName": detail.get("uom_name"),
                "rate": detail.get("rate"),
                "discountType": detail.get("discount_type"),
                "discountedRate": detail.get("discounted_rate"),
                "discountAmount": detail.get("discount_amount"),
                "netAmount": detail.get("amount_without_tax"),
                "totalAmount": detail.get("total_amount"),
                "salesWeight": detail.get("sales_weight"),
                "remarks": detail.get("remarks"),
                "deliveryOrderDtlId": detail.get("delivery_order_dtl_id"),
            }
            gst_info = gst_by_line.get(line_id)
            if gst_info:
                line["gst"] = gst_info
            response["lines"].append(line)

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching sales invoice by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_sales_invoice")
async def create_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a sales invoice with line items. Delivery order reference is optional."""
    try:
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            invoice_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        user_id = to_int(token_data.get("user_id"), "user_id")

        # Optional fields
        transporter_id = to_int(payload.get("transporter"), "transporter")
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id")
        broker_id = to_int(payload.get("broker_id") or payload.get("broker"), "broker_id")
        billing_to_id = to_int(payload.get("billing_to"), "billing_to")
        shipping_to_id = to_int(payload.get("shipping_to"), "shipping_to")

        gross_amount = to_float(payload.get("gross_amount"), "gross_amount")
        freight_charges = to_float(payload.get("freight_charges"), "freight_charges")
        round_off = to_float(payload.get("round_off"), "round_off")
        tax_amount = to_float(payload.get("tax_amount"), "tax_amount")
        tax_payable = to_float(payload.get("tax_payable"), "tax_payable")

        challan_date = None
        if payload.get("challan_date"):
            try:
                challan_date = datetime.strptime(str(payload["challan_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        eway_bill_date = None
        if payload.get("eway_bill_date"):
            try:
                eway_bill_date = datetime.strptime(str(payload["eway_bill_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        due_date = None
        if payload.get("due_date"):
            try:
                due_date = datetime.strptime(str(payload["due_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        contract_date = None
        if payload.get("contract_date"):
            try:
                contract_date = datetime.strptime(str(payload["contract_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        consignment_date = None
        if payload.get("consignment_date"):
            try:
                consignment_date = datetime.strptime(str(payload["consignment_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        # Look up co_id from branch
        branch_row = db.execute(
            text("SELECT co_id FROM branch_mst WHERE branch_id = :branch_id"),
            {"branch_id": branch_id},
        ).fetchone()
        co_id = dict(branch_row._mapping).get("co_id") if branch_row else None

        # Normalize items — sales_invoice_dtl uses int columns for item_id, item_make_id, uom_id
        normalized_items = []
        for idx, item in enumerate(raw_items, start=1):
            item_val = item.get("item")
            if not item_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].item is required")
            uom_val = item.get("uom")
            if not uom_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].uom is required")

            qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            rate = to_float(item.get("rate"), f"items[{idx}].rate")

            # Calculate line amounts
            amount_without_tax = to_float(item.get("net_amount"), f"items[{idx}].net_amount")
            if amount_without_tax is None and qty and rate:
                amount_without_tax = round(qty * rate, 2)
            line_total_amount = to_float(item.get("total_amount"), f"items[{idx}].total_amount")
            if line_total_amount is None and amount_without_tax is not None:
                line_total_amount = amount_without_tax

            normalized_items.append({
                "hsn_code": item.get("hsn_code"),
                "item_id": int(item_val),
                "item_make_id": to_int(item.get("item_make"), "item_make"),
                "quantity": qty,
                "uom_id": int(uom_val) if str(uom_val).isdigit() else None,
                "rate": rate,
                "discount_type": to_int(item.get("discount_type"), f"items[{idx}].discount_type"),
                "discounted_rate": to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"),
                "discount_amount": to_float(item.get("discount_amount"), f"items[{idx}].discount_amount"),
                "amount_without_tax": amount_without_tax,
                "total_amount": line_total_amount,
                "sales_weight": to_float(item.get("sales_weight"), f"items[{idx}].sales_weight"),
                "remarks": item.get("remarks"),
                "delivery_order_dtl_id": to_int(item.get("delivery_order_dtl_id"), f"items[{idx}].delivery_order_dtl_id"),
                "gst": item.get("gst"),
            })

        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")

        # Insert header
        insert_hdr = insert_sales_invoice()
        header_params = {
            "invoice_date": invoice_date,
            "invoice_no": None,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_delivery_order_id": sales_delivery_order_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "challan_no": payload.get("challan_no"),
            "challan_date": challan_date,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "transporter_name": payload.get("transporter_name"),
            "transporter_address": payload.get("transporter_address"),
            "transporter_state_code": payload.get("transporter_state_code"),
            "transporter_state_name": payload.get("transporter_state_name"),
            "eway_bill_no": payload.get("eway_bill_no"),
            "eway_bill_date": eway_bill_date,
            "invoice_type": invoice_type,
            "footer_notes": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "terms": payload.get("terms"),
            "terms_conditions": payload.get("terms_conditions"),
            "invoice_amount": gross_amount or 0,
            "tax_amount": tax_amount or 0,
            "tax_payable": tax_payable,
            "freight_charges": freight_charges or 0,
            "round_off": round_off or 0,
            "shipping_state_code": to_int(payload.get("shipping_state_code"), "shipping_state_code"),
            "intra_inter_state": payload.get("intra_inter_state"),
            "due_date": due_date,
            "type_of_sale": payload.get("type_of_sale"),
            "tax_id": to_int(payload.get("tax_id"), "tax_id"),
            "container_no": payload.get("container_no"),
            "contract_no": to_int(payload.get("contract_no"), "contract_no"),
            "contract_date": contract_date,
            "consignment_no": payload.get("consignment_no"),
            "consignment_date": consignment_date,
            "status_id": 21,
            "updated_by": user_id,
        }

        result = db.execute(insert_hdr, header_params)
        invoice_id = result.lastrowid
        if not invoice_id:
            raise HTTPException(status_code=500, detail="Failed to create sales invoice header")

        # Insert line items and GST
        line_query = insert_invoice_line_item()
        gst_query = insert_invoice_dtl_gst()
        for item in normalized_items:
            line_result = db.execute(line_query, {
                "invoice_id": invoice_id,
                "hsn_code": item["hsn_code"],
                "item_id": item["item_id"],
                "item_make_id": item["item_make_id"],
                "quantity": item["quantity"] or 0,
                "uom_id": item["uom_id"],
                "rate": item["rate"] or 0,
                "discount_type": item["discount_type"],
                "discounted_rate": item["discounted_rate"],
                "discount_amount": item["discount_amount"],
                "amount_without_tax": item["amount_without_tax"] or 0,
                "total_amount": item["total_amount"] or 0,
                "sales_weight": item["sales_weight"],
                "remarks": item["remarks"],
                "delivery_order_dtl_id": item["delivery_order_dtl_id"],
            })
            line_item_id = line_result.lastrowid

            # Insert GST breakup if provided
            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and line_item_id:
                db.execute(gst_query, {
                    "invoice_line_item_id": line_item_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        db.commit()
        return {"message": "Sales invoice created successfully", "invoice_id": invoice_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update_sales_invoice")
async def update_sales_invoice_endpoint(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update a sales invoice with line items (delete-reinsert pattern)."""
    try:
        invoice_id = to_int(payload.get("id"), "id", required=True)
        branch_id = to_int(payload.get("branch"), "branch", required=True)
        party_id = to_int(payload.get("party"), "party", required=True)

        date_str = payload.get("date")
        if not date_str:
            raise HTTPException(status_code=400, detail="date is required")
        try:
            invoice_date = datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or len(raw_items) == 0:
            raise HTTPException(status_code=400, detail="At least one item row is required")

        # Verify exists
        check_query = text("SELECT invoice_id, status_id, active FROM sales_invoice WHERE invoice_id = :id")
        check_result = db.execute(check_query, {"id": invoice_id}).fetchone()
        if not check_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found or inactive")

        user_id = to_int(token_data.get("user_id"), "user_id")

        transporter_id = to_int(payload.get("transporter"), "transporter")
        sales_delivery_order_id = to_int(payload.get("sales_delivery_order_id"), "sales_delivery_order_id")
        broker_id = to_int(payload.get("broker_id") or payload.get("broker"), "broker_id")
        billing_to_id = to_int(payload.get("billing_to_id"), "billing_to_id")
        shipping_to_id = to_int(payload.get("shipping_to_id"), "shipping_to_id")

        gross_amount = to_float(payload.get("gross_amount"), "gross_amount")
        freight_charges = to_float(payload.get("freight_charges"), "freight_charges")
        round_off = to_float(payload.get("round_off"), "round_off")
        tax_amount = to_float(payload.get("tax_amount"), "tax_amount")
        tax_payable = to_float(payload.get("tax_payable"), "tax_payable")

        challan_date = None
        if payload.get("challan_date"):
            try:
                challan_date = datetime.strptime(str(payload["challan_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        eway_bill_date = None
        if payload.get("eway_bill_date"):
            try:
                eway_bill_date = datetime.strptime(str(payload["eway_bill_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        due_date = None
        if payload.get("due_date"):
            try:
                due_date = datetime.strptime(str(payload["due_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        contract_date = None
        if payload.get("contract_date"):
            try:
                contract_date = datetime.strptime(str(payload["contract_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        consignment_date = None
        if payload.get("consignment_date"):
            try:
                consignment_date = datetime.strptime(str(payload["consignment_date"]), "%Y-%m-%d").date()
            except ValueError:
                pass

        invoice_type = to_int(payload.get("invoice_type"), "invoice_type")

        # Update header
        update_hdr = update_sales_invoice()
        db.execute(update_hdr, {
            "invoice_id": invoice_id,
            "invoice_date": invoice_date,
            "branch_id": branch_id,
            "party_id": party_id,
            "sales_delivery_order_id": sales_delivery_order_id,
            "broker_id": broker_id,
            "billing_to_id": billing_to_id,
            "shipping_to_id": shipping_to_id,
            "challan_no": payload.get("challan_no"),
            "challan_date": challan_date,
            "transporter_id": transporter_id,
            "vehicle_no": payload.get("vehicle_no"),
            "transporter_name": payload.get("transporter_name"),
            "transporter_address": payload.get("transporter_address"),
            "transporter_state_code": payload.get("transporter_state_code"),
            "transporter_state_name": payload.get("transporter_state_name"),
            "eway_bill_no": payload.get("eway_bill_no"),
            "eway_bill_date": eway_bill_date,
            "invoice_type": invoice_type,
            "footer_notes": payload.get("footer_note"),
            "internal_note": payload.get("internal_note"),
            "terms": payload.get("terms"),
            "terms_conditions": payload.get("terms_conditions"),
            "invoice_amount": gross_amount or 0,
            "tax_amount": tax_amount or 0,
            "tax_payable": tax_payable,
            "freight_charges": freight_charges or 0,
            "round_off": round_off or 0,
            "shipping_state_code": to_int(payload.get("shipping_state_code"), "shipping_state_code"),
            "intra_inter_state": payload.get("intra_inter_state"),
            "due_date": due_date,
            "type_of_sale": payload.get("type_of_sale"),
            "tax_id": to_int(payload.get("tax_id"), "tax_id"),
            "container_no": payload.get("container_no"),
            "contract_no": to_int(payload.get("contract_no"), "contract_no"),
            "contract_date": contract_date,
            "consignment_no": payload.get("consignment_no"),
            "consignment_date": consignment_date,
            "updated_by": user_id,
        })

        # Delete old GST data first (FK depends on line items existing)
        delete_gst_q = delete_invoice_dtl_gst()
        db.execute(delete_gst_q, {"invoice_id": invoice_id})

        # Delete old line items
        delete_q = delete_invoice_line_items()
        db.execute(delete_q, {"invoice_id": invoice_id})

        # Re-insert line items and GST
        line_query = insert_invoice_line_item()
        gst_query = insert_invoice_dtl_gst()
        for idx, item in enumerate(raw_items, start=1):
            item_val = item.get("item")
            if not item_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].item is required")
            uom_val = item.get("uom")
            if not uom_val:
                raise HTTPException(status_code=400, detail=f"items[{idx}].uom is required")

            qty = to_positive_float(item.get("quantity"), f"items[{idx}].quantity")
            rate = to_float(item.get("rate"), f"items[{idx}].rate")

            amount_without_tax = to_float(item.get("net_amount"), f"items[{idx}].net_amount")
            if amount_without_tax is None and qty and rate:
                amount_without_tax = round(qty * rate, 2)
            line_total = to_float(item.get("total_amount"), f"items[{idx}].total_amount")
            if line_total is None and amount_without_tax is not None:
                line_total = amount_without_tax

            line_result = db.execute(line_query, {
                "invoice_id": invoice_id,
                "hsn_code": item.get("hsn_code"),
                "item_id": int(item_val),
                "item_make_id": to_int(item.get("item_make"), "item_make"),
                "quantity": qty,
                "uom_id": int(uom_val) if str(uom_val).isdigit() else None,
                "rate": rate,
                "discount_type": item.get("discount_type"),
                "discounted_rate": to_float(item.get("discounted_rate"), f"items[{idx}].discounted_rate"),
                "discount_amount": to_float(item.get("discount_amount"), f"items[{idx}].discount_amount"),
                "amount_without_tax": amount_without_tax,
                "total_amount": line_total,
                "sales_weight": to_float(item.get("sales_weight"), f"items[{idx}].sales_weight"),
                "remarks": item.get("remarks"),
                "delivery_order_dtl_id": to_int(item.get("delivery_order_dtl_id"), f"items[{idx}].delivery_order_dtl_id"),
            })
            line_item_id = line_result.lastrowid

            # Insert GST breakup if provided
            gst_data = item.get("gst")
            if gst_data and isinstance(gst_data, dict) and line_item_id:
                db.execute(gst_query, {
                    "invoice_line_item_id": line_item_id,
                    "igst_amount": to_float(gst_data.get("igst_amount"), "igst_amount"),
                    "igst_percent": to_float(gst_data.get("igst_percent"), "igst_percent"),
                    "cgst_amount": to_float(gst_data.get("cgst_amount"), "cgst_amount"),
                    "cgst_percent": to_float(gst_data.get("cgst_percent"), "cgst_percent"),
                    "sgst_amount": to_float(gst_data.get("sgst_amount"), "sgst_amount"),
                    "sgst_percent": to_float(gst_data.get("sgst_percent"), "sgst_percent"),
                    "gst_total": to_float(gst_data.get("gst_total"), "gst_total"),
                })

        db.commit()
        return {"message": "Sales invoice updated successfully", "invoice_id": invoice_id}
    except HTTPException as exc:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WORKFLOW ENDPOINTS
# =============================================================================


@router.post("/open_sales_invoice")
async def open_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Open a sales invoice (21 -> 1). Generates document number."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        branch_id = to_int(payload.get("branch_id"), "branch_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        doc = dict(doc_result._mapping)

        if doc.get("status_id") != 21:
            raise HTTPException(status_code=400, detail=f"Cannot open invoice with status {doc.get('status_id')}. Expected 21 (Draft).")

        invoice_date = doc.get("invoice_date")
        if not invoice_date:
            raise HTTPException(status_code=400, detail="Invoice date is required to generate document number.")

        current_no = doc.get("invoice_no")
        new_no = None
        new_no_string = None
        if current_no is None or current_no == "" or current_no == 0:
            fy_start, fy_end = get_fy_boundaries(invoice_date)
            max_query = get_max_invoice_no_for_branch_fy()
            max_result = db.execute(max_query, {"branch_id": branch_id, "fy_start_date": fy_start, "fy_end_date": fy_end}).fetchone()
            max_no = dict(max_result._mapping).get("max_doc_no") or 0 if max_result else 0
            new_no = int(max_no) + 1

            # Get prefixes for formatted number string
            branch_row = db.execute(
                text("SELECT bm.branch_prefix, cm.co_prefix FROM branch_mst bm LEFT JOIN co_mst cm ON cm.co_id = bm.co_id WHERE bm.branch_id = :branch_id"),
                {"branch_id": branch_id},
            ).fetchone()
            if branch_row:
                bdata = dict(branch_row._mapping)
                try:
                    new_no_string = format_indent_no(
                        indent_no=new_no,
                        co_prefix=bdata.get("co_prefix"),
                        branch_prefix=bdata.get("branch_prefix"),
                        indent_date=invoice_date,
                        document_type=SALES_DOC_TYPES.get("INVOICE", "SI"),
                    )
                except Exception:
                    new_no_string = str(new_no)

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 1,
            "approval_level": None,
            "invoice_no": new_no,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()

        return {
            "status": "success",
            "new_status_id": 1,
            "message": "Sales invoice opened successfully.",
            "invoice_no": new_no_string if new_no_string else str(current_no) if current_no else None,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error opening sales invoice")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel_draft_sales_invoice")
async def cancel_draft_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Cancel a draft sales invoice (21 -> 6)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        if dict(doc_result._mapping).get("status_id") != 21:
            raise HTTPException(status_code=400, detail="Cannot cancel. Expected status 21 (Draft).")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 6,
            "approval_level": None,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": 6, "message": "Draft cancelled successfully."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send_sales_invoice_for_approval")
async def send_sales_invoice_for_approval(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Send sales invoice for approval (1 -> 20, level=1)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        if dict(doc_result._mapping).get("status_id") != 1:
            raise HTTPException(status_code=400, detail="Cannot send for approval. Expected status 1 (Open).")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": 20,
            "approval_level": 1,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": 20, "new_approval_level": 1, "message": "Sales invoice sent for approval."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve_sales_invoice")
async def approve_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a sales invoice."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        document_amount = float(dict(doc_result._mapping).get("invoice_amount", 0) or 0)

        result = process_approval(
            doc_id=invoice_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_invoice_with_approval_info,
            update_status_fn=update_invoice_status,
            id_param_name="invoice_id",
            doc_name="Sales invoice",
            document_amount=document_amount,
            extra_update_params={"invoice_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject_sales_invoice")
async def reject_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a sales invoice (20 -> 4)."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        menu_id = to_int(payload.get("menu_id"), "menu_id")
        user_id = int(token_data.get("user_id"))
        reason = payload.get("reason")

        result = process_rejection(
            doc_id=invoice_id,
            user_id=user_id,
            menu_id=menu_id,
            db=db,
            get_doc_fn=get_invoice_with_approval_info,
            update_status_fn=update_invoice_status,
            id_param_name="invoice_id",
            doc_name="Sales invoice",
            reason=reason,
            extra_update_params={"invoice_no": None},
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reopen_sales_invoice")
async def reopen_sales_invoice(
    payload: dict,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reopen a cancelled (6 -> 21) or rejected (4 -> 1) sales invoice."""
    try:
        invoice_id = to_int(payload.get("invoice_id"), "invoice_id", required=True)
        user_id = int(token_data.get("user_id"))

        doc_query = get_invoice_with_approval_info()
        doc_result = db.execute(doc_query, {"invoice_id": invoice_id}).fetchone()
        if not doc_result:
            raise HTTPException(status_code=404, detail="Sales invoice not found")
        current_status = dict(doc_result._mapping).get("status_id")

        if current_status == 6:
            new_status_id = 21
        elif current_status == 4:
            new_status_id = 1
        else:
            raise HTTPException(status_code=400, detail=f"Cannot reopen with status {current_status}. Only 6 or 4.")

        update_q = update_invoice_status()
        db.execute(update_q, {
            "invoice_id": invoice_id,
            "status_id": new_status_id,
            "approval_level": None,
            "invoice_no": None,
            "updated_by": user_id,
            "updated_date_time": now_ist(),
        })
        db.commit()
        return {"status": "success", "new_status_id": new_status_id, "message": f"Sales invoice reopened (status: {new_status_id})."}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
