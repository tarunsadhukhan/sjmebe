"""
Jute Procurement Report Queries.
Contains SQL queries for jute stock and related reports.
"""

from sqlalchemy import text


def _group_path_cte():
    """
    Returns a recursive CTE that builds full hierarchical group paths.
    Creates a temp table `full_group_paths` with columns: item_grp_id, item_grp_name_path.
    Usage: prepend to any query, then JOIN full_group_paths fgp ON fgp.item_grp_id = ...
    and use COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name.
    """
    return """
        WITH RECURSIVE group_path AS (
            SELECT
                igm.item_grp_id AS target_id,
                igm.item_grp_id,
                igm.item_grp_name,
                igm.parent_grp_id,
                CAST(igm.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst igm

            UNION ALL

            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        ),
        full_group_paths AS (
            SELECT target_id AS item_grp_id, item_grp_name_path
            FROM group_path
            WHERE parent_grp_id IS NULL
        )
    """


def get_jute_stock_report_query():
    """
    Query to calculate daily jute stock position grouped by item group and item.

    Returns opening stock, receipt, issue, closing stock, and MTD receipt/issue
    for a given branch and report date.

    Key tables:
    - jute_mr + jute_mr_li for receipts (out_date = inward date, actual_weight, actual_item_id)
    - jute_issue for issues (issue_date, weight, COALESCE(item_id, mrli.actual_item_id))
    - item_mst + item_grp_mst for item/group names

    Parameters: :branch_id (int), :report_date (string 'YYYY-MM-DD')
    """
    sql = _group_path_cte() + """,
        -- Receipts before report_date (for opening)
        receipt_before AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date < :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- Issues before report_date (for opening)
        issue_before AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date < :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        -- Receipts ON report_date
        receipt_on AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date = :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- Issues ON report_date
        issue_on AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        -- MTD receipts (1st of month to report_date)
        receipt_mtd AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date >= DATE_SUB(:report_date, INTERVAL DAYOFMONTH(:report_date) - 1 DAY)
              AND jm.out_date <= :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- MTD issues (1st of month to report_date)
        issue_mtd AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date >= DATE_SUB(:report_date, INTERVAL DAYOFMONTH(:report_date) - 1 DAY)
              AND ji.issue_date <= :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        )

        SELECT
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS item_group_name,
            im.item_id,
            im.item_name,
            ROUND(COALESCE(rb.total_weight, 0) - COALESCE(ib.total_weight, 0), 3) AS opening_weight,
            ROUND(COALESCE(ro.total_weight, 0), 3) AS receipt_weight,
            ROUND(COALESCE(io.total_weight, 0), 3) AS issue_weight,
            ROUND(
                (COALESCE(rb.total_weight, 0) - COALESCE(ib.total_weight, 0))
                + COALESCE(ro.total_weight, 0)
                - COALESCE(io.total_weight, 0),
                3
            ) AS closing_weight,
            ROUND(COALESCE(rm.total_weight, 0), 3) AS mtd_receipt_weight,
            ROUND(COALESCE(im2.total_weight, 0), 3) AS mtd_issue_weight
        FROM item_mst im
        INNER JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        LEFT JOIN receipt_before rb ON rb.item_id = im.item_id
        LEFT JOIN issue_before ib ON ib.item_id = im.item_id
        LEFT JOIN receipt_on ro ON ro.item_id = im.item_id
        LEFT JOIN issue_on io ON io.item_id = im.item_id
        LEFT JOIN receipt_mtd rm ON rm.item_id = im.item_id
        LEFT JOIN issue_mtd im2 ON im2.item_id = im.item_id
        WHERE (
            rb.item_id IS NOT NULL
            OR ib.item_id IS NOT NULL
            OR ro.item_id IS NOT NULL
            OR io.item_id IS NOT NULL
            OR rm.item_id IS NOT NULL
            OR im2.item_id IS NOT NULL
        )
        ORDER BY ig.item_grp_name, im.item_name
    """
    return text(sql)


def get_jute_summary_report_query():
    """
    Date-wise jute stock summary for a given branch and date range.

    Sources:
      - Purchase: tbl_jute_received  (recv_date, weight, branch_id) — flat table.
      - Issue:    assorting_entry (tran_date, net_wt, jute_quality_id) — flat
                  table; net_wt is taken as the issue weight directly. Note: this
                  table has no branch_id column, so the issue side is NOT
                  branch-scoped.

    For each date in [from_date, to_date], returns:
      - opening: cumulative purchases - cumulative issues before that date
      - purchase: total received weight on that date
      - issue:    total issue weight on that date (sum of net_wt)
      - closing:  opening + purchase - issue

    Parameters: :branch_id (int), :from_date ('YYYY-MM-DD'), :to_date ('YYYY-MM-DD')
    """
    sql = """
                  WITH RECURSIVE date_series AS (
            SELECT CAST(:from_date AS DATE) AS dt
            UNION ALL
            SELECT DATE_ADD(dt, INTERVAL 1 DAY)
            FROM date_series
            WHERE dt < CAST(:to_date AS DATE)
        ),
        historical_open AS (
            SELECT
                COALESCE((
                    SELECT SUM(r.weight)
                    FROM tbl_jute_received r
                    WHERE r.branch_id = :branch_id
                      AND r.recv_date < :from_date
                ), 0)
                -
                COALESCE((
                    SELECT SUM(s.net_wt)
                    FROM assorting_entry s
                    WHERE s.entry_date < :from_date
                ), 0) AS opening_bal
        ),
        daily_receipt AS (
            SELECT r.recv_date AS dt,
                   ROUND(COALESCE(SUM(r.weight), 0), 3) AS wt
            FROM tbl_jute_received r
            WHERE r.branch_id = :branch_id
              AND r.recv_date BETWEEN :from_date AND :to_date
            GROUP BY r.recv_date
        ),
        daily_issue AS (
            SELECT s.entry_date AS dt,
                   ROUND(COALESCE(SUM(s.net_wt), 0), 3) AS wt
            FROM assorting_entry s
            WHERE s.entry_date BETWEEN :from_date AND :to_date
            GROUP BY s.entry_date
        ),
        daily AS (
            SELECT
                ds.dt,
                COALESCE(dr.wt, 0) AS rcv,
                COALESCE(di.wt, 0) AS iss
            FROM date_series ds
            LEFT JOIN daily_receipt dr ON dr.dt = ds.dt
            LEFT JOIN daily_issue di ON di.dt = ds.dt
        )
        SELECT
            DATE_FORMAT(d.dt, '%d-%m-%Y') AS report_date,
            ROUND(
                ho.opening_bal
                + SUM(d.rcv - d.iss) OVER (ORDER BY d.dt)
                - (d.rcv - d.iss),
                3
            ) AS opening,
            d.rcv AS purchase,
            d.iss AS issue,
            ROUND(
                ho.opening_bal + SUM(d.rcv - d.iss) OVER (ORDER BY d.dt),
                3
            ) AS closing
        FROM daily d
        CROSS JOIN historical_open ho
        ORDER BY d.dt
    """
    print('summary report query:', sql )
    return text(sql)


def get_jute_details_report_query():
    """
    Date-wise + quality-wise jute report.

    Returns one row per (date, quality) for a given branch and date range,
    showing opening, purchase, issue and closing weights per quality.

    Sources (same as summary report):
      - tbl_jute_received  (recv_date, quality_id, weight, branch_id) for Purchase.
      - assorting_entry (entry_date, jute_quality_id, net_wt) for Issue;
        net_wt is taken as the issue weight directly. Note: this table has no
        branch_id column, so the issue side is NOT branch-scoped.

    Opening / closing use a running balance per quality:
        opening[quality, day]  = hist_open[quality]
                                + SUM(rcv - iss) OVER (PARTITION BY quality ORDER BY day) - (rcv - iss)
        closing[quality, day]  = opening + purchase - issue

    Only (date, quality) pairs with activity in the range are returned —
    frontend can compute per-day totals across qualities.

    Parameters: :branch_id (int), :from_date ('YYYY-MM-DD'), :to_date ('YYYY-MM-DD')
    """
    sql = """
                WITH daily_receipt AS (
            SELECT r.recv_date AS dt,
                   r.quality_id,
                   ROUND(COALESCE(SUM(r.weight), 0), 3) AS wt
            FROM tbl_jute_received r
            WHERE r.branch_id = :branch_id
              AND r.recv_date BETWEEN :from_date AND :to_date
              AND r.quality_id IS NOT NULL
            GROUP BY r.recv_date, r.quality_id
        ),
        daily_issue AS (
            SELECT s.entry_date AS dt,
                   s.quality_id  AS quality_id,
                   ROUND(COALESCE(SUM(s.net_wt), 0), 3) AS wt
            FROM assorting_entry s
            WHERE s.entry_date BETWEEN :from_date AND :to_date
              AND s.quality_id IS NOT NULL
            GROUP BY s.entry_date, s.quality_id
        ),
        day_quality AS (
            SELECT dt, quality_id FROM daily_receipt
            UNION
            SELECT dt, quality_id FROM daily_issue
        ),
        hist_open AS (
            SELECT quality_id, SUM(bal) AS opening_bal
            FROM (
                SELECT r.quality_id, SUM(r.weight) AS bal
                FROM tbl_jute_received r
                WHERE r.branch_id = :branch_id
                  AND r.recv_date < :from_date
                  AND r.quality_id IS NOT NULL
                GROUP BY r.quality_id
                UNION ALL
                SELECT s.quality_id AS quality_id, -SUM(s.net_wt) AS bal
                FROM assorting_entry s
                WHERE s.entry_date < :from_date
                  AND s.quality_id IS NOT NULL
                GROUP BY s.quality_id
            ) x
            GROUP BY quality_id
        ),
        all_days AS (
            SELECT
                dq.dt,
                dq.quality_id,
                COALESCE(dr.wt, 0) AS rcv,
                COALESCE(di.wt, 0) AS iss
            FROM day_quality dq
            LEFT JOIN daily_receipt dr ON dr.dt = dq.dt AND dr.quality_id = dq.quality_id
            LEFT JOIN daily_issue di ON di.dt = dq.dt AND di.quality_id = dq.quality_id
        )
        SELECT
            DATE_FORMAT(ad.dt, '%d-%m-%Y') AS report_date,
            ad.quality_id,
            COALESCE(jqm.jute_quality, CONCAT('Quality #', ad.quality_id)) AS quality_name,
            ROUND(
                COALESCE(ho.opening_bal, 0)
                + SUM(ad.rcv - ad.iss) OVER (PARTITION BY ad.quality_id ORDER BY ad.dt)
                - (ad.rcv - ad.iss),
                3
            ) AS opening,
            ad.rcv AS purchase,
            ad.iss AS issue,
            ROUND(
                COALESCE(ho.opening_bal, 0)
                + SUM(ad.rcv - ad.iss) OVER (PARTITION BY ad.quality_id ORDER BY ad.dt),
                3
            ) AS closing
        FROM all_days ad
        LEFT JOIN hist_open ho ON ho.quality_id = ad.quality_id
        LEFT JOIN jute_quality_mst jqm ON jqm.jute_qlty_id = ad.quality_id
        ORDER BY ad.dt, quality_name
    """
    return text(sql)


def get_batch_cost_report_query():
    """
    Query to calculate yarn quality-wise planned vs actual jute issue
    for a given branch and date (batch cost report).

    For each yarn type assigned on the date, computes:
    - Planned weight: (batch_plan_li percentage / 100) * total actual issue weight for that yarn type
    - Actual weight: sum of jute_issue weight grouped by yarn_type + item
    - Avg rate: average of jute_mr_li.actual_rate per group
    - Issue value: sum of jute_issue.issue_value
    - Variance: actual_weight - planned_weight

    Uses a UNION to emulate FULL OUTER JOIN (MySQL doesn't support it natively).

    Parameters: :branch_id (int), :report_date (string 'YYYY-MM-DD')
    """
    sql = """
        -- CTE 1: Total actual issue weight per yarn type on this date
        WITH yarn_totals AS (
            SELECT
                ji.yarn_type_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_actual_weight
            FROM jute_issue ji
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY ji.yarn_type_id
        ),

        -- CTE 2: Planned weights from batch daily assignments + batch plan line items
        planned AS (
            SELECT
                bda.jute_yarn_id AS yarn_type_id,
                bpl.jute_quality_id AS item_id,
                bpl.percentage,
                yt.total_actual_weight,
                ROUND((bpl.percentage / 100.0) * COALESCE(yt.total_actual_weight, 0), 3) AS planned_weight
            FROM jute_batch_daily_assign bda
            INNER JOIN jute_batch_plan_li bpl ON bpl.batch_plan_id = bda.batch_plan_id
            LEFT JOIN yarn_totals yt ON yt.yarn_type_id = bda.jute_yarn_id
            WHERE bda.branch_id = :branch_id
              AND bda.assign_date = :report_date
              AND bda.status_id IN (1, 3)
        ),

        -- CTE 3: Actual issues grouped by yarn_type + item
        actual AS (
            SELECT
                ji.yarn_type_id,
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS actual_weight,
                ROUND(AVG(mrli.actual_rate), 2) AS avg_rate,
                ROUND(COALESCE(SUM(ji.issue_value), 0), 2) AS issue_value
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY ji.yarn_type_id, COALESCE(ji.item_id, mrli.actual_item_id)
        )

        -- FULL OUTER JOIN emulated via LEFT JOIN + UNION
        -- Part 1: All planned items, with actual data where available
        SELECT
            COALESCE(p.yarn_type_id, a.yarn_type_id) AS yarn_type_id,
            COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
            COALESCE(p.item_id, a.item_id) AS item_id,
            im.item_name,
            im.item_grp_id,
            COALESCE(igm.item_grp_name) AS item_group_name,
            COALESCE(p.planned_weight, 0) AS planned_weight,
            COALESCE(a.actual_weight, 0) AS actual_weight,
            COALESCE(a.avg_rate, 0) AS actual_rate,
            COALESCE(a.issue_value, 0) AS issue_value,
            ROUND(COALESCE(a.actual_weight, 0) - COALESCE(p.planned_weight, 0), 3) AS variance
        FROM planned p
        LEFT JOIN actual a ON a.yarn_type_id = p.yarn_type_id AND a.item_id = p.item_id
        LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = COALESCE(p.yarn_type_id, a.yarn_type_id)
        LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
        LEFT JOIN item_mst im ON im.item_id = COALESCE(p.item_id, a.item_id)
        LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id

        UNION

        -- Part 2: Actual-only items not in the plan
        SELECT
            a.yarn_type_id,
            COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
            a.item_id,
            im.item_name,
            im.item_grp_id,
            COALESCE(igm.item_grp_name) AS item_group_name,
            0 AS planned_weight,
            COALESCE(a.actual_weight, 0) AS actual_weight,
            COALESCE(a.avg_rate, 0) AS actual_rate,
            COALESCE(a.issue_value, 0) AS issue_value,
            ROUND(COALESCE(a.actual_weight, 0) - 0, 3) AS variance
        FROM actual a
        LEFT JOIN planned p ON p.yarn_type_id = a.yarn_type_id AND p.item_id = a.item_id
        LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = a.yarn_type_id
        LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
        LEFT JOIN item_mst im ON im.item_id = a.item_id
        LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
        WHERE p.yarn_type_id IS NULL

        ORDER BY yarn_type_name, item_name
    """
    return text(sql)
