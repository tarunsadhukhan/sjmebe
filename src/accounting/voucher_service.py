"""Voucher service — creation, validation, numbering, reversal."""
import logging
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException
from src.common.utils import now_ist

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status IDs (mirrors acc workflow statuses)
# ---------------------------------------------------------------------------
STATUS_DRAFT = 21
STATUS_OPEN = 1
STATUS_PENDING_APPROVAL = 20
STATUS_APPROVED = 3
STATUS_REJECTED = 4
STATUS_CANCELLED = 6

# Voucher type categories that require Bank/Cash ledger
BANK_CASH_REQUIRED_TYPES = {"PAYMENT", "RECEIPT", "CONTRA"}


# =============================================================================
# VALIDATION
# =============================================================================

def validate_voucher(db: Session, co_id: int, voucher_data: dict) -> dict:
    """Pre-save validation that returns warnings and errors.

    Checks:
      1. DR/CR balance
      2. Period lock
      3. Voucher type rules (Payment/Receipt/Contra must have Bank/Cash ledger)
      4. Duplicate check (same party + similar amount + same date)

    Returns dict with keys: valid, warnings, errors.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    lines = voucher_data.get("lines", [])
    voucher_date = voucher_data.get("voucher_date")
    type_category = voucher_data.get("type_category", "").upper()

    # --- 1. DR / CR balance ---------------------------------------------------
    total_dr = sum(float(l.get("debit_amount", 0) or 0) for l in lines)
    total_cr = sum(float(l.get("credit_amount", 0) or 0) for l in lines)
    if round(total_dr, 2) != round(total_cr, 2):
        errors.append({
            "code": "DR_CR_MISMATCH",
            "severity": "error",
            "message": (
                f"Total Debit ({total_dr:.2f}) does not match "
                f"Total Credit ({total_cr:.2f})"
            ),
        })

    # --- 2. Period lock -------------------------------------------------------
    if voucher_date:
        lock_row = db.execute(
            text("""
                SELECT afp.is_locked
                FROM acc_financial_period afp
                JOIN acc_financial_year afy ON afy.acc_fy_id = afp.acc_fy_id
                WHERE afy.co_id = :co_id
                  AND :vdate BETWEEN afp.start_date AND afp.end_date
                LIMIT 1
            """),
            {"co_id": int(co_id), "vdate": voucher_date},
        ).fetchone()
        if lock_row and lock_row._mapping.get("is_locked"):
            errors.append({
                "code": "PERIOD_LOCKED",
                "severity": "error",
                "message": "The accounting period for the voucher date is locked.",
            })

    # --- 3. Voucher type rules ------------------------------------------------
    if type_category in BANK_CASH_REQUIRED_TYPES:
        has_bank_cash = False
        for line in lines:
            ledger_id = line.get("acc_ledger_id")
            if ledger_id:
                row = db.execute(
                    text("""
                        SELECT al.ledger_type
                        FROM acc_ledger al
                        WHERE al.acc_ledger_id = :lid
                    """),
                    {"lid": int(ledger_id)},
                ).fetchone()
                if row and row._mapping.get("ledger_type") in ("B", "C"):
                    has_bank_cash = True
                    break
        if not has_bank_cash:
            errors.append({
                "code": "BANK_CASH_REQUIRED",
                "severity": "error",
                "message": (
                    f"{type_category} voucher must include at least one "
                    "Bank or Cash ledger line."
                ),
            })

    # --- 4. Duplicate check ---------------------------------------------------
    if voucher_date and lines:
        party_ids = [
            l.get("party_id") for l in lines if l.get("party_id")
        ]
        if party_ids:
            dup_row = db.execute(
                text("""
                    SELECT v.acc_voucher_id, v.voucher_no
                    FROM acc_voucher v
                    JOIN acc_voucher_line vl ON vl.acc_voucher_id = v.acc_voucher_id
                    WHERE v.co_id = :co_id
                      AND v.voucher_date = :vdate
                      AND vl.party_id IN :party_ids
                      AND ABS(vl.debit_amount - :amt) < 1
                      AND v.status_id NOT IN (:cancelled)
                    LIMIT 1
                """),
                {
                    "co_id": int(co_id),
                    "vdate": voucher_date,
                    "party_ids": tuple(party_ids),
                    "amt": total_dr,
                    "cancelled": STATUS_CANCELLED,
                },
            ).fetchone()
            if dup_row:
                warnings.append({
                    "code": "POSSIBLE_DUPLICATE",
                    "severity": "warning",
                    "message": (
                        f"A similar voucher ({dup_row._mapping['voucher_no']}) "
                        "already exists for the same party, amount and date."
                    ),
                })

    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
    }


# =============================================================================
# HELPERS
# =============================================================================

def _get_financial_year(db: Session, co_id: int, vdate) -> dict | None:
    """Return the financial year row for a given date."""
    row = db.execute(
        text("""
            SELECT acc_fy_id, fy_start_date, fy_end_date
            FROM acc_financial_year
            WHERE co_id = :co_id
              AND :vdate BETWEEN fy_start_date AND fy_end_date
              AND active = 1
            LIMIT 1
        """),
        {"co_id": int(co_id), "vdate": vdate},
    ).fetchone()
    return dict(row._mapping) if row else None


def _get_voucher_type_id(db: Session, co_id: int, type_category: str) -> int | None:
    """Resolve voucher_type_id from category code."""
    row = db.execute(
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
    return row._mapping["acc_voucher_type_id"] if row else None


def _next_voucher_number(
    db: Session, co_id: int, branch_id: int, voucher_type_id: int, fy_id: int
) -> str:
    """Generate the next voucher number for a type within branch + FY."""
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

    # Fetch prefix from voucher type
    prefix_row = db.execute(
        text("""
            SELECT voucher_prefix
            FROM acc_voucher_type
            WHERE acc_voucher_type_id = :vtid
        """),
        {"vtid": int(voucher_type_id)},
    ).fetchone()
    prefix = prefix_row._mapping["voucher_prefix"] if prefix_row else "V"

    return f"{prefix}{next_seq:05d}"


def _insert_approval_log(
    db: Session,
    voucher_id: int,
    user_id: int,
    from_status: int,
    to_status: int,
    remarks: str | None = None,
):
    """Insert a row into acc_voucher_approval_log."""
    db.execute(
        text("""
            INSERT INTO acc_voucher_approval_log
                (acc_voucher_id, action_by, action_date, from_status_id,
                 to_status_id, remarks)
            VALUES
                (:vid, :uid, :now, :fs, :ts, :rem)
        """),
        {
            "vid": int(voucher_id),
            "uid": int(user_id),
            "now": now_ist(),
            "fs": from_status,
            "ts": to_status,
            "rem": remarks,
        },
    )


def _get_voucher_header(db: Session, voucher_id: int) -> dict:
    """Fetch voucher header or raise 404."""
    row = db.execute(
        text("""
            SELECT * FROM acc_voucher
            WHERE acc_voucher_id = :vid
        """),
        {"vid": int(voucher_id)},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Voucher not found")
    return dict(row._mapping)


# =============================================================================
# CREATE
# =============================================================================

def create_manual_voucher(
    db: Session,
    co_id: int,
    branch_id: int,
    user_id: int,
    voucher_data: dict,
) -> dict:
    """Create a manual (non-auto-posted) voucher.

    Returns dict with voucher_id and voucher_no or validation errors.
    """
    # 1. Validate
    validation = validate_voucher(db, co_id, voucher_data)
    if not validation["valid"]:
        return {"success": False, "errors": validation["errors"],
                "warnings": validation["warnings"]}

    voucher_date = voucher_data["voucher_date"]
    type_category = voucher_data["type_category"]
    narration = voucher_data.get("narration", "")
    lines = voucher_data.get("lines", [])

    # 2. Financial year
    fy = _get_financial_year(db, co_id, voucher_date)
    if not fy:
        raise HTTPException(
            status_code=400,
            detail="No active financial year found for the voucher date.",
        )

    # 3. Voucher type
    voucher_type_id = _get_voucher_type_id(db, co_id, type_category)
    if not voucher_type_id:
        raise HTTPException(
            status_code=400,
            detail=f"Voucher type '{type_category}' not found for this company.",
        )

    # 4. Next voucher number
    voucher_no = _next_voucher_number(
        db, co_id, branch_id, voucher_type_id, fy["acc_fy_id"]
    )

    # 5. Insert header
    result = db.execute(
        text("""
            INSERT INTO acc_voucher
                (co_id, branch_id, acc_voucher_type_id, acc_fy_id,
                 voucher_no, voucher_seq, voucher_date, narration,
                 status_id, is_auto_posted, is_reversed,
                 created_by, created_date_time)
            VALUES
                (:co_id, :branch_id, :vtid, :fy_id,
                 :vno, :vseq, :vdate, :narration,
                 :status, 0, 0,
                 :uid, :now)
        """),
        {
            "co_id": int(co_id),
            "branch_id": int(branch_id),
            "vtid": int(voucher_type_id),
            "fy_id": int(fy["acc_fy_id"]),
            "vno": voucher_no,
            "vseq": int(voucher_no.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or 0),
            "vdate": voucher_date,
            "narration": narration,
            "status": STATUS_DRAFT,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )
    voucher_id = result.lastrowid

    # 6. Insert lines
    for idx, line in enumerate(lines, start=1):
        db.execute(
            text("""
                INSERT INTO acc_voucher_line
                    (acc_voucher_id, line_no, acc_ledger_id, party_id,
                     debit_amount, credit_amount, narration,
                     cost_center_id, branch_id)
                VALUES
                    (:vid, :lno, :lid, :pid,
                     :dr, :cr, :narr,
                     :ccid, :bid)
            """),
            {
                "vid": int(voucher_id),
                "lno": idx,
                "lid": int(line["acc_ledger_id"]),
                "pid": int(line["party_id"]) if line.get("party_id") else None,
                "dr": float(line.get("debit_amount", 0) or 0),
                "cr": float(line.get("credit_amount", 0) or 0),
                "narr": line.get("narration", ""),
                "ccid": (
                    int(line["cost_center_id"])
                    if line.get("cost_center_id") else None
                ),
                "bid": (
                    int(line["branch_id"])
                    if line.get("branch_id") else int(branch_id)
                ),
            },
        )

    # 7. GST lines (optional)
    gst_lines = voucher_data.get("gst_lines", [])
    for gst in gst_lines:
        db.execute(
            text("""
                INSERT INTO acc_voucher_gst
                    (acc_voucher_id, acc_ledger_id, hsn_code,
                     taxable_amount, cgst_rate, cgst_amount,
                     sgst_rate, sgst_amount, igst_rate, igst_amount,
                     cess_rate, cess_amount)
                VALUES
                    (:vid, :lid, :hsn,
                     :taxable, :cgst_r, :cgst_a,
                     :sgst_r, :sgst_a, :igst_r, :igst_a,
                     :cess_r, :cess_a)
            """),
            {
                "vid": int(voucher_id),
                "lid": int(gst["acc_ledger_id"]),
                "hsn": gst.get("hsn_code", ""),
                "taxable": float(gst.get("taxable_amount", 0)),
                "cgst_r": float(gst.get("cgst_rate", 0)),
                "cgst_a": float(gst.get("cgst_amount", 0)),
                "sgst_r": float(gst.get("sgst_rate", 0)),
                "sgst_a": float(gst.get("sgst_amount", 0)),
                "igst_r": float(gst.get("igst_rate", 0)),
                "igst_a": float(gst.get("igst_amount", 0)),
                "cess_r": float(gst.get("cess_rate", 0)),
                "cess_a": float(gst.get("cess_amount", 0)),
            },
        )

    db.commit()

    _insert_approval_log(db, voucher_id, user_id, 0, STATUS_DRAFT, "Created")
    db.commit()

    logger.info(
        "Voucher %s (id=%s) created by user %s", voucher_no, voucher_id, user_id
    )

    return {
        "success": True,
        "voucher_id": voucher_id,
        "voucher_no": voucher_no,
        "warnings": validation["warnings"],
    }


# =============================================================================
# UPDATE DRAFT
# =============================================================================

def update_draft_voucher(
    db: Session, voucher_id: int, user_id: int, voucher_data: dict
) -> dict:
    """Update a draft (status_id = 21) voucher. Only drafts can be edited."""
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_DRAFT:
        raise HTTPException(
            status_code=400,
            detail="Only draft vouchers can be edited.",
        )

    lines = voucher_data.get("lines", [])
    narration = voucher_data.get("narration", header.get("narration", ""))
    voucher_date = voucher_data.get("voucher_date", header.get("voucher_date"))

    # Delete old lines and GST
    db.execute(
        text("DELETE FROM acc_voucher_gst WHERE acc_voucher_id = :vid"),
        {"vid": int(voucher_id)},
    )
    db.execute(
        text("DELETE FROM acc_voucher_line WHERE acc_voucher_id = :vid"),
        {"vid": int(voucher_id)},
    )

    # Update header
    db.execute(
        text("""
            UPDATE acc_voucher
            SET voucher_date = :vdate,
                narration    = :narration,
                updated_by   = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "vdate": voucher_date,
            "narration": narration,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    # Re-insert lines
    branch_id = header["branch_id"]
    for idx, line in enumerate(lines, start=1):
        db.execute(
            text("""
                INSERT INTO acc_voucher_line
                    (acc_voucher_id, line_no, acc_ledger_id, party_id,
                     debit_amount, credit_amount, narration,
                     cost_center_id, branch_id)
                VALUES
                    (:vid, :lno, :lid, :pid,
                     :dr, :cr, :narr,
                     :ccid, :bid)
            """),
            {
                "vid": int(voucher_id),
                "lno": idx,
                "lid": int(line["acc_ledger_id"]),
                "pid": int(line["party_id"]) if line.get("party_id") else None,
                "dr": float(line.get("debit_amount", 0) or 0),
                "cr": float(line.get("credit_amount", 0) or 0),
                "narr": line.get("narration", ""),
                "ccid": (
                    int(line["cost_center_id"])
                    if line.get("cost_center_id") else None
                ),
                "bid": (
                    int(line["branch_id"])
                    if line.get("branch_id") else int(branch_id)
                ),
            },
        )

    # Re-insert GST
    for gst in voucher_data.get("gst_lines", []):
        db.execute(
            text("""
                INSERT INTO acc_voucher_gst
                    (acc_voucher_id, acc_ledger_id, hsn_code,
                     taxable_amount, cgst_rate, cgst_amount,
                     sgst_rate, sgst_amount, igst_rate, igst_amount,
                     cess_rate, cess_amount)
                VALUES
                    (:vid, :lid, :hsn,
                     :taxable, :cgst_r, :cgst_a,
                     :sgst_r, :sgst_a, :igst_r, :igst_a,
                     :cess_r, :cess_a)
            """),
            {
                "vid": int(voucher_id),
                "lid": int(gst["acc_ledger_id"]),
                "hsn": gst.get("hsn_code", ""),
                "taxable": float(gst.get("taxable_amount", 0)),
                "cgst_r": float(gst.get("cgst_rate", 0)),
                "cgst_a": float(gst.get("cgst_amount", 0)),
                "sgst_r": float(gst.get("sgst_rate", 0)),
                "sgst_a": float(gst.get("sgst_amount", 0)),
                "igst_r": float(gst.get("igst_rate", 0)),
                "igst_a": float(gst.get("igst_amount", 0)),
                "cess_r": float(gst.get("cess_rate", 0)),
                "cess_a": float(gst.get("cess_amount", 0)),
            },
        )

    db.commit()
    logger.info("Draft voucher %s updated by user %s", voucher_id, user_id)

    return {"success": True, "voucher_id": voucher_id}


# =============================================================================
# REVERSAL
# =============================================================================

def reverse_voucher(
    db: Session, voucher_id: int, user_id: int, narration: str | None = None
) -> dict:
    """Create a reversal voucher for an approved voucher.

    Swaps DR/CR on every line. Marks original as reversed.
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_APPROVED:
        raise HTTPException(
            status_code=400, detail="Only approved vouchers can be reversed."
        )
    if header.get("is_reversed"):
        raise HTTPException(
            status_code=400, detail="This voucher has already been reversed."
        )

    # Load original lines
    orig_lines = db.execute(
        text("""
            SELECT * FROM acc_voucher_line
            WHERE acc_voucher_id = :vid
            ORDER BY line_no
        """),
        {"vid": int(voucher_id)},
    ).fetchall()

    if not orig_lines:
        raise HTTPException(
            status_code=400, detail="Original voucher has no lines."
        )

    # New voucher number
    rev_no = _next_voucher_number(
        db,
        header["co_id"],
        header["branch_id"],
        header["acc_voucher_type_id"],
        header["acc_fy_id"],
    )

    rev_narration = narration or f"Reversal of {header['voucher_no']}"

    # Insert reversal header
    result = db.execute(
        text("""
            INSERT INTO acc_voucher
                (co_id, branch_id, acc_voucher_type_id, acc_fy_id,
                 voucher_no, voucher_seq, voucher_date, narration,
                 status_id, is_auto_posted, is_reversed,
                 reversal_of_voucher_id,
                 created_by, created_date_time)
            VALUES
                (:co_id, :branch_id, :vtid, :fy_id,
                 :vno, :vseq, :vdate, :narration,
                 :status, 0, 0,
                 :rev_of,
                 :uid, :now)
        """),
        {
            "co_id": int(header["co_id"]),
            "branch_id": int(header["branch_id"]),
            "vtid": int(header["acc_voucher_type_id"]),
            "fy_id": int(header["acc_fy_id"]),
            "vno": rev_no,
            "vseq": int(rev_no.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or 0),
            "vdate": header["voucher_date"],
            "narration": rev_narration,
            "status": STATUS_APPROVED,
            "rev_of": int(voucher_id),
            "uid": int(user_id),
            "now": now_ist(),
        },
    )
    rev_voucher_id = result.lastrowid

    # Insert reversed lines (swap DR / CR)
    for idx, line in enumerate(orig_lines, start=1):
        m = line._mapping
        db.execute(
            text("""
                INSERT INTO acc_voucher_line
                    (acc_voucher_id, line_no, acc_ledger_id, party_id,
                     debit_amount, credit_amount, narration,
                     cost_center_id, branch_id)
                VALUES
                    (:vid, :lno, :lid, :pid,
                     :dr, :cr, :narr,
                     :ccid, :bid)
            """),
            {
                "vid": int(rev_voucher_id),
                "lno": idx,
                "lid": int(m["acc_ledger_id"]),
                "pid": int(m["party_id"]) if m.get("party_id") else None,
                "dr": float(m.get("credit_amount", 0) or 0),
                "cr": float(m.get("debit_amount", 0) or 0),
                "narr": m.get("narration", ""),
                "ccid": (
                    int(m["cost_center_id"]) if m.get("cost_center_id") else None
                ),
                "bid": int(m["branch_id"]) if m.get("branch_id") else None,
            },
        )

    # Mark original as reversed
    db.execute(
        text("""
            UPDATE acc_voucher
            SET is_reversed = 1,
                reversed_by_voucher_id = :rev_id,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "rev_id": int(rev_voucher_id),
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(
        db, rev_voucher_id, user_id, 0, STATUS_APPROVED, rev_narration
    )
    db.commit()

    logger.info(
        "Voucher %s reversed by %s → new voucher %s",
        voucher_id, user_id, rev_voucher_id,
    )

    return {
        "success": True,
        "reversal_voucher_id": rev_voucher_id,
        "reversal_voucher_no": rev_no,
    }


# =============================================================================
# BILL SETTLEMENT
# =============================================================================

def settle_bills(
    db: Session, voucher_id: int, user_id: int, settlements: list[dict]
) -> dict:
    """Link a payment/receipt voucher to outstanding bills.

    settlements: [{"acc_bill_ref_id": 1, "amount": 5000}, ...]
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_APPROVED:
        raise HTTPException(
            status_code=400,
            detail="Only approved vouchers can be used for bill settlement.",
        )

    # Verify voucher type is Payment or Receipt
    vtype_row = db.execute(
        text("""
            SELECT type_category FROM acc_voucher_type
            WHERE acc_voucher_type_id = :vtid
        """),
        {"vtid": int(header["acc_voucher_type_id"])},
    ).fetchone()
    if not vtype_row or vtype_row._mapping["type_category"].upper() not in (
        "PAYMENT", "RECEIPT"
    ):
        raise HTTPException(
            status_code=400,
            detail="Bill settlement is only allowed for Payment/Receipt vouchers.",
        )

    settled_count = 0
    for s in settlements:
        bill_ref_id = int(s["acc_bill_ref_id"])
        amount = float(s["amount"])

        # Fetch current bill
        bill = db.execute(
            text("""
                SELECT acc_bill_ref_id, total_amount, pending_amount, status
                FROM acc_bill_ref
                WHERE acc_bill_ref_id = :bid
            """),
            {"bid": bill_ref_id},
        ).fetchone()
        if not bill:
            raise HTTPException(
                status_code=404,
                detail=f"Bill reference {bill_ref_id} not found.",
            )

        bm = bill._mapping
        if amount > float(bm["pending_amount"] or 0):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Settlement amount ({amount}) exceeds pending amount "
                    f"({bm['pending_amount']}) for bill {bill_ref_id}."
                ),
            )

        # Insert settlement record
        db.execute(
            text("""
                INSERT INTO acc_bill_settlement
                    (acc_bill_ref_id, acc_voucher_id, settled_amount,
                     settled_by, settled_date)
                VALUES
                    (:bid, :vid, :amt, :uid, :now)
            """),
            {
                "bid": bill_ref_id,
                "vid": int(voucher_id),
                "amt": amount,
                "uid": int(user_id),
                "now": now_ist(),
            },
        )

        # Update pending amount and status
        new_pending = float(bm["pending_amount"] or 0) - amount
        new_status = "CLOSED" if new_pending <= 0 else "PARTIAL"

        db.execute(
            text("""
                UPDATE acc_bill_ref
                SET pending_amount = :pending,
                    status = :status
                WHERE acc_bill_ref_id = :bid
            """),
            {
                "bid": bill_ref_id,
                "pending": round(new_pending, 2),
                "status": new_status,
            },
        )
        settled_count += 1

    db.commit()
    logger.info(
        "Settled %d bills against voucher %s by user %s",
        settled_count, voucher_id, user_id,
    )

    return {"success": True, "settled_count": settled_count}


# =============================================================================
# STATUS TRANSITIONS
# =============================================================================

def open_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Move voucher from Draft (21) to Open (1).

    Generate voucher number if not yet assigned.
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft vouchers can be opened."
        )

    # Assign voucher number if missing
    voucher_no = header.get("voucher_no")
    if not voucher_no:
        voucher_no = _next_voucher_number(
            db,
            header["co_id"],
            header["branch_id"],
            header["acc_voucher_type_id"],
            header["acc_fy_id"],
        )
        db.execute(
            text("""
                UPDATE acc_voucher
                SET voucher_no = :vno,
                    voucher_seq = :vseq
                WHERE acc_voucher_id = :vid
            """),
            {
                "vid": int(voucher_id),
                "vno": voucher_no,
                "vseq": int(
                    voucher_no.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") or 0
                ),
            },
        )

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": STATUS_OPEN,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(db, voucher_id, user_id, STATUS_DRAFT, STATUS_OPEN)
    db.commit()

    logger.info("Voucher %s opened by user %s", voucher_id, user_id)
    return {"success": True, "voucher_id": voucher_id, "voucher_no": voucher_no}


def cancel_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Cancel a draft voucher (21 -> 6)."""
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_DRAFT:
        raise HTTPException(
            status_code=400, detail="Only draft vouchers can be cancelled."
        )

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": STATUS_CANCELLED,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(db, voucher_id, user_id, STATUS_DRAFT, STATUS_CANCELLED)
    db.commit()

    logger.info("Voucher %s cancelled by user %s", voucher_id, user_id)
    return {"success": True, "voucher_id": voucher_id}


def send_for_approval(db: Session, voucher_id: int, user_id: int) -> dict:
    """Send open voucher for approval (1 -> 20, level 1)."""
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_OPEN:
        raise HTTPException(
            status_code=400,
            detail="Only open vouchers can be sent for approval.",
        )

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                approval_level = 1,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": STATUS_PENDING_APPROVAL,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(
        db, voucher_id, user_id, STATUS_OPEN, STATUS_PENDING_APPROVAL,
        "Sent for approval (level 1)",
    )
    db.commit()

    logger.info("Voucher %s sent for approval by user %s", voucher_id, user_id)
    return {"success": True, "voucher_id": voucher_id, "approval_level": 1}


def approve_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Approve voucher.

    If final approval level -> status 3 (Approved).
    Otherwise increment approval_level (stay at 20).
    """
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only vouchers pending approval can be approved.",
        )

    current_level = header.get("approval_level", 1) or 1

    # Get max approval level for this voucher type + branch
    max_row = db.execute(
        text("""
            SELECT COALESCE(MAX(approval_level), 1) AS max_level
            FROM acc_approval_mst
            WHERE co_id = :co_id
              AND acc_voucher_type_id = :vtid
              AND branch_id = :bid
              AND active = 1
        """),
        {
            "co_id": int(header["co_id"]),
            "vtid": int(header["acc_voucher_type_id"]),
            "bid": int(header["branch_id"]),
        },
    ).fetchone()
    max_level = max_row._mapping["max_level"] if max_row else 1

    if current_level >= max_level:
        # Final approval
        new_status = STATUS_APPROVED
        new_level = current_level
        remarks = f"Final approval (level {current_level})"
    else:
        # Increment level
        new_status = STATUS_PENDING_APPROVAL
        new_level = current_level + 1
        remarks = f"Approved at level {current_level}, moved to level {new_level}"

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                approval_level = :level,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": new_status,
            "level": new_level,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(
        db, voucher_id, user_id, STATUS_PENDING_APPROVAL, new_status, remarks
    )
    db.commit()

    logger.info(
        "Voucher %s approved (level %s->%s, status %s) by user %s",
        voucher_id, current_level, new_level, new_status, user_id,
    )
    return {
        "success": True,
        "voucher_id": voucher_id,
        "status_id": new_status,
        "approval_level": new_level,
    }


def reject_voucher(
    db: Session, voucher_id: int, user_id: int, reason: str
) -> dict:
    """Reject voucher (20 -> 4) with reason."""
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] != STATUS_PENDING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail="Only vouchers pending approval can be rejected.",
        )

    if not reason or not reason.strip():
        raise HTTPException(
            status_code=400, detail="Rejection reason is required."
        )

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": STATUS_REJECTED,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(
        db, voucher_id, user_id, STATUS_PENDING_APPROVAL, STATUS_REJECTED,
        reason.strip(),
    )
    db.commit()

    logger.info("Voucher %s rejected by user %s: %s", voucher_id, user_id, reason)
    return {"success": True, "voucher_id": voucher_id}


def reopen_voucher(db: Session, voucher_id: int, user_id: int) -> dict:
    """Reopen a cancelled or rejected voucher (6/4 -> 1)."""
    header = _get_voucher_header(db, voucher_id)

    if header["status_id"] not in (STATUS_CANCELLED, STATUS_REJECTED):
        raise HTTPException(
            status_code=400,
            detail="Only cancelled or rejected vouchers can be reopened.",
        )

    old_status = header["status_id"]

    db.execute(
        text("""
            UPDATE acc_voucher
            SET status_id = :status,
                approval_level = NULL,
                updated_by = :uid,
                updated_date_time = :now
            WHERE acc_voucher_id = :vid
        """),
        {
            "vid": int(voucher_id),
            "status": STATUS_OPEN,
            "uid": int(user_id),
            "now": now_ist(),
        },
    )

    _insert_approval_log(db, voucher_id, user_id, old_status, STATUS_OPEN, "Reopened")
    db.commit()

    logger.info("Voucher %s reopened by user %s", voucher_id, user_id)
    return {"success": True, "voucher_id": voucher_id}
