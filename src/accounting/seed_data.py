"""
Accounting module seed data — creates default chart of accounts, voucher types,
and supporting configuration when accounting is activated for a company.
"""

from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.accounting.constants import (
    VOUCHER_CATEGORIES,
    LEDGER_TYPES,
    ACCOUNT_NATURE,
    SOURCE_DOC_TYPES,
    LINE_TYPES,
)


# =============================================================================
# LEDGER GROUP DEFINITIONS
# =============================================================================

# Each tuple: (group_name, parent_name_or_None, nature, is_revenue, normal_balance, is_party_group)
# nature: A=Asset, L=Liability, I=Income, E=Expense
# is_revenue: 0=BS, 1=PL
# normal_balance: D=Debit, C=Credit
# is_party_group: 0=No, 1=Yes

# ROOT groups (no parent) inserted first
_ROOT_GROUPS = [
    ("Capital Account",        None, "L", 0, "C", 0),
    ("Loans (Liability)",      None, "L", 0, "C", 0),
    ("Current Liabilities",    None, "L", 0, "C", 0),
    ("Fixed Assets",           None, "A", 0, "D", 0),
    ("Investments",            None, "A", 0, "D", 0),
    ("Current Assets",         None, "A", 0, "D", 0),
    ("Misc. Expenses (Asset)", None, "A", 0, "D", 0),
    ("Sales Accounts",         None, "I", 1, "C", 0),
    ("Purchase Accounts",      None, "E", 1, "D", 0),
    ("Direct Expenses",        None, "E", 1, "D", 0),
    ("Direct Incomes",         None, "I", 1, "C", 0),
    ("Indirect Expenses",      None, "E", 1, "D", 0),
    ("Indirect Incomes",       None, "I", 1, "C", 0),
    ("Branch / Divisions",     None, "A", 0, "D", 0),
    ("Suspense Account",       None, "A", 0, "D", 0),
]

# CHILD groups (have a parent)
_CHILD_GROUPS = [
    ("Reserves & Surplus",          "Capital Account",     "L", 0, "C", 0),
    ("Bank OD Accounts",            "Loans (Liability)",   "L", 0, "C", 0),
    ("Secured Loans",               "Loans (Liability)",   "L", 0, "C", 0),
    ("Unsecured Loans",             "Loans (Liability)",   "L", 0, "C", 0),
    ("Duties & Taxes",              "Current Liabilities", "L", 0, "C", 0),
    ("Provisions",                  "Current Liabilities", "L", 0, "C", 0),
    ("Sundry Creditors",            "Current Liabilities", "L", 0, "C", 1),
    ("Bank Accounts",               "Current Assets",      "A", 0, "D", 0),
    ("Cash-in-Hand",                "Current Assets",      "A", 0, "D", 0),
    ("Deposits (Asset)",            "Current Assets",      "A", 0, "D", 0),
    ("Loans & Advances (Asset)",    "Current Assets",      "A", 0, "D", 0),
    ("Stock-in-Hand",               "Current Assets",      "A", 0, "D", 0),
    ("Sundry Debtors",              "Current Assets",      "A", 0, "D", 1),
]


# =============================================================================
# SYSTEM LEDGER DEFINITIONS
# =============================================================================

# Each tuple: (ledger_name, group_name, ledger_type, is_system_ledger)
_SYSTEM_LEDGERS = [
    ("Cash",                  "Cash-in-Hand",         LEDGER_TYPES["CASH"],    1),
    ("CGST Input",            "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("SGST Input",            "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("IGST Input",            "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("CGST Output",           "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("SGST Output",           "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("IGST Output",           "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("TDS Payable",           "Duties & Taxes",       LEDGER_TYPES["GENERAL"], 1),
    ("Purchase Account",      "Purchase Accounts",    LEDGER_TYPES["GENERAL"], 1),
    ("Jute Purchase Account", "Purchase Accounts",    LEDGER_TYPES["GENERAL"], 1),
    ("Purchase Returns",      "Purchase Accounts",    LEDGER_TYPES["GENERAL"], 1),
    ("Sales Account",         "Sales Accounts",       LEDGER_TYPES["GENERAL"], 1),
    ("Freight Inward",        "Direct Expenses",      LEDGER_TYPES["GENERAL"], 1),
    ("Round Off",             "Indirect Expenses",    LEDGER_TYPES["GENERAL"], 1),
    ("Claims Receivable",     "Current Assets",       LEDGER_TYPES["GENERAL"], 1),
    ("Opening Stock",         "Stock-in-Hand",        LEDGER_TYPES["GENERAL"], 1),
    ("Closing Stock",         "Stock-in-Hand",        LEDGER_TYPES["GENERAL"], 1),
    ("Profit & Loss A/c",     "Misc. Expenses (Asset)", LEDGER_TYPES["GENERAL"], 1),
]


def seed_ledger_groups(db: Session, co_id: int, user_id: int) -> dict:
    """
    Insert 28 predefined ledger groups with correct parent hierarchy.

    Returns dict mapping group_name -> acc_ledger_group_id.
    """
    group_map = {}

    # Check if groups already exist for this company
    existing = db.execute(
        text("SELECT group_name, acc_ledger_group_id FROM acc_ledger_group WHERE co_id = :co_id AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()

    if existing:
        for row in existing:
            r = row._mapping
            group_map[r["group_name"]] = r["acc_ledger_group_id"]
        return group_map

    now = datetime.now()

    # Phase 1: Insert ROOT groups (parent_group_id = NULL)
    for seq, (name, _parent, nature, is_revenue, normal_balance, is_party) in enumerate(_ROOT_GROUPS, start=1):
        db.execute(
            text("""
                INSERT INTO acc_ledger_group
                    (co_id, parent_group_id, group_name, nature, is_revenue, normal_balance,
                     is_party_group, is_system_group, sequence_no, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, NULL, :group_name, :nature, :is_revenue, :normal_balance,
                     :is_party_group, 1, :sequence_no, 1, :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "group_name": name,
                "nature": nature,
                "is_revenue": is_revenue,
                "normal_balance": normal_balance,
                "is_party_group": is_party,
                "sequence_no": seq,
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )

    db.flush()

    # Fetch ROOT group IDs
    root_rows = db.execute(
        text("SELECT group_name, acc_ledger_group_id FROM acc_ledger_group WHERE co_id = :co_id AND parent_group_id IS NULL AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()
    for row in root_rows:
        r = row._mapping
        group_map[r["group_name"]] = r["acc_ledger_group_id"]

    # Phase 2: Insert CHILD groups
    for seq, (name, parent_name, nature, is_revenue, normal_balance, is_party) in enumerate(_CHILD_GROUPS, start=len(_ROOT_GROUPS) + 1):
        parent_id = group_map.get(parent_name)
        db.execute(
            text("""
                INSERT INTO acc_ledger_group
                    (co_id, parent_group_id, group_name, nature, is_revenue, normal_balance,
                     is_party_group, is_system_group, sequence_no, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, :parent_group_id, :group_name, :nature, :is_revenue, :normal_balance,
                     :is_party_group, 1, :sequence_no, 1, :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "parent_group_id": int(parent_id) if parent_id else None,
                "group_name": name,
                "nature": nature,
                "is_revenue": is_revenue,
                "normal_balance": normal_balance,
                "is_party_group": is_party,
                "sequence_no": seq,
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )

    db.flush()

    # Fetch all group IDs (root + child)
    all_rows = db.execute(
        text("SELECT group_name, acc_ledger_group_id FROM acc_ledger_group WHERE co_id = :co_id AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()
    group_map = {}
    for row in all_rows:
        r = row._mapping
        group_map[r["group_name"]] = r["acc_ledger_group_id"]

    return group_map


def seed_system_ledgers(db: Session, co_id: int, user_id: int, group_map: dict) -> int:
    """
    Create system ledgers (Cash, GST, TDS, Purchase, Sales, etc.).

    Args:
        group_map: dict of group_name -> group_id returned from seed_ledger_groups.

    Returns count of ledgers created.
    """
    # Check if system ledgers already exist
    existing_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM acc_ledger WHERE co_id = :co_id AND is_system_ledger = 1 AND active = 1"),
        {"co_id": int(co_id)},
    ).scalar()

    if existing_count and existing_count > 0:
        return 0

    now = datetime.now()
    created = 0

    for ledger_name, group_name, ledger_type, is_system in _SYSTEM_LEDGERS:
        group_id = group_map.get(group_name)
        if group_id is None:
            continue

        db.execute(
            text("""
                INSERT INTO acc_ledger
                    (co_id, acc_ledger_group_id, ledger_name, ledger_type,
                     is_system_ledger, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, :acc_ledger_group_id, :ledger_name, :ledger_type,
                     :is_system_ledger, 1, :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "acc_ledger_group_id": int(group_id),
                "ledger_name": ledger_name,
                "ledger_type": ledger_type,
                "is_system_ledger": is_system,
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        created += 1

    db.flush()
    return created


def seed_voucher_types(db: Session, co_id: int, user_id: int) -> int:
    """
    Insert 8 predefined voucher types (Payment, Receipt, Journal, Contra,
    Sales, Purchase, Debit Note, Credit Note).

    Returns count of voucher types created.
    """
    # Check if voucher types already exist
    existing_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM acc_voucher_type WHERE co_id = :co_id AND active = 1"),
        {"co_id": int(co_id)},
    ).scalar()

    if existing_count and existing_count > 0:
        return 0

    now = datetime.now()
    created = 0

    # Human-friendly display names
    _TYPE_NAMES = {
        "PAYMENT": "Payment",
        "RECEIPT": "Receipt",
        "JOURNAL": "Journal",
        "CONTRA": "Contra",
        "SALES": "Sales",
        "PURCHASE": "Purchase",
        "DEBIT_NOTE": "Debit Note",
        "CREDIT_NOTE": "Credit Note",
    }

    for category_key, cat_info in VOUCHER_CATEGORIES.items():
        display_name = _TYPE_NAMES.get(category_key, category_key)
        db.execute(
            text("""
                INSERT INTO acc_voucher_type
                    (co_id, type_name, type_code, type_category, auto_numbering,
                     prefix, requires_bank_cash, is_system_type, active,
                     updated_by, updated_date_time)
                VALUES
                    (:co_id, :type_name, :type_code, :type_category, 1,
                     :prefix, :requires_bank_cash, 1, 1,
                     :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "type_name": display_name,
                "type_code": cat_info["code"],
                "type_category": category_key,
                "prefix": cat_info["code"],
                "requires_bank_cash": 1 if cat_info["requires_bank_cash"] else 0,
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        created += 1

    db.flush()
    return created


def seed_party_ledgers(db: Session, co_id: int, user_id: int, group_map: dict) -> int:
    """
    Auto-create party ledgers for all active parties in party_mst.

    Determines Sundry Creditors vs Sundry Debtors based on party_type_id:
      - party_type_id = 1 (Supplier/Vendor) -> Sundry Creditors
      - party_type_id = 2 (Customer)        -> Sundry Debtors
      - Other                               -> Sundry Creditors (default)

    Returns count of party ledgers created.
    """
    creditors_group_id = group_map.get("Sundry Creditors")
    debtors_group_id = group_map.get("Sundry Debtors")

    if not creditors_group_id or not debtors_group_id:
        return 0

    # Get already-linked party IDs to avoid duplicates
    existing_party_ids = db.execute(
        text("SELECT party_id FROM acc_ledger WHERE co_id = :co_id AND party_id IS NOT NULL AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()
    existing_set = {row._mapping["party_id"] for row in existing_party_ids}

    # Fetch active parties
    parties = db.execute(
        text("""
            SELECT party_id, party_name, party_type_id
            FROM party_mst
            WHERE co_id = :co_id AND active = 1
        """),
        {"co_id": int(co_id)},
    ).fetchall()

    now = datetime.now()
    created = 0

    for party_row in parties:
        p = party_row._mapping
        party_id = p["party_id"]

        if party_id in existing_set:
            continue

        # Determine group: customer -> Debtors, else -> Creditors
        party_type_id = p.get("party_type_id")
        if party_type_id == 2:
            group_id = debtors_group_id
        else:
            group_id = creditors_group_id

        party_name = p.get("party_name", f"Party {party_id}")

        db.execute(
            text("""
                INSERT INTO acc_ledger
                    (co_id, acc_ledger_group_id, ledger_name, ledger_type, party_id,
                     is_system_ledger, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, :acc_ledger_group_id, :ledger_name, :ledger_type, :party_id,
                     0, 1, :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "acc_ledger_group_id": int(group_id),
                "ledger_name": party_name,
                "ledger_type": LEDGER_TYPES["PARTY"],
                "party_id": int(party_id),
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        created += 1

    if created > 0:
        db.flush()

    return created


def seed_account_determinations(db: Session, co_id: int, user_id: int) -> int:
    """
    Insert default account determination rules for PURCHASE, JUTE_PURCHASE,
    and SALES document types.

    Maps line types to the corresponding system ledger for auto-posting.

    Returns count of rules created.
    """
    # Check if rules already exist
    existing_count = db.execute(
        text("SELECT COUNT(*) AS cnt FROM acc_account_determination WHERE co_id = :co_id AND active = 1"),
        {"co_id": int(co_id)},
    ).scalar()

    if existing_count and existing_count > 0:
        return 0

    # Build ledger lookup: ledger_name -> acc_ledger_id (system ledgers only)
    ledger_rows = db.execute(
        text("SELECT acc_ledger_id, ledger_name FROM acc_ledger WHERE co_id = :co_id AND is_system_ledger = 1 AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()
    ledger_lookup = {row._mapping["ledger_name"]: row._mapping["acc_ledger_id"] for row in ledger_rows}

    # Default determination rules: (doc_type, line_type, ledger_name)
    _RULES = [
        # Procurement bill-pass
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["MATERIAL"],    "Purchase Account"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["CGST_INPUT"],  "CGST Input"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["SGST_INPUT"],  "SGST Input"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["IGST_INPUT"],  "IGST Input"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["TDS"],         "TDS Payable"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["FREIGHT"],     "Freight Inward"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["ROUND_OFF"],   "Round Off"),
        (SOURCE_DOC_TYPES["PROC_BILLPASS"], LINE_TYPES["CLAIMS"],      "Claims Receivable"),
        # Jute bill-pass
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["MATERIAL"],    "Jute Purchase Account"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["CGST_INPUT"],  "CGST Input"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["SGST_INPUT"],  "SGST Input"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["IGST_INPUT"],  "IGST Input"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["TDS"],         "TDS Payable"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["FREIGHT"],     "Freight Inward"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["ROUND_OFF"],   "Round Off"),
        (SOURCE_DOC_TYPES["JUTE_BILLPASS"], LINE_TYPES["CLAIMS"],      "Claims Receivable"),
        # Sales invoice
        (SOURCE_DOC_TYPES["SALES_INVOICE"], LINE_TYPES["REVENUE"],     "Sales Account"),
        (SOURCE_DOC_TYPES["SALES_INVOICE"], LINE_TYPES["CGST_OUTPUT"], "CGST Output"),
        (SOURCE_DOC_TYPES["SALES_INVOICE"], LINE_TYPES["SGST_OUTPUT"], "SGST Output"),
        (SOURCE_DOC_TYPES["SALES_INVOICE"], LINE_TYPES["IGST_OUTPUT"], "IGST Output"),
        (SOURCE_DOC_TYPES["SALES_INVOICE"], LINE_TYPES["ROUND_OFF"],   "Round Off"),
    ]

    now = datetime.now()
    created = 0

    for doc_type, line_type, ledger_name in _RULES:
        ledger_id = ledger_lookup.get(ledger_name)
        if ledger_id is None:
            continue

        db.execute(
            text("""
                INSERT INTO acc_account_determination
                    (co_id, doc_type, line_type, acc_ledger_id, is_default, active,
                     updated_by, updated_date_time)
                VALUES
                    (:co_id, :doc_type, :line_type, :acc_ledger_id, 1, 1,
                     :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "doc_type": doc_type,
                "line_type": line_type,
                "acc_ledger_id": int(ledger_id),
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        created += 1

    if created > 0:
        db.flush()

    return created


def seed_ageing_slabs(db: Session, co_id: int, user_id: int) -> int:
    """
    Placeholder for Phase 2 — ageing slabs for receivable/payable analysis.

    Will insert default slabs: 0-30, 31-60, 61-90, 91-120, 120+ days.
    Table: acc_ageing_slab (to be created in Phase 2).
    """
    # Phase 2: implement when acc_ageing_slab table is available
    return 0


def seed_financial_year(db: Session, co_id: int, user_id: int) -> dict:
    """
    Create the current financial year (April 1 to March 31) and 12 period locks.

    Returns dict with fy_id and period_count.
    """
    today = date.today()

    # Determine FY boundaries (Indian FY: April to March)
    if today.month >= 4:
        fy_start = date(today.year, 4, 1)
        fy_end = date(today.year + 1, 3, 31)
        fy_label = f"{today.year}-{str(today.year + 1)[-2:]}"
    else:
        fy_start = date(today.year - 1, 4, 1)
        fy_end = date(today.year, 3, 31)
        fy_label = f"{today.year - 1}-{str(today.year)[-2:]}"

    # Check if FY already exists
    existing_fy = db.execute(
        text("""
            SELECT acc_financial_year_id FROM acc_financial_year
            WHERE co_id = :co_id AND fy_start = :fy_start AND fy_end = :fy_end AND is_active = 1
        """),
        {"co_id": int(co_id), "fy_start": fy_start, "fy_end": fy_end},
    ).fetchone()

    if existing_fy:
        return {"fy_id": existing_fy._mapping["acc_financial_year_id"], "period_count": 0}

    now = datetime.now()

    # Insert financial year
    db.execute(
        text("""
            INSERT INTO acc_financial_year
                (co_id, fy_start, fy_end, fy_label, is_active, is_locked,
                 updated_by, updated_date_time)
            VALUES
                (:co_id, :fy_start, :fy_end, :fy_label, 1, 0,
                 :updated_by, :updated_date_time)
        """),
        {
            "co_id": int(co_id),
            "fy_start": fy_start,
            "fy_end": fy_end,
            "fy_label": fy_label,
            "updated_by": int(user_id),
            "updated_date_time": now,
        },
    )
    db.flush()

    # Retrieve the new FY ID
    fy_row = db.execute(
        text("""
            SELECT acc_financial_year_id FROM acc_financial_year
            WHERE co_id = :co_id AND fy_start = :fy_start AND fy_end = :fy_end AND is_active = 1
            ORDER BY acc_financial_year_id DESC LIMIT 1
        """),
        {"co_id": int(co_id), "fy_start": fy_start, "fy_end": fy_end},
    ).fetchone()

    fy_id = fy_row._mapping["acc_financial_year_id"]

    # Create 12 monthly period locks (April=month 1 through March=month 12)
    period_count = 0
    for i in range(12):
        # Month in calendar terms
        month = ((4 + i - 1) % 12) + 1  # Apr=4, May=5, ..., Feb=2, Mar=3
        year = fy_start.year if month >= 4 else fy_end.year

        period_start = date(year, month, 1)

        # Last day of month
        if month == 12:
            period_end = date(year, 12, 31)
        else:
            next_month_first = date(year, month + 1, 1)
            period_end = next_month_first - timedelta(days=1)

        db.execute(
            text("""
                INSERT INTO acc_period_lock
                    (acc_financial_year_id, period_month, period_start, period_end,
                     is_locked, updated_by, updated_date_time)
                VALUES
                    (:acc_financial_year_id, :period_month, :period_start, :period_end,
                     0, :updated_by, :updated_date_time)
            """),
            {
                "acc_financial_year_id": int(fy_id),
                "period_month": i + 1,
                "period_start": period_start,
                "period_end": period_end,
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        period_count += 1

    db.flush()
    return {"fy_id": fy_id, "period_count": period_count}


def seed_voucher_numbering(db: Session, co_id: int, user_id: int) -> int:
    """
    Create numbering sequences per voucher type for the active financial year.

    Returns count of numbering records created.
    """
    # Get active FY
    fy_row = db.execute(
        text("""
            SELECT acc_financial_year_id FROM acc_financial_year
            WHERE co_id = :co_id AND is_active = 1
            ORDER BY fy_start DESC LIMIT 1
        """),
        {"co_id": int(co_id)},
    ).fetchone()

    if not fy_row:
        return 0

    fy_id = fy_row._mapping["acc_financial_year_id"]

    # Get voucher types
    vt_rows = db.execute(
        text("SELECT acc_voucher_type_id, type_code FROM acc_voucher_type WHERE co_id = :co_id AND active = 1"),
        {"co_id": int(co_id)},
    ).fetchall()

    if not vt_rows:
        return 0

    # Check if numbering already exists
    existing_count = db.execute(
        text("""
            SELECT COUNT(*) AS cnt FROM acc_voucher_numbering
            WHERE co_id = :co_id AND acc_financial_year_id = :fy_id AND active = 1
        """),
        {"co_id": int(co_id), "fy_id": int(fy_id)},
    ).scalar()

    if existing_count and existing_count > 0:
        return 0

    now = datetime.now()
    created = 0

    for vt_row in vt_rows:
        vt = vt_row._mapping
        db.execute(
            text("""
                INSERT INTO acc_voucher_numbering
                    (co_id, acc_voucher_type_id, acc_financial_year_id, branch_id,
                     prefix, last_number, active, updated_by, updated_date_time)
                VALUES
                    (:co_id, :acc_voucher_type_id, :acc_financial_year_id, NULL,
                     :prefix, 0, 1, :updated_by, :updated_date_time)
            """),
            {
                "co_id": int(co_id),
                "acc_voucher_type_id": int(vt["acc_voucher_type_id"]),
                "acc_financial_year_id": int(fy_id),
                "prefix": vt["type_code"],
                "updated_by": int(user_id),
                "updated_date_time": now,
            },
        )
        created += 1

    if created > 0:
        db.flush()

    return created


def activate_company(db: Session, co_id: int, user_id: int) -> dict:
    """
    Main activation function — seeds all accounting defaults for a company.

    Calls all seed functions in order, wrapped in a transaction.
    Returns results dict with counts of created records.
    """
    results = {
        "co_id": int(co_id),
        "groups_created": 0,
        "system_ledgers_created": 0,
        "voucher_types_created": 0,
        "party_ledgers_created": 0,
        "account_determinations_created": 0,
        "ageing_slabs_created": 0,
        "financial_year": None,
        "voucher_numbering_created": 0,
        "success": False,
        "error": None,
    }

    try:
        # 1. Ledger groups (chart of accounts structure)
        group_map = seed_ledger_groups(db, co_id, user_id)
        results["groups_created"] = len(group_map)

        # 2. System ledgers (Cash, GST, Purchase, Sales, etc.)
        results["system_ledgers_created"] = seed_system_ledgers(db, co_id, user_id, group_map)

        # 3. Voucher types (Payment, Receipt, Journal, etc.)
        results["voucher_types_created"] = seed_voucher_types(db, co_id, user_id)

        # 4. Party ledgers (auto-create from party_mst)
        results["party_ledgers_created"] = seed_party_ledgers(db, co_id, user_id, group_map)

        # 5. Account determination rules
        results["account_determinations_created"] = seed_account_determinations(db, co_id, user_id)

        # 6. Ageing slabs (Phase 2 placeholder)
        results["ageing_slabs_created"] = seed_ageing_slabs(db, co_id, user_id)

        # 7. Financial year and period locks
        fy_result = seed_financial_year(db, co_id, user_id)
        results["financial_year"] = fy_result

        # 8. Voucher numbering sequences
        results["voucher_numbering_created"] = seed_voucher_numbering(db, co_id, user_id)

        db.commit()
        results["success"] = True

    except Exception as e:
        db.rollback()
        results["success"] = False
        results["error"] = str(e)

    return results
