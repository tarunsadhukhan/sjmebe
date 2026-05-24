"""
Accounting API endpoints.
Covers: setup & masters, voucher operations, reports, and opening balances.
"""
import logging
from datetime import date, datetime, timedelta
from fastapi import Depends, Request, HTTPException, APIRouter
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.accounting import query as acc_query
from src.accounting import report_query
from src.accounting import voucher_service
from src.accounting.seed_data import activate_company

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# SETUP & MASTERS
# =============================================================================

# 1. POST /activate_company
@router.post("/activate_company")
async def activate_company_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        user_id = token_data.get("user_id")
        result = activate_company(db, int(co_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 2. GET /ledger_groups
@router.get("/ledger_groups")
async def get_ledger_groups(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_ledger_groups(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3. POST /ledger_groups
@router.post("/ledger_groups")
async def create_ledger_group(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        group_name = body.get("group_name")
        parent_group_id = body.get("parent_group_id")
        nature = body.get("nature")
        affects_gross_profit = body.get("affects_gross_profit", 0)
        is_revenue = body.get("is_revenue", 0)
        normal_balance = body.get("normal_balance")
        is_party_group = body.get("is_party_group", 0)
        sequence_no = body.get("sequence_no", 999)

        if not group_name:
            raise HTTPException(status_code=400, detail="group_name is required")

        result = db.execute(
            text("""
                INSERT INTO acc_ledger_group
                    (co_id, group_name, parent_group_id, nature,
                     affects_gross_profit, is_revenue, normal_balance,
                     is_party_group, is_system_group, sequence_no, active)
                VALUES
                    (:co_id, :group_name, :parent_group_id, :nature,
                     :affects_gross_profit, :is_revenue, :normal_balance,
                     :is_party_group, 0, :sequence_no, 1)
            """),
            {
                "co_id": int(co_id),
                "group_name": group_name,
                "parent_group_id": int(parent_group_id) if parent_group_id else None,
                "nature": nature,
                "affects_gross_profit": int(affects_gross_profit),
                "is_revenue": int(is_revenue),
                "normal_balance": normal_balance,
                "is_party_group": int(is_party_group),
                "sequence_no": int(sequence_no),
            },
        )
        db.commit()

        return {"data": {"acc_ledger_group_id": result.lastrowid}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 4. GET /ledgers
@router.get("/ledgers")
async def get_ledgers(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_type = request.query_params.get("ledger_type")
        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        query = acc_query.get_ledgers(int(co_id))
        rows = db.execute(query, {
            "co_id": int(co_id),
            "ledger_type": ledger_type if ledger_type else None,
            "search": search_param,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 5. POST /ledgers
@router.post("/ledgers")
async def create_ledger(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_name = body.get("ledger_name")
        if not ledger_name:
            raise HTTPException(status_code=400, detail="ledger_name is required")

        acc_ledger_group_id = body.get("acc_ledger_group_id")
        if not acc_ledger_group_id:
            raise HTTPException(status_code=400, detail="acc_ledger_group_id is required")

        result = db.execute(
            text("""
                INSERT INTO acc_ledger
                    (co_id, acc_ledger_group_id, ledger_name, ledger_code,
                     ledger_type, party_id, credit_days, credit_limit,
                     opening_balance, opening_balance_type, opening_fy_id,
                     gst_applicable, hsn_sac_code, is_system_ledger,
                     is_related_party, active)
                VALUES
                    (:co_id, :acc_ledger_group_id, :ledger_name, :ledger_code,
                     :ledger_type, :party_id, :credit_days, :credit_limit,
                     :opening_balance, :opening_balance_type, :opening_fy_id,
                     :gst_applicable, :hsn_sac_code, 0,
                     :is_related_party, 1)
            """),
            {
                "co_id": int(co_id),
                "acc_ledger_group_id": int(acc_ledger_group_id),
                "ledger_name": ledger_name,
                "ledger_code": body.get("ledger_code"),
                "ledger_type": body.get("ledger_type", "G"),
                "party_id": int(body["party_id"]) if body.get("party_id") else None,
                "credit_days": int(body["credit_days"]) if body.get("credit_days") else None,
                "credit_limit": float(body["credit_limit"]) if body.get("credit_limit") else None,
                "opening_balance": float(body["opening_balance"]) if body.get("opening_balance") else None,
                "opening_balance_type": body.get("opening_balance_type"),
                "opening_fy_id": int(body["opening_fy_id"]) if body.get("opening_fy_id") else None,
                "gst_applicable": int(body["gst_applicable"]) if body.get("gst_applicable") is not None else 0,
                "hsn_sac_code": body.get("hsn_sac_code"),
                "is_related_party": int(body["is_related_party"]) if body.get("is_related_party") is not None else 0,
            },
        )
        db.commit()

        return {"data": {"acc_ledger_id": result.lastrowid}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 6. PUT /ledgers/{ledger_id}
@router.put("/ledgers/{ledger_id}")
async def update_ledger(
    ledger_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        db.execute(
            text("""
                UPDATE acc_ledger
                SET acc_ledger_group_id = COALESCE(:acc_ledger_group_id, acc_ledger_group_id),
                    ledger_name = COALESCE(:ledger_name, ledger_name),
                    ledger_code = COALESCE(:ledger_code, ledger_code),
                    ledger_type = COALESCE(:ledger_type, ledger_type),
                    party_id = COALESCE(:party_id, party_id),
                    credit_days = COALESCE(:credit_days, credit_days),
                    credit_limit = COALESCE(:credit_limit, credit_limit),
                    opening_balance = COALESCE(:opening_balance, opening_balance),
                    opening_balance_type = COALESCE(:opening_balance_type, opening_balance_type),
                    opening_fy_id = COALESCE(:opening_fy_id, opening_fy_id),
                    gst_applicable = COALESCE(:gst_applicable, gst_applicable),
                    hsn_sac_code = COALESCE(:hsn_sac_code, hsn_sac_code),
                    is_related_party = COALESCE(:is_related_party, is_related_party)
                WHERE acc_ledger_id = :ledger_id
                    AND co_id = :co_id
                    AND is_system_ledger = 0
            """),
            {
                "ledger_id": int(ledger_id),
                "co_id": int(co_id),
                "acc_ledger_group_id": int(body["acc_ledger_group_id"]) if body.get("acc_ledger_group_id") else None,
                "ledger_name": body.get("ledger_name"),
                "ledger_code": body.get("ledger_code"),
                "ledger_type": body.get("ledger_type"),
                "party_id": int(body["party_id"]) if body.get("party_id") else None,
                "credit_days": int(body["credit_days"]) if body.get("credit_days") else None,
                "credit_limit": float(body["credit_limit"]) if body.get("credit_limit") else None,
                "opening_balance": float(body["opening_balance"]) if body.get("opening_balance") else None,
                "opening_balance_type": body.get("opening_balance_type"),
                "opening_fy_id": int(body["opening_fy_id"]) if body.get("opening_fy_id") else None,
                "gst_applicable": int(body["gst_applicable"]) if body.get("gst_applicable") is not None else None,
                "hsn_sac_code": body.get("hsn_sac_code"),
                "is_related_party": int(body["is_related_party"]) if body.get("is_related_party") is not None else None,
            },
        )
        db.commit()

        return {"data": {"acc_ledger_id": int(ledger_id), "updated": True}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 7. GET /parties_dropdown (for ledger party autocomplete)
@router.get("/parties_dropdown")
async def get_parties_dropdown(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        search_param = f"%{search}%" if search else None

        query = acc_query.get_parties_for_dropdown()
        rows = db.execute(
            query,
            {"co_id": int(co_id), "search": search_param}
        ).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 8. GET /voucher_types
@router.get("/voucher_types")
async def get_voucher_types(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_voucher_types(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 8. GET /financial_years
@router.get("/financial_years")
async def get_financial_years(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_financial_years(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 9. POST /financial_years
@router.post("/financial_years")
async def create_financial_year(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        fy_start = body.get("fy_start")
        fy_end = body.get("fy_end")
        fy_label = body.get("fy_label")

        if not fy_start or not fy_end or not fy_label:
            raise HTTPException(
                status_code=400,
                detail="fy_start, fy_end, and fy_label are required",
            )

        # Extract user_id from token
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="User ID not found in token")

        # Insert financial year
        result = db.execute(
            text("""
                INSERT INTO acc_financial_year
                    (co_id, fy_start, fy_end, fy_label, is_active, is_locked, updated_by)
                VALUES
                    (:co_id, :fy_start, :fy_end, :fy_label, 1, 0, :updated_by)
            """),
            {
                "co_id": int(co_id),
                "fy_start": fy_start,
                "fy_end": fy_end,
                "fy_label": fy_label,
                "updated_by": int(user_id),
            },
        )
        fy_id = result.lastrowid

        # Create 12 period_lock rows
        fy_start_date = datetime.strptime(fy_start, "%Y-%m-%d").date()
        for month_offset in range(12):
            period_month = ((fy_start_date.month - 1 + month_offset) % 12) + 1
            period_year = fy_start_date.year + ((fy_start_date.month - 1 + month_offset) // 12)

            # Calculate period start and end dates
            period_start = date(period_year, period_month, 1)
            if period_month == 12:
                period_end = date(period_year + 1, 1, 1)
            else:
                period_end = date(period_year, period_month + 1, 1)
            # Last day of the month
            period_end = date(period_end.year, period_end.month, period_end.day) - timedelta(days=1)

            db.execute(
                text("""
                    INSERT INTO acc_period_lock
                        (acc_financial_year_id, period_month, period_start,
                         period_end, is_locked, updated_by)
                    VALUES
                        (:fy_id, :period_month, :period_start,
                         :period_end, 0, :updated_by)
                """),
                {
                    "fy_id": int(fy_id),
                    "period_month": month_offset + 1,
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                    "updated_by": int(user_id),
                },
            )

        db.commit()

        return {"data": {"acc_financial_year_id": fy_id, "periods_created": 12}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 10. GET /account_determinations
@router.get("/account_determinations")
async def get_account_determinations(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = acc_query.get_account_determinations(int(co_id))
        rows = db.execute(query, {"co_id": int(co_id)}).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 11. PUT /account_determinations
@router.put("/account_determinations")
async def update_account_determinations(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        rules = body if isinstance(body, list) else body.get("rules", [])

        if not rules:
            raise HTTPException(status_code=400, detail="No rules provided")

        for rule in rules:
            acc_account_determination_id = rule.get("acc_account_determination_id")
            acc_ledger_id = rule.get("acc_ledger_id")

            if not acc_account_determination_id:
                raise HTTPException(
                    status_code=400,
                    detail="acc_account_determination_id is required for each rule",
                )

            db.execute(
                text("""
                    UPDATE acc_account_determination
                    SET acc_ledger_id = :acc_ledger_id
                    WHERE acc_account_determination_id = :id
                """),
                {
                    "id": int(acc_account_determination_id),
                    "acc_ledger_id": int(acc_ledger_id) if acc_ledger_id else None,
                },
            )

        db.commit()

        return {"data": {"updated": len(rules)}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VOUCHER OPERATIONS
# =============================================================================

# 12. GET /vouchers
@router.get("/vouchers")
async def get_vouchers(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        voucher_type_id = request.query_params.get("voucher_type_id")
        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        party_id = request.query_params.get("party_id")
        source_doc_type = request.query_params.get("source_doc_type")
        status_id = request.query_params.get("status_id")
        page = int(request.query_params.get("page", 1))
        limit = int(request.query_params.get("limit", 50))
        offset = (page - 1) * limit

        query = acc_query.get_vouchers_list(int(co_id))
        rows = db.execute(query, {
            "co_id": int(co_id),
            "branch_id": int(branch_id) if branch_id else None,
            "voucher_type_id": int(voucher_type_id) if voucher_type_id else None,
            "from_date": from_date if from_date else None,
            "to_date": to_date if to_date else None,
            "party_id": int(party_id) if party_id else None,
            "source_doc_type": source_doc_type if source_doc_type else None,
            "status_id": int(status_id) if status_id else None,
            "limit": limit,
            "offset": offset,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data, "page": page, "limit": limit}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 13. GET /vouchers/{voucher_id}
@router.get("/vouchers/{voucher_id}")
async def get_voucher_detail(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # Header
        header_query = acc_query.get_voucher_detail(int(voucher_id))
        header_row = db.execute(
            header_query, {"voucher_id": int(voucher_id)}
        ).fetchone()

        if not header_row:
            raise HTTPException(status_code=404, detail="Voucher not found")

        header = dict(header_row._mapping)

        # Lines
        lines_query = acc_query.get_voucher_lines(int(voucher_id))
        lines_rows = db.execute(
            lines_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        lines = [dict(r._mapping) for r in lines_rows]

        # GST
        gst_query = acc_query.get_voucher_gst(int(voucher_id))
        gst_rows = db.execute(
            gst_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        gst = [dict(r._mapping) for r in gst_rows]

        # Bill References
        bill_refs_query = acc_query.get_voucher_bill_refs(int(voucher_id))
        bill_refs_rows = db.execute(
            bill_refs_query, {"voucher_id": int(voucher_id)}
        ).fetchall()
        bill_refs = [dict(r._mapping) for r in bill_refs_rows]

        header["lines"] = lines
        header["gst"] = gst
        header["bill_refs"] = bill_refs

        return {"data": header}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 14. POST /vouchers
@router.post("/vouchers")
async def create_voucher(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        co_id = body.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = body.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        user_id = token_data.get("user_id")

        result = voucher_service.create_manual_voucher(
            db, int(co_id), int(branch_id), int(user_id), body
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 15. PUT /vouchers/{voucher_id}
@router.put("/vouchers/{voucher_id}")
async def update_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        user_id = token_data.get("user_id")

        result = voucher_service.update_draft_voucher(
            db, int(voucher_id), int(user_id), body
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 16. POST /vouchers/{voucher_id}/open
@router.post("/vouchers/{voucher_id}/open")
async def open_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.open_voucher(db, int(voucher_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 17. POST /vouchers/{voucher_id}/cancel
@router.post("/vouchers/{voucher_id}/cancel")
async def cancel_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.cancel_voucher(db, int(voucher_id), int(user_id))
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 18. POST /vouchers/{voucher_id}/send_for_approval
@router.post("/vouchers/{voucher_id}/send_for_approval")
async def send_voucher_for_approval(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.send_for_approval(
            db, int(voucher_id), int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 19. POST /vouchers/{voucher_id}/approve
@router.post("/vouchers/{voucher_id}/approve")
async def approve_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.approve_voucher(
            db, int(voucher_id), int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 20. POST /vouchers/{voucher_id}/reject
@router.post("/vouchers/{voucher_id}/reject")
async def reject_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        reason = body.get("reason", "")
        user_id = token_data.get("user_id")

        result = voucher_service.reject_voucher(
            db, int(voucher_id), int(user_id), reason
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 21. POST /vouchers/{voucher_id}/reopen
@router.post("/vouchers/{voucher_id}/reopen")
async def reopen_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        user_id = token_data.get("user_id")
        result = voucher_service.reopen_voucher(
            db, int(voucher_id), int(user_id)
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 22. POST /vouchers/{voucher_id}/reverse
@router.post("/vouchers/{voucher_id}/reverse")
async def reverse_voucher(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        narration = body.get("narration")
        user_id = token_data.get("user_id")

        result = voucher_service.reverse_voucher(
            db, int(voucher_id), int(user_id), narration
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 23. POST /vouchers/{voucher_id}/settle_bills
@router.post("/vouchers/{voucher_id}/settle_bills")
async def settle_bills(
    voucher_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        settlements = body.get("settlements", [])

        if not settlements:
            raise HTTPException(status_code=400, detail="settlements list is required")

        user_id = token_data.get("user_id")

        result = voucher_service.settle_bills(
            db, int(voucher_id), int(user_id), settlements
        )
        return {"data": result}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# REPORTS
# =============================================================================

# 24. GET /reports/trial_balance
@router.get("/reports/trial_balance")
async def trial_balance(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_trial_balance()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 25. GET /reports/profit_loss
@router.get("/reports/profit_loss")
async def profit_loss(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_profit_loss()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 26. GET /reports/balance_sheet
@router.get("/reports/balance_sheet")
async def balance_sheet(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_balance_sheet()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 27. GET /reports/ledger_report
@router.get("/reports/ledger_report")
async def ledger_report(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        ledger_id = request.query_params.get("ledger_id")
        if not ledger_id:
            raise HTTPException(status_code=400, detail="ledger_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_ledger_report()
        rows = db.execute(query, {
            "ledger_id": int(ledger_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 28. GET /reports/day_book
@router.get("/reports/day_book")
async def day_book(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")
        voucher_type_id = request.query_params.get("voucher_type_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_day_book()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
            "voucher_type_id": int(voucher_type_id) if voucher_type_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 29. GET /reports/cash_book
@router.get("/reports/cash_book")
async def cash_book(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_id = request.query_params.get("branch_id")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_cash_book()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 30. GET /reports/party_outstanding
@router.get("/reports/party_outstanding")
async def party_outstanding(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        party_type = request.query_params.get("party_type")
        branch_id = request.query_params.get("branch_id")

        query = report_query.get_party_outstanding()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "party_type": party_type if party_type else None,
            "branch_id": int(branch_id) if branch_id else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 31. GET /reports/ageing_analysis
@router.get("/reports/ageing_analysis")
async def ageing_analysis(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        query = report_query.get_ageing_analysis()
        rows = db.execute(query, {
            "co_id": int(co_id),
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 32. GET /reports/gst_summary
@router.get("/reports/gst_summary")
async def gst_summary(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        branch_gstin = request.query_params.get("branch_gstin")

        if not from_date or not to_date:
            raise HTTPException(status_code=400, detail="from_date and to_date are required")

        query = report_query.get_gst_summary()
        rows = db.execute(query, {
            "co_id": int(co_id),
            "from_date": from_date,
            "to_date": to_date,
            "branch_gstin": branch_gstin if branch_gstin else None,
        }).fetchall()
        data = [dict(r._mapping) for r in rows]
        return {"data": data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OPENING BALANCE
# =============================================================================

# 33. POST /opening_bills
@router.post("/opening_bills")
async def import_opening_bills(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        body = await request.json()
        bills = body if isinstance(body, list) else body.get("bills", [])

        if not bills:
            raise HTTPException(status_code=400, detail="No bills provided")

        user_id = token_data.get("user_id")
        inserted_count = 0

        for bill in bills:
            co_id = bill.get("co_id")
            if not co_id:
                raise HTTPException(status_code=400, detail="co_id is required for each bill")

            db.execute(
                text("""
                    INSERT INTO acc_opening_bill
                        (co_id, party_id, bill_no, bill_date, due_date,
                         bill_type, original_amount, pending_amount,
                         acc_ledger_id, branch_id, narration,
                         created_by, active)
                    VALUES
                        (:co_id, :party_id, :bill_no, :bill_date, :due_date,
                         :bill_type, :original_amount, :pending_amount,
                         :acc_ledger_id, :branch_id, :narration,
                         :created_by, 1)
                """),
                {
                    "co_id": int(co_id),
                    "party_id": int(bill["party_id"]) if bill.get("party_id") else None,
                    "bill_no": bill.get("bill_no"),
                    "bill_date": bill.get("bill_date"),
                    "due_date": bill.get("due_date"),
                    "bill_type": bill.get("bill_type", "PAYABLE"),
                    "original_amount": float(bill["original_amount"]) if bill.get("original_amount") else 0,
                    "pending_amount": float(bill["pending_amount"]) if bill.get("pending_amount") else float(bill.get("original_amount", 0)),
                    "acc_ledger_id": int(bill["acc_ledger_id"]) if bill.get("acc_ledger_id") else None,
                    "branch_id": int(bill["branch_id"]) if bill.get("branch_id") else None,
                    "narration": bill.get("narration"),
                    "created_by": int(user_id),
                },
            )
            inserted_count += 1

        db.commit()

        return {"data": {"inserted": inserted_count}}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
