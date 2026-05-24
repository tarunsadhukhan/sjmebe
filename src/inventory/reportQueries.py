"""
Inventory Report Queries.
Contains SQL queries for inventory reports (stock position, item-wise issue).
"""

from sqlalchemy import text


def get_inventory_stock_report_query():
    """
    Inventory stock position report query.

    Returns one row per item with opening, receipt, issue, closing quantities
    over a date range. Opening = all receipts before date_from minus all issues
    before date_from. Closing = opening + receipts_in_range - issues_in_range.

    Only considers approved inwards (sr_status = 3) and active issues.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional branch filter
        :item_grp_id (int or NULL) - optional item group filter
        :date_from (str) - range start (YYYY-MM-DD), required
        :date_to (str) - range end (YYYY-MM-DD), required
        :search_like (str or NULL) - LIKE pattern for item_name, item_grp_name
        :limit (int) - pagination limit
        :offset (int) - pagination offset
    """
    sql = """
    WITH receipts_before AS (
        SELECT
            pid.item_id,
            COALESCE(SUM(pid.approved_qty), 0) AS total_qty
        FROM proc_inward_dtl AS pid
        INNER JOIN proc_inward AS pi ON pi.inward_id = pid.inward_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
        WHERE pid.active = 1
            AND pi.sr_status = 3
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
            AND pi.inward_date < :date_from
        GROUP BY pid.item_id
    ),
    issues_before AS (
        SELECT
            il.item_id,
            COALESCE(SUM(il.issue_qty), 0) AS total_qty
        FROM issue_li AS il
        INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
        WHERE (ih.active = 1 OR ih.active IS NULL)
            AND ih.status_id IN (1, 3, 5, 20)
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
            AND ih.issue_date < :date_from
        GROUP BY il.item_id
    ),
    receipts_in_range AS (
        SELECT
            pid.item_id,
            COALESCE(SUM(pid.approved_qty), 0) AS total_qty
        FROM proc_inward_dtl AS pid
        INNER JOIN proc_inward AS pi ON pi.inward_id = pid.inward_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
        WHERE pid.active = 1
            AND pi.sr_status = 3
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
            AND pi.inward_date >= :date_from
            AND pi.inward_date <= :date_to
        GROUP BY pid.item_id
    ),
    issues_in_range AS (
        SELECT
            il.item_id,
            COALESCE(SUM(il.issue_qty), 0) AS total_qty
        FROM issue_li AS il
        INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
        WHERE (ih.active = 1 OR ih.active IS NULL)
            AND ih.status_id IN (1, 3, 5, 20)
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
            AND ih.issue_date >= :date_from
            AND ih.issue_date <= :date_to
        GROUP BY il.item_id
    ),
    all_items AS (
        SELECT item_id FROM receipts_before
        UNION
        SELECT item_id FROM issues_before
        UNION
        SELECT item_id FROM receipts_in_range
        UNION
        SELECT item_id FROM issues_in_range
    )
    SELECT
        im.item_id,
        im.item_name,
        igm.item_grp_name,
        um.uom_name,
        (COALESCE(rb.total_qty, 0) - COALESCE(ib.total_qty, 0)) AS opening_qty,
        COALESCE(rir.total_qty, 0) AS receipt_qty,
        COALESCE(iir.total_qty, 0) AS issue_qty,
        (COALESCE(rb.total_qty, 0) - COALESCE(ib.total_qty, 0)
         + COALESCE(rir.total_qty, 0) - COALESCE(iir.total_qty, 0)) AS closing_qty
    FROM all_items AS ai
    INNER JOIN item_mst AS im ON im.item_id = ai.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = im.uom_id
    LEFT JOIN receipts_before AS rb ON rb.item_id = ai.item_id
    LEFT JOIN issues_before AS ib ON ib.item_id = ai.item_id
    LEFT JOIN receipts_in_range AS rir ON rir.item_id = ai.item_id
    LEFT JOIN issues_in_range AS iir ON iir.item_id = ai.item_id
    WHERE (:item_grp_id IS NULL OR im.item_grp_id = :item_grp_id)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
        )
    ORDER BY igm.item_grp_name, im.item_name
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_inventory_stock_report_count_query():
    """
    Count query for inventory stock report pagination.
    """
    sql = """
    WITH receipts_before AS (
        SELECT DISTINCT pid.item_id
        FROM proc_inward_dtl AS pid
        INNER JOIN proc_inward AS pi ON pi.inward_id = pid.inward_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
        WHERE pid.active = 1
            AND pi.sr_status = 3
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
            AND pi.inward_date < :date_from
    ),
    issues_before AS (
        SELECT DISTINCT il.item_id
        FROM issue_li AS il
        INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
        WHERE (ih.active = 1 OR ih.active IS NULL)
            AND ih.status_id IN (1, 3, 5, 20)
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
            AND ih.issue_date < :date_from
    ),
    receipts_in_range AS (
        SELECT DISTINCT pid.item_id
        FROM proc_inward_dtl AS pid
        INNER JOIN proc_inward AS pi ON pi.inward_id = pid.inward_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = pi.branch_id
        WHERE pid.active = 1
            AND pi.sr_status = 3
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR pi.branch_id = :branch_id)
            AND pi.inward_date >= :date_from
            AND pi.inward_date <= :date_to
    ),
    issues_in_range AS (
        SELECT DISTINCT il.item_id
        FROM issue_li AS il
        INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
        LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
        WHERE (ih.active = 1 OR ih.active IS NULL)
            AND ih.status_id IN (1, 3, 5, 20)
            AND bm.co_id = :co_id
            AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
            AND ih.issue_date >= :date_from
            AND ih.issue_date <= :date_to
    ),
    all_items AS (
        SELECT item_id FROM receipts_before
        UNION
        SELECT item_id FROM issues_before
        UNION
        SELECT item_id FROM receipts_in_range
        UNION
        SELECT item_id FROM issues_in_range
    )
    SELECT COUNT(1) AS total
    FROM all_items AS ai
    INNER JOIN item_mst AS im ON im.item_id = ai.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    WHERE (:item_grp_id IS NULL OR im.item_grp_id = :item_grp_id)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
        );
    """
    return text(sql)


def get_issue_itemwise_report_query():
    """
    Item-wise issue report query.

    Returns one row per issue line item with issue header info,
    item details, and department/cost factor/machine info.

    Parameters:
        :co_id (int) - required
        :branch_id (int or NULL) - optional branch filter
        :item_grp_id (int or NULL) - optional item group filter
        :date_from (str or NULL) - date range start (YYYY-MM-DD)
        :date_to (str or NULL) - date range end (YYYY-MM-DD)
        :search_like (str or NULL) - LIKE pattern for item_name, branch_name, item_grp_name
        :limit (int) - pagination limit
        :offset (int) - pagination offset
    """
    sql = """
    SELECT
        il.issue_li_id,
        ih.issue_id,
        ih.issue_pass_no,
        ih.issue_pass_print_no,
        ih.issue_date,
        bm.branch_name,
        bm.branch_prefix,
        cm.co_prefix,
        dm.dept_desc AS department,
        im.item_name,
        igm.item_grp_name,
        um.uom_name,
        il.req_quantity,
        il.issue_qty,
        etm.expense_type_name,
        cfm.cost_factor_name,
        mm.machine_name,
        sm.status_name
    FROM issue_li AS il
    INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
    LEFT JOIN co_mst AS cm ON cm.co_id = bm.co_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = ih.dept_id
    LEFT JOIN item_mst AS im ON im.item_id = il.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    LEFT JOIN uom_mst AS um ON um.uom_id = il.uom_id
    LEFT JOIN expense_type_mst AS etm ON etm.expense_type_id = il.expense_type_id
    LEFT JOIN cost_factor_mst AS cfm ON cfm.cost_factor_id = il.cost_factor_id
    LEFT JOIN machine_mst AS mm ON mm.machine_id = il.machine_id
    LEFT JOIN status_mst AS sm ON sm.status_id = ih.status_id
    WHERE (ih.active = 1 OR ih.active IS NULL)
        AND ih.status_id IN (1, 3, 5, 20)
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
        AND (:item_grp_id IS NULL OR im.item_grp_id = :item_grp_id)
        AND (:date_from IS NULL OR ih.issue_date >= :date_from)
        AND (:date_to IS NULL OR ih.issue_date <= :date_to)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR dm.dept_desc LIKE :search_like
        )
    ORDER BY ih.issue_date DESC, ih.issue_id DESC, il.issue_li_id
    LIMIT :limit OFFSET :offset;
    """
    return text(sql)


def get_issue_itemwise_report_count_query():
    """
    Count query for item-wise issue report pagination.
    """
    sql = """
    SELECT COUNT(1) AS total
    FROM issue_li AS il
    INNER JOIN issue_hdr AS ih ON ih.issue_id = il.issue_id
    LEFT JOIN branch_mst AS bm ON bm.branch_id = ih.branch_id
    LEFT JOIN dept_mst AS dm ON dm.dept_id = ih.dept_id
    LEFT JOIN item_mst AS im ON im.item_id = il.item_id
    LEFT JOIN item_grp_mst AS igm ON igm.item_grp_id = im.item_grp_id
    WHERE (ih.active = 1 OR ih.active IS NULL)
        AND ih.status_id IN (1, 3, 5, 20)
        AND bm.co_id = :co_id
        AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
        AND (:item_grp_id IS NULL OR im.item_grp_id = :item_grp_id)
        AND (:date_from IS NULL OR ih.issue_date >= :date_from)
        AND (:date_to IS NULL OR ih.issue_date <= :date_to)
        AND (
            :search_like IS NULL
            OR im.item_name LIKE :search_like
            OR bm.branch_name LIKE :search_like
            OR igm.item_grp_name LIKE :search_like
            OR dm.dept_desc LIKE :search_like
        );
    """
    return text(sql)
