"""Auto-posting service — creates accounting vouchers automatically
when procurement bill pass, jute bill pass, or sales invoices are approved."""
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.common.utils import now_ist

logger = logging.getLogger(__name__)

# Status for auto-posted vouchers (immediately approved)
STATUS_APPROVED = 3
STATUS_CANCELLED = 6


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_account(db: Session, co_id: int, doc_type: str, line_type: str):
    """Look up ledger_id from acc_account_determination."""
    row = db.execute(
        text("""
            SELECT acc_ledger_id FROM acc_account_determination
            WHERE co_id = :co_id AND doc_type = :doc_type AND line_type = :line_type
            AND is_default = 1 AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "doc_type": doc_type, "line_type": line_type},
    ).fetchone()
    return row._mapping["acc_ledger_id"] if row else None


def _get_party_ledger(db: Session, co_id: int, party_id: int):
    """Find ledger linked to a party."""
    row = db.execute(
        text("""
            SELECT acc_ledger_id FROM acc_ledger
            WHERE co_id = :co_id AND party_id = :pid AND ledger_type = 'P' AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "pid": int(party_id)},
    ).fetchone()
    return row._mapping["acc_ledger_id"] if row else None


def _check_duplicate(db: Session, source_doc_type: str, source_doc_id: int) -> bool:
    """Check if voucher already exists for source document.

    Returns True if a non-cancelled voucher already exists.
    """
    row = db.execute(
        text("""
            SELECT acc_voucher_id FROM acc_voucher
            WHERE source_doc_type = :sdt AND source_doc_id = :sdi
            AND status_id != :cancelled
            LIMIT 1
        """),
        {
            "sdt": source_doc_type,
            "sdi": int(source_doc_id),
            "cancelled": STATUS_CANCELLED,
        },
    ).fetchone()
    return row is not None


def _get_fy_and_type(
    db: Session, co_id: int, voucher_date, type_category: str
) -> dict | None:
    """Get financial year and voucher type IDs.

    Returns dict with acc_fy_id and acc_voucher_type_id, or None on failure.
    """
    fy_row = db.execute(
        text("""
            SELECT acc_fy_id, fy_start_date, fy_end_date
            FROM acc_financial_year
            WHERE co_id = :co_id
              AND :vdate BETWEEN fy_start_date AND fy_end_date
              AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "vdate": voucher_date},
    ).fetchone()
    if not fy_row:
        return None

    vt_row = db.execute(
        text("""
            SELECT acc_voucher_type_id
            FROM acc_voucher_type
            WHERE co_id = :co_id
              AND type_category = :cat
              AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "cat": type_category},
    ).fetchone()
    if not vt_row:
        return None

    return {
        "acc_fy_id": fy_row._mapping["acc_fy_id"],
        "acc_voucher_type_id": vt_row._mapping["acc_voucher_type_id"],
    }


def _next_number(
    db: Session, co_id: int, branch_id: int, voucher_type_id: int, fy_id: int
) -> tuple[str, int]:
    """Generate next voucher number.

    Returns (voucher_no, voucher_seq).
    """
    row = db.execute(
        text("""
            SELECT COALESCE(MAX(voucher_seq), 0) + 1 AS next_seq
            FROM acc_voucher
            WHERE co_id = :co_id
              AND branch_id = :branch_id
              AND acc_voucher_type_id = :vtid
              AND acc_fy_id = :fy_id
        """),
        {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "vtid": int(voucher_type_id),
            "fy_id": int(fy_id),
        },
    ).fetchone()
    next_seq = row._mapping["next_seq"] if row else 1

    prefix_row = db.execute(
        text("""
            SELECT voucher_prefix
            FROM acc_voucher_type
            WHERE acc_voucher_type_id = :vtid
        """),
        {"vtid": int(voucher_type_id)},
    ).fetchone()
    prefix = prefix_row._mapping["voucher_prefix"] if prefix_row else "V"

    voucher_no = f"{prefix}{next_seq:05d}"
    return voucher_no, int(next_seq)


def _insert_voucher_header(
    db: Session,
    co_id: int,
    branch_id: int,
    voucher_type_id: int,
    fy_id: int,
    voucher_no: str,
    voucher_seq: int,
    voucher_date,
    narration: str,
    source_doc_type: str,
    source_doc_id: int,
    user_id: int,
) -> int:
    """Insert voucher header with is_auto_posted=1, status_id=3."""
    result = db.execute(
        text("""
            INSERT INTO acc_voucher
                (co_id, branch_id, acc_voucher_type_id, acc_fy_id,
                 voucher_no, voucher_seq, voucher_date, narration,
                 status_id, is_auto_posted, is_reversed,
                 source_doc_type, source_doc_id,
                 created_by, created_date_time)
            VALUES
                (:co_id, :branch_id, :vtid, :fy_id,
                 :vno, :vseq, :vdate, :narration,
                 :status, 1, 0,
                 :sdt, :sdi,
                 :uid, :now)
        """),
        {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "vtid": int(voucher_type_id),
            "fy_id": int(fy_id),
            "vno": voucher_no,
            "vseq": voucher_seq,
            "vdate": voucher_date,
            "narration": narration,
            "status": STATUS_APPROVED,
            "sdt": source_doc_type,
            "sdi": int(source_doc_id),
            "uid": int(user_id),
            "now": now_ist(),
        },
    )
    return result.lastrowid


def _insert_voucher_line(
    db: Session,
    voucher_id: int,
    line_no: int,
    ledger_id: int,
    debit: float,
    credit: float,
    narration: str = "",
    party_id: int | None = None,
    branch_id: int | None = None,
):
    """Insert a single voucher line."""
    db.execute(
        text("""
            INSERT INTO acc_voucher_line
                (acc_voucher_id, line_no, acc_ledger_id, party_id,
                 debit_amount, credit_amount, narration,
                 cost_center_id, branch_id)
            VALUES
                (:vid, :lno, :lid, :pid,
                 :dr, :cr, :narr,
                 NULL, :bid)
        """),
        {
            "vid": int(voucher_id),
            "lno": line_no,
            "lid": int(ledger_id),
            "pid": int(party_id) if party_id else None,
            "dr": round(float(debit), 2),
            "cr": round(float(credit), 2),
            "narr": narration,
            "bid": int(branch_id) if branch_id else None,
        },
    )


def _insert_bill_ref(
    db: Session,
    co_id: int,
    voucher_id: int,
    party_id: int,
    bill_no: str,
    bill_date,
    total_amount: float,
    bill_type: str,
):
    """Create acc_bill_ref entry for tracking outstanding amounts."""
    db.execute(
        text("""
            INSERT INTO acc_bill_ref
                (co_id, acc_voucher_id, party_id,
                 bill_no, bill_date, bill_type,
                 total_amount, pending_amount, status)
            VALUES
                (:co_id, :vid, :pid,
                 :bno, :bdate, :btype,
                 :total, :pending, 'OPEN')
        """),
        {
            "co_id": int(co_id),
            "vid": int(voucher_id),
            "pid": int(party_id),
            "bno": bill_no,
            "bdate": bill_date,
            "btype": bill_type,
            "total": round(float(total_amount), 2),
            "pending": round(float(total_amount), 2),
        },
    )


def _insert_approval_log(
    db: Session, voucher_id: int, user_id: int, remarks: str | None = None
):
    """Insert approval log for auto-posted voucher."""
    db.execute(
        text("""
            INSERT INTO acc_voucher_approval_log
                (acc_voucher_id, action_by, action_date, from_status_id,
                 to_status_id, remarks)
            VALUES
                (:vid, :uid, :now, 0, :ts, :rem)
        """),
        {
            "vid": int(voucher_id),
            "uid": int(user_id),
            "now": now_ist(),
            "ts": STATUS_APPROVED,
            "rem": remarks or "Auto-posted",
        },
    )


# =============================================================================
# PROCUREMENT BILL PASS
# =============================================================================

def auto_post_procurement_billpass(
    db: Session, inward_id: int, user_id: int
) -> dict:
    """Create PURCHASE voucher when procurement bill pass is approved.

    Reads proc_inward header and detail lines with GST, then creates:
      DR  Purchase A/c         (sum of taxable amounts)
      DR  CGST Input           (from proc_gst)
      DR  SGST Input           (from proc_gst)
      DR  IGST Input           (from proc_gst)
      DR  Round Off            (if positive)
      CR  Sundry Creditors     (net payable - party ledger)
      CR  Round Off            (if negative)
    """
    # --- 1. Duplicate check ---------------------------------------------------
    if _check_duplicate(db, "PROC_BILLPASS", inward_id):
        logger.warning(
            "Duplicate auto-post attempt for proc_inward %s", inward_id
        )
        return {"success": False, "error": "Voucher already exists for this bill pass."}

    # --- 2. Read header -------------------------------------------------------
    hdr = db.execute(
        text("""
            SELECT pi.co_id, pi.branch_id, pi.supplier_id,
                   pi.invoice_no, pi.invoice_date,
                   pi.net_amount, pi.round_off_value
            FROM proc_inward pi
            WHERE pi.inward_id = :iid
        """),
        {"iid": int(inward_id)},
    ).fetchone()
    if not hdr:
        return {"success": False, "error": f"Inward {inward_id} not found."}

    h = hdr._mapping
    co_id = h["co_id"]
    branch_id = h["branch_id"]
    supplier_id = h["supplier_id"]
    invoice_no = h["invoice_no"]
    invoice_date = h["invoice_date"]
    net_amount = float(h["net_amount"] or 0)
    round_off = float(h["round_off_value"] or 0)

    # --- 3. Read detail lines for taxable amounts -----------------------------
    dtl_rows = db.execute(
        text("""
            SELECT COALESCE(SUM(pid.taxable_amount), 0) AS total_taxable
            FROM proc_inward_dtl pid
            WHERE pid.inward_id = :iid
        """),
        {"iid": int(inward_id)},
    ).fetchone()
    total_taxable = float(dtl_rows._mapping["total_taxable"]) if dtl_rows else 0.0

    # --- 4. Read GST amounts --------------------------------------------------
    gst_row = db.execute(
        text("""
            SELECT COALESCE(SUM(pg.cgst_amount), 0) AS cgst,
                   COALESCE(SUM(pg.sgst_amount), 0) AS sgst,
                   COALESCE(SUM(pg.igst_amount), 0) AS igst
            FROM proc_gst pg
            JOIN proc_inward_dtl pid ON pid.inward_dtl_id = pg.inward_dtl_id
            WHERE pid.inward_id = :iid
        """),
        {"iid": int(inward_id)},
    ).fetchone()
    cgst = float(gst_row._mapping["cgst"]) if gst_row else 0.0
    sgst = float(gst_row._mapping["sgst"]) if gst_row else 0.0
    igst = float(gst_row._mapping["igst"]) if gst_row else 0.0

    # --- 5. FY and voucher type -----------------------------------------------
    fy_type = _get_fy_and_type(db, co_id, invoice_date, "PURCHASE")
    if not fy_type:
        return {
            "success": False,
            "error": "Financial year or PURCHASE voucher type not found.",
        }

    # --- 6. Account determinations --------------------------------------------
    purchase_ledger = _get_account(db, co_id, "PROC_BILLPASS", "PURCHASE")
    cgst_ledger = _get_account(db, co_id, "PROC_BILLPASS", "CGST_INPUT")
    sgst_ledger = _get_account(db, co_id, "PROC_BILLPASS", "SGST_INPUT")
    igst_ledger = _get_account(db, co_id, "PROC_BILLPASS", "IGST_INPUT")
    roundoff_ledger = _get_account(db, co_id, "PROC_BILLPASS", "ROUND_OFF")
    creditor_ledger = _get_party_ledger(db, co_id, supplier_id)

    if not purchase_ledger:
        return {"success": False, "error": "Purchase account not configured."}
    if not creditor_ledger:
        return {
            "success": False,
            "error": f"Party ledger not found for supplier {supplier_id}.",
        }

    # --- 7. Generate voucher number -------------------------------------------
    voucher_no, voucher_seq = _next_number(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
    )

    # --- 8. Insert voucher header ---------------------------------------------
    narration = f"Auto: Procurement Bill Pass - Invoice {invoice_no}"
    voucher_id = _insert_voucher_header(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
        voucher_no, voucher_seq, invoice_date,
        narration, "PROC_BILLPASS", inward_id, user_id,
    )

    # --- 9. Insert voucher lines ----------------------------------------------
    line_no = 0

    # DR Purchase A/c
    if total_taxable > 0:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, purchase_ledger,
            debit=total_taxable, credit=0,
            narration="Purchase amount", branch_id=branch_id,
        )

    # DR CGST Input
    if cgst > 0 and cgst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, cgst_ledger,
            debit=cgst, credit=0,
            narration="CGST Input", branch_id=branch_id,
        )

    # DR SGST Input
    if sgst > 0 and sgst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, sgst_ledger,
            debit=sgst, credit=0,
            narration="SGST Input", branch_id=branch_id,
        )

    # DR IGST Input
    if igst > 0 and igst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, igst_ledger,
            debit=igst, credit=0,
            narration="IGST Input", branch_id=branch_id,
        )

    # DR/CR Round Off
    if round_off != 0 and roundoff_ledger:
        line_no += 1
        if round_off > 0:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=abs(round_off), credit=0,
                narration="Round Off", branch_id=branch_id,
            )
        else:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=0, credit=abs(round_off),
                narration="Round Off", branch_id=branch_id,
            )

    # CR Sundry Creditors (party)
    line_no += 1
    _insert_voucher_line(
        db, voucher_id, line_no, creditor_ledger,
        debit=0, credit=net_amount,
        narration=f"Creditor - Invoice {invoice_no}",
        party_id=supplier_id, branch_id=branch_id,
    )

    # --- 10. Bill reference ---------------------------------------------------
    _insert_bill_ref(
        db, co_id, voucher_id, supplier_id,
        invoice_no, invoice_date, net_amount, "PAYABLE",
    )

    # --- 11. Approval log and commit ------------------------------------------
    _insert_approval_log(db, voucher_id, user_id, narration)
    db.commit()

    logger.info(
        "Auto-posted procurement bill pass voucher %s (id=%s) for inward %s",
        voucher_no, voucher_id, inward_id,
    )

    return {
        "success": True,
        "voucher_id": voucher_id,
        "voucher_no": voucher_no,
    }


# =============================================================================
# JUTE BILL PASS
# =============================================================================

def auto_post_jute_billpass(
    db: Session, mr_id: int, user_id: int
) -> dict:
    """Create PURCHASE voucher when jute bill pass is approved.

    Reads jute_mr header, then creates:
      DR  Jute Purchase A/c    (total_amount)
      DR  Round Off            (if positive)
      CR  Sundry Creditors     (net_total - party ledger)
      CR  TDS Payable          (tds_amount)
      CR  Round Off            (if negative)
    If claim_amount:
      DR  Claims Receivable
      CR  Sundry Creditors
    If frieght_paid (note: DB typo preserved):
      DR  Freight Inward
      CR  Cash
    """
    # --- 1. Duplicate check ---------------------------------------------------
    if _check_duplicate(db, "JUTE_BILLPASS", mr_id):
        logger.warning(
            "Duplicate auto-post attempt for jute_mr %s", mr_id
        )
        return {"success": False, "error": "Voucher already exists for this jute bill pass."}

    # --- 2. Read header -------------------------------------------------------
    hdr = db.execute(
        text("""
            SELECT jm.co_id, jm.branch_id, jm.party_id,
                   jm.total_amount, jm.tds_amount, jm.claim_amount,
                   jm.frieght_paid, jm.roundoff, jm.net_total,
                   jm.mr_date, jm.mr_no
            FROM jute_mr jm
            WHERE jm.mr_id = :mid
        """),
        {"mid": int(mr_id)},
    ).fetchone()
    if not hdr:
        return {"success": False, "error": f"Jute MR {mr_id} not found."}

    h = hdr._mapping
    co_id = h["co_id"]
    branch_id = h["branch_id"]
    party_id = h["party_id"]
    total_amount = float(h["total_amount"] or 0)
    tds_amount = float(h["tds_amount"] or 0)
    claim_amount = float(h["claim_amount"] or 0)
    frieght_paid = float(h["frieght_paid"] or 0)
    roundoff = float(h["roundoff"] or 0)
    net_total = float(h["net_total"] or 0)
    mr_date = h["mr_date"]
    mr_no = h.get("mr_no", "")

    # --- 3. FY and voucher type -----------------------------------------------
    fy_type = _get_fy_and_type(db, co_id, mr_date, "PURCHASE")
    if not fy_type:
        return {
            "success": False,
            "error": "Financial year or PURCHASE voucher type not found.",
        }

    # --- 4. Account determinations --------------------------------------------
    jute_purchase_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "JUTE_PURCHASE")
    tds_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "TDS_PAYABLE")
    roundoff_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "ROUND_OFF")
    claims_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "CLAIMS_RECEIVABLE")
    freight_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "FREIGHT_INWARD")
    cash_ledger = _get_account(db, co_id, "JUTE_BILLPASS", "CASH")
    creditor_ledger = _get_party_ledger(db, co_id, party_id)

    if not jute_purchase_ledger:
        return {"success": False, "error": "Jute Purchase account not configured."}
    if not creditor_ledger:
        return {
            "success": False,
            "error": f"Party ledger not found for party {party_id}.",
        }

    # --- 5. Generate voucher number -------------------------------------------
    voucher_no, voucher_seq = _next_number(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
    )

    # --- 6. Insert voucher header ---------------------------------------------
    narration = f"Auto: Jute Bill Pass - MR {mr_no}"
    voucher_id = _insert_voucher_header(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
        voucher_no, voucher_seq, mr_date,
        narration, "JUTE_BILLPASS", mr_id, user_id,
    )

    # --- 7. Insert voucher lines — main entry ---------------------------------
    line_no = 0

    # DR Jute Purchase A/c
    if total_amount > 0:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, jute_purchase_ledger,
            debit=total_amount, credit=0,
            narration="Jute Purchase", branch_id=branch_id,
        )

    # DR/CR Round Off
    if roundoff != 0 and roundoff_ledger:
        line_no += 1
        if roundoff > 0:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=abs(roundoff), credit=0,
                narration="Round Off", branch_id=branch_id,
            )
        else:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=0, credit=abs(roundoff),
                narration="Round Off", branch_id=branch_id,
            )

    # CR Sundry Creditors (net_total)
    if net_total > 0:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, creditor_ledger,
            debit=0, credit=net_total,
            narration=f"Creditor - MR {mr_no}",
            party_id=party_id, branch_id=branch_id,
        )

    # CR TDS Payable
    if tds_amount > 0 and tds_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, tds_ledger,
            debit=0, credit=tds_amount,
            narration="TDS Payable", branch_id=branch_id,
        )

    # --- 8. Claim entry (if applicable) ---------------------------------------
    if claim_amount > 0 and claims_ledger and creditor_ledger:
        # DR Claims Receivable
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, claims_ledger,
            debit=claim_amount, credit=0,
            narration="Claims Receivable", branch_id=branch_id,
        )
        # CR Sundry Creditors (for claim)
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, creditor_ledger,
            debit=0, credit=claim_amount,
            narration="Creditor - Claim adjustment",
            party_id=party_id, branch_id=branch_id,
        )

    # --- 9. Freight entry (if applicable) -------------------------------------
    if frieght_paid > 0 and freight_ledger and cash_ledger:
        # DR Freight Inward
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, freight_ledger,
            debit=frieght_paid, credit=0,
            narration="Freight Inward", branch_id=branch_id,
        )
        # CR Cash
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, cash_ledger,
            debit=0, credit=frieght_paid,
            narration="Cash - Freight paid", branch_id=branch_id,
        )

    # --- 10. Bill reference ---------------------------------------------------
    _insert_bill_ref(
        db, co_id, voucher_id, party_id,
        mr_no or str(mr_id), mr_date, net_total, "PAYABLE",
    )

    # --- 11. Approval log and commit ------------------------------------------
    _insert_approval_log(db, voucher_id, user_id, narration)
    db.commit()

    logger.info(
        "Auto-posted jute bill pass voucher %s (id=%s) for mr %s",
        voucher_no, voucher_id, mr_id,
    )

    return {
        "success": True,
        "voucher_id": voucher_id,
        "voucher_no": voucher_no,
    }


# =============================================================================
# SALES INVOICE
# =============================================================================

def auto_post_sales_invoice(
    db: Session, invoice_id: int, user_id: int
) -> dict:
    """Create SALES voucher when a sales invoice is approved.

    Reads sales_invoice header and detail lines with GST, then creates:
      DR  Sundry Debtors       (invoice total - party ledger)
      CR  Sales A/c            (taxable amounts)
      CR  CGST Output          (from sales_invoice_dtl_gst)
      CR  SGST Output          (from sales_invoice_dtl_gst)
      CR  IGST Output          (from sales_invoice_dtl_gst)
      CR  Round Off            (if positive round off, CR; if negative, DR)
    """
    # --- 1. Duplicate check ---------------------------------------------------
    if _check_duplicate(db, "SALES_INVOICE", invoice_id):
        logger.warning(
            "Duplicate auto-post attempt for sales_invoice %s", invoice_id
        )
        return {"success": False, "error": "Voucher already exists for this sales invoice."}

    # --- 2. Read header -------------------------------------------------------
    hdr = db.execute(
        text("""
            SELECT si.co_id, si.branch_id, si.party_id,
                   si.invoice_no, si.invoice_date,
                   si.net_amount, si.round_off_value
            FROM sales_invoice si
            WHERE si.sales_invoice_id = :iid
        """),
        {"iid": int(invoice_id)},
    ).fetchone()
    if not hdr:
        return {"success": False, "error": f"Sales invoice {invoice_id} not found."}

    h = hdr._mapping
    co_id = h["co_id"]
    branch_id = h["branch_id"]
    party_id = h["party_id"]
    invoice_no = h["invoice_no"]
    invoice_date = h["invoice_date"]
    net_amount = float(h["net_amount"] or 0)
    round_off = float(h["round_off_value"] or 0)

    # --- 3. Read detail lines for taxable amounts -----------------------------
    dtl_rows = db.execute(
        text("""
            SELECT COALESCE(SUM(sid.taxable_amount), 0) AS total_taxable
            FROM sales_invoice_dtl sid
            WHERE sid.sales_invoice_id = :iid
        """),
        {"iid": int(invoice_id)},
    ).fetchone()
    total_taxable = float(dtl_rows._mapping["total_taxable"]) if dtl_rows else 0.0

    # --- 4. Read GST amounts --------------------------------------------------
    gst_row = db.execute(
        text("""
            SELECT COALESCE(SUM(sg.cgst_amount), 0) AS cgst,
                   COALESCE(SUM(sg.sgst_amount), 0) AS sgst,
                   COALESCE(SUM(sg.igst_amount), 0) AS igst
            FROM sales_invoice_dtl_gst sg
            JOIN sales_invoice_dtl sid
                ON sid.sales_invoice_dtl_id = sg.sales_invoice_dtl_id
            WHERE sid.sales_invoice_id = :iid
        """),
        {"iid": int(invoice_id)},
    ).fetchone()
    cgst = float(gst_row._mapping["cgst"]) if gst_row else 0.0
    sgst = float(gst_row._mapping["sgst"]) if gst_row else 0.0
    igst = float(gst_row._mapping["igst"]) if gst_row else 0.0

    # --- 5. FY and voucher type -----------------------------------------------
    fy_type = _get_fy_and_type(db, co_id, invoice_date, "SALES")
    if not fy_type:
        return {
            "success": False,
            "error": "Financial year or SALES voucher type not found.",
        }

    # --- 6. Account determinations --------------------------------------------
    sales_ledger = _get_account(db, co_id, "SALES_INVOICE", "SALES")
    cgst_ledger = _get_account(db, co_id, "SALES_INVOICE", "CGST_OUTPUT")
    sgst_ledger = _get_account(db, co_id, "SALES_INVOICE", "SGST_OUTPUT")
    igst_ledger = _get_account(db, co_id, "SALES_INVOICE", "IGST_OUTPUT")
    roundoff_ledger = _get_account(db, co_id, "SALES_INVOICE", "ROUND_OFF")
    debtor_ledger = _get_party_ledger(db, co_id, party_id)

    if not sales_ledger:
        return {"success": False, "error": "Sales account not configured."}
    if not debtor_ledger:
        return {
            "success": False,
            "error": f"Party ledger not found for party {party_id}.",
        }

    # --- 7. Generate voucher number -------------------------------------------
    voucher_no, voucher_seq = _next_number(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
    )

    # --- 8. Insert voucher header ---------------------------------------------
    narration = f"Auto: Sales Invoice {invoice_no}"
    voucher_id = _insert_voucher_header(
        db, co_id, branch_id,
        fy_type["acc_voucher_type_id"], fy_type["acc_fy_id"],
        voucher_no, voucher_seq, invoice_date,
        narration, "SALES_INVOICE", invoice_id, user_id,
    )

    # --- 9. Insert voucher lines ----------------------------------------------
    line_no = 0

    # DR Sundry Debtors (party)
    line_no += 1
    _insert_voucher_line(
        db, voucher_id, line_no, debtor_ledger,
        debit=net_amount, credit=0,
        narration=f"Debtor - Invoice {invoice_no}",
        party_id=party_id, branch_id=branch_id,
    )

    # CR Sales A/c
    if total_taxable > 0:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, sales_ledger,
            debit=0, credit=total_taxable,
            narration="Sales amount", branch_id=branch_id,
        )

    # CR CGST Output
    if cgst > 0 and cgst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, cgst_ledger,
            debit=0, credit=cgst,
            narration="CGST Output", branch_id=branch_id,
        )

    # CR SGST Output
    if sgst > 0 and sgst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, sgst_ledger,
            debit=0, credit=sgst,
            narration="SGST Output", branch_id=branch_id,
        )

    # CR IGST Output
    if igst > 0 and igst_ledger:
        line_no += 1
        _insert_voucher_line(
            db, voucher_id, line_no, igst_ledger,
            debit=0, credit=igst,
            narration="IGST Output", branch_id=branch_id,
        )

    # DR/CR Round Off (for sales: positive round_off means CR, negative means DR)
    if round_off != 0 and roundoff_ledger:
        line_no += 1
        if round_off > 0:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=0, credit=abs(round_off),
                narration="Round Off", branch_id=branch_id,
            )
        else:
            _insert_voucher_line(
                db, voucher_id, line_no, roundoff_ledger,
                debit=abs(round_off), credit=0,
                narration="Round Off", branch_id=branch_id,
            )

    # --- 10. Bill reference ---------------------------------------------------
    _insert_bill_ref(
        db, co_id, voucher_id, party_id,
        invoice_no, invoice_date, net_amount, "RECEIVABLE",
    )

    # --- 11. Approval log and commit ------------------------------------------
    _insert_approval_log(db, voucher_id, user_id, narration)
    db.commit()

    logger.info(
        "Auto-posted sales invoice voucher %s (id=%s) for invoice %s",
        voucher_no, voucher_id, invoice_id,
    )

    return {
        "success": True,
        "voucher_id": voucher_id,
        "voucher_no": voucher_no,
    }
