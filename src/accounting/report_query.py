"""
SQL query functions for the accounting module (Report queries).
Covers: trial balance, profit & loss, balance sheet, ledger report,
day book, cash book, party outstanding, ageing analysis, and GST summary.
"""

from sqlalchemy.sql import text


# =============================================================================
# TRIAL BALANCE
# =============================================================================

def get_trial_balance():
    """Trial balance with opening balance, period debits/credits, and closing balance.
    Params: co_id, from_date, to_date, branch_id (optional).
    """
    sql = """SELECT
        l.acc_ledger_id, l.ledger_name, g.group_name, g.nature,
        COALESCE(l.opening_balance, 0) AS opening_balance,
        l.opening_balance_type,
        SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END) AS period_debit,
        SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS period_credit,
        COALESCE(l.opening_balance, 0)
            + SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END)
            - SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS closing_balance
    FROM acc_ledger l
    JOIN acc_ledger_group g ON l.acc_ledger_group_id = g.acc_ledger_group_id
    LEFT JOIN acc_voucher_line vl ON vl.acc_ledger_id = l.acc_ledger_id AND vl.active = 1
    LEFT JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
        AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    WHERE l.co_id = :co_id AND l.active = 1
    GROUP BY l.acc_ledger_id
    HAVING period_debit != 0 OR period_credit != 0 OR opening_balance != 0
    ORDER BY g.sequence_no, l.ledger_name;"""
    return text(sql)


# =============================================================================
# PROFIT & LOSS
# =============================================================================

def get_profit_loss():
    """Profit & Loss statement filtered to revenue groups (is_revenue = 1).
    Uses affects_gross_profit to separate Trading vs P&L sections.
    Params: co_id, from_date, to_date, branch_id (optional).
    """
    sql = """SELECT
        l.acc_ledger_id, l.ledger_name, g.group_name, g.nature,
        g.affects_gross_profit,
        COALESCE(l.opening_balance, 0) AS opening_balance,
        l.opening_balance_type,
        SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END) AS period_debit,
        SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS period_credit,
        COALESCE(l.opening_balance, 0)
            + SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END)
            - SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS closing_balance
    FROM acc_ledger l
    JOIN acc_ledger_group g ON l.acc_ledger_group_id = g.acc_ledger_group_id
    LEFT JOIN acc_voucher_line vl ON vl.acc_ledger_id = l.acc_ledger_id AND vl.active = 1
    LEFT JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
        AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    WHERE l.co_id = :co_id AND l.active = 1
        AND g.is_revenue = 1
    GROUP BY l.acc_ledger_id
    HAVING period_debit != 0 OR period_credit != 0 OR opening_balance != 0
    ORDER BY g.affects_gross_profit DESC, g.sequence_no, l.ledger_name;"""
    return text(sql)


# =============================================================================
# BALANCE SHEET
# =============================================================================

def get_balance_sheet():
    """Balance Sheet filtered to non-revenue groups (is_revenue = 0).
    Params: co_id, from_date, to_date, branch_id (optional).
    """
    sql = """SELECT
        l.acc_ledger_id, l.ledger_name, g.group_name, g.nature,
        COALESCE(l.opening_balance, 0) AS opening_balance,
        l.opening_balance_type,
        SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END) AS period_debit,
        SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS period_credit,
        COALESCE(l.opening_balance, 0)
            + SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END)
            - SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS closing_balance
    FROM acc_ledger l
    JOIN acc_ledger_group g ON l.acc_ledger_group_id = g.acc_ledger_group_id
    LEFT JOIN acc_voucher_line vl ON vl.acc_ledger_id = l.acc_ledger_id AND vl.active = 1
    LEFT JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
        AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    WHERE l.co_id = :co_id AND l.active = 1
        AND g.is_revenue = 0
    GROUP BY l.acc_ledger_id
    HAVING period_debit != 0 OR period_credit != 0 OR opening_balance != 0
    ORDER BY g.sequence_no, l.ledger_name;"""
    return text(sql)


# =============================================================================
# LEDGER REPORT
# =============================================================================

def get_ledger_report():
    """Ledger-wise transaction detail with contra ledger names.
    Params: ledger_id, from_date, to_date, branch_id (optional).
    """
    sql = """SELECT v.voucher_date, v.voucher_no, vt.type_name AS voucher_type,
        vl.dr_cr, vl.amount,
        CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE NULL END AS debit,
        CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE NULL END AS credit,
        v.narration, v.ref_no,
        GROUP_CONCAT(DISTINCT cl.ledger_name) AS contra_ledgers
    FROM acc_voucher_line vl
    JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
    JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
    LEFT JOIN acc_voucher_line cvl ON cvl.acc_voucher_id = v.acc_voucher_id
        AND cvl.acc_voucher_line_id != vl.acc_voucher_line_id
    LEFT JOIN acc_ledger cl ON cvl.acc_ledger_id = cl.acc_ledger_id
    WHERE vl.acc_ledger_id = :ledger_id AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    GROUP BY vl.acc_voucher_line_id
    ORDER BY v.voucher_date, v.voucher_no;"""
    return text(sql)


# =============================================================================
# DAY BOOK
# =============================================================================

def get_day_book():
    """All approved vouchers for a date range with optional type filter.
    Params: co_id, from_date, to_date, branch_id (optional), voucher_type_id (optional).
    """
    sql = """SELECT v.voucher_date, v.voucher_no, vt.type_name AS voucher_type,
        v.total_amount, v.narration, v.ref_no,
        p.supp_name AS party_name, bm.branch_name,
        v.is_auto_posted, v.source_doc_type
    FROM acc_voucher v
    JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
    LEFT JOIN party_mst p ON v.party_id = p.party_id
    LEFT JOIN branch_mst bm ON v.branch_id = bm.branch_id
    WHERE v.co_id = :co_id AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
        AND (:voucher_type_id IS NULL OR v.acc_voucher_type_id = :voucher_type_id)
    ORDER BY v.voucher_date, vt.type_name, v.voucher_no;"""
    return text(sql)


# =============================================================================
# CASH BOOK
# =============================================================================

def get_cash_book():
    """Cash ledger transactions with receipt/payment and contra ledgers.
    Filters to ledgers with ledger_type = 'C' (Cash).
    Params: co_id, from_date, to_date, branch_id (optional).
    """
    sql = """SELECT v.voucher_date, v.voucher_no, vt.type_name AS voucher_type,
        CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE NULL END AS receipt,
        CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE NULL END AS payment,
        v.narration, v.ref_no,
        GROUP_CONCAT(DISTINCT cl.ledger_name) AS contra_ledgers
    FROM acc_voucher_line vl
    JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
    JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
    JOIN acc_ledger cash_l ON vl.acc_ledger_id = cash_l.acc_ledger_id AND cash_l.ledger_type = 'C'
    LEFT JOIN acc_voucher_line cvl ON cvl.acc_voucher_id = v.acc_voucher_id
        AND cvl.acc_voucher_line_id != vl.acc_voucher_line_id
    LEFT JOIN acc_ledger cl ON cvl.acc_ledger_id = cl.acc_ledger_id
    WHERE cash_l.co_id = :co_id AND v.status_id = 3 AND v.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    GROUP BY vl.acc_voucher_line_id
    ORDER BY v.voucher_date, v.voucher_no;"""
    return text(sql)


# =============================================================================
# PARTY OUTSTANDING
# =============================================================================

def get_party_outstanding():
    """Debtor/Creditor outstanding bills with overdue days.
    Params: co_id, party_type (optional: 'DEBTOR' or 'CREDITOR'), branch_id (optional).
    """
    sql = """SELECT p.party_id, p.supp_name AS party_name,
        br.bill_no, br.bill_date, br.due_date,
        br.amount AS bill_amount, br.pending_amount AS outstanding,
        DATEDIFF(CURDATE(), br.due_date) AS overdue_days
    FROM acc_bill_ref br
    JOIN party_mst p ON br.party_id = p.party_id
    JOIN acc_voucher v ON br.acc_voucher_id = v.acc_voucher_id
    WHERE v.co_id = :co_id AND br.status IN ('OPEN', 'PARTIAL') AND br.active = 1
        AND (:party_type IS NULL OR
             (:party_type = 'CREDITOR' AND v.acc_voucher_type_id IN (SELECT acc_voucher_type_id FROM acc_voucher_type WHERE type_category = 'PURCHASE' AND co_id = :co_id))
             OR
             (:party_type = 'DEBTOR' AND v.acc_voucher_type_id IN (SELECT acc_voucher_type_id FROM acc_voucher_type WHERE type_category = 'SALES' AND co_id = :co_id)))
        AND (:branch_id IS NULL OR v.branch_id = :branch_id)
    ORDER BY br.due_date ASC;"""
    return text(sql)


# =============================================================================
# AGEING ANALYSIS
# =============================================================================

def get_ageing_analysis():
    """AR/AP ageing buckets: not due, 1-30, 31-60, 61-90, above 90 days.
    Params: co_id.
    """
    sql = """SELECT p.party_id, p.supp_name AS party_name,
        SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) <= 0 THEN br.pending_amount ELSE 0 END) AS not_due,
        SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 1 AND 30 THEN br.pending_amount ELSE 0 END) AS days_1_30,
        SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 31 AND 60 THEN br.pending_amount ELSE 0 END) AS days_31_60,
        SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 61 AND 90 THEN br.pending_amount ELSE 0 END) AS days_61_90,
        SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) > 90 THEN br.pending_amount ELSE 0 END) AS above_90,
        SUM(br.pending_amount) AS total_outstanding
    FROM acc_bill_ref br
    JOIN party_mst p ON br.party_id = p.party_id
    WHERE br.co_id = :co_id AND br.status IN ('OPEN', 'PARTIAL') AND br.active = 1
    GROUP BY p.party_id
    ORDER BY total_outstanding DESC;"""
    return text(sql)


# =============================================================================
# GST SUMMARY (GSTR-3B STYLE)
# =============================================================================

def get_gst_summary():
    """GSTR-3B style GST summary using UNION ALL for outward taxable supplies,
    inward supplies under RCM, and eligible ITC sections.
    Params: co_id, from_date, to_date, branch_gstin (optional).
    """
    sql = """SELECT 'OUTWARD_TAXABLE' AS section,
        avg.supply_type,
        SUM(avg.taxable_amount) AS taxable_amount,
        SUM(avg.cgst_amount) AS cgst_amount,
        SUM(avg.sgst_amount) AS sgst_amount,
        SUM(avg.igst_amount) AS igst_amount,
        SUM(avg.cess_amount) AS cess_amount,
        SUM(avg.total_gst_amount) AS total_gst_amount
    FROM acc_voucher_gst avg
    JOIN acc_voucher v ON avg.acc_voucher_id = v.acc_voucher_id
    JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
    WHERE v.co_id = :co_id AND v.status_id = 3 AND v.active = 1 AND avg.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_gstin IS NULL OR v.branch_gstin = :branch_gstin)
        AND vt.type_category IN ('SALES', 'DEBIT_NOTE')
        AND avg.is_rcm = 0
    GROUP BY avg.supply_type

    UNION ALL

    SELECT 'INWARD_RCM' AS section,
        avg.supply_type,
        SUM(avg.taxable_amount) AS taxable_amount,
        SUM(avg.cgst_amount) AS cgst_amount,
        SUM(avg.sgst_amount) AS sgst_amount,
        SUM(avg.igst_amount) AS igst_amount,
        SUM(avg.cess_amount) AS cess_amount,
        SUM(avg.total_gst_amount) AS total_gst_amount
    FROM acc_voucher_gst avg
    JOIN acc_voucher v ON avg.acc_voucher_id = v.acc_voucher_id
    WHERE v.co_id = :co_id AND v.status_id = 3 AND v.active = 1 AND avg.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_gstin IS NULL OR v.branch_gstin = :branch_gstin)
        AND avg.is_rcm = 1
    GROUP BY avg.supply_type

    UNION ALL

    SELECT 'ELIGIBLE_ITC' AS section,
        avg.itc_eligibility AS supply_type,
        SUM(avg.taxable_amount) AS taxable_amount,
        SUM(avg.cgst_amount) AS cgst_amount,
        SUM(avg.sgst_amount) AS sgst_amount,
        SUM(avg.igst_amount) AS igst_amount,
        SUM(avg.cess_amount) AS cess_amount,
        SUM(avg.total_gst_amount) AS total_gst_amount
    FROM acc_voucher_gst avg
    JOIN acc_voucher v ON avg.acc_voucher_id = v.acc_voucher_id
    JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
    WHERE v.co_id = :co_id AND v.status_id = 3 AND v.active = 1 AND avg.active = 1
        AND v.voucher_date BETWEEN :from_date AND :to_date
        AND (:branch_gstin IS NULL OR v.branch_gstin = :branch_gstin)
        AND vt.type_category IN ('PURCHASE', 'CREDIT_NOTE')
        AND avg.itc_eligibility IS NOT NULL
    GROUP BY avg.itc_eligibility;"""
    return text(sql)
