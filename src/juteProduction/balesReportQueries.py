"""
Jute Production - Bales Report Queries.

Source:
  - tbl_daily_bales_transaction       per (tran_date, spell, quality, customer):
                                       prod_bales, issue_bales
  - tbl_finishing_quality_mst         quality_name (joined on
                                       tbl_fngqual_mst_id = fng_quality_id)
  - tbl_customer_mst                  customer_name (joined on
                                       tbl_cust_mst_id = customer_id)

Per-day balance per (quality, customer):
    opening    = cumulative SUM(prod - issue) for all dates STRICTLY BEFORE
                 this row (so the very first transaction's opening is 0)
    production = SUM(prod_bales) on this date
    issue      = SUM(issue_bales) on this date
    closing    = opening + production - issue

Computed by aggregating to (date, quality, customer), then applying window
functions over PARTITION BY (quality, customer) ORDER BY tran_date.

Parameters: :branch_id (currently unused — bales table has no branch column),
            :from_date, :to_date ('YYYY-MM-DD')
"""

from sqlalchemy import text


def get_bales_entries_query():
    """
    Returns one row per (date, quality, customer) for every date in
    [:from_date, :to_date] where the pair has ANY non-zero stock state
    (opening, production, issue, or closing).

    Construction:
      - base       : actual transactions aggregated by (date, qual, cust)
      - qc_pairs   : every (qual, cust) that has ever transacted up to :to_date
      - date_series: recursive CTE emitting one row per day in the period
      - grid       : period_dates × qc_pairs (the carry-forward skeleton)
      - filled     : pre-period transactions (for opening seed) UNION
                     grid LEFT JOIN base (period-date rows, zero-filled)
      - running    : window functions compute opening / closing per pair

    Requires MySQL 8.0+ (CTEs + window functions). cte_max_recursion_depth
    default is 1000, so periods longer than ~1000 days will need that bumped.
    """
    sql = """
        WITH RECURSIVE
        date_series AS (
            SELECT :from_date AS d
            UNION ALL
            SELECT DATE_ADD(d, INTERVAL 1 DAY)
            FROM date_series
            WHERE d < :to_date
        ),
        base AS (
            SELECT
                tran_date,
                fng_quality_id,
                customer_id,
                COALESCE(SUM(prod_bales), 0)  AS prod,
                COALESCE(SUM(issue_bales), 0) AS issue
            FROM tbl_daily_bales_transaction
            WHERE tran_date <= :to_date
            GROUP BY tran_date, fng_quality_id, customer_id
        ),
        qc_pairs AS (
            SELECT DISTINCT fng_quality_id, customer_id FROM base
        ),
        grid AS (
            SELECT ds.d AS tran_date, qc.fng_quality_id, qc.customer_id
            FROM date_series ds
            CROSS JOIN qc_pairs qc
        ),
        filled AS (
            -- Pre-period transactions (one row per actual tx date) — these
            -- feed the running-balance window so opening is correct at the
            -- start of the period. Their tran_date is < :from_date so they
            -- get filtered out by the final WHERE.
            SELECT tran_date, fng_quality_id, customer_id, prod, issue
            FROM base
            WHERE tran_date < :from_date

            UNION ALL

            -- Period grid (every period_date × every pair), zero-filled where
            -- no transaction exists for that (date, pair).
            SELECT
                g.tran_date,
                g.fng_quality_id,
                g.customer_id,
                COALESCE(b.prod, 0)  AS prod,
                COALESCE(b.issue, 0) AS issue
            FROM grid g
            LEFT JOIN base b
                ON b.tran_date       = g.tran_date
               AND b.fng_quality_id  = g.fng_quality_id
               AND b.customer_id     = g.customer_id
        ),
        running AS (
            SELECT
                tran_date,
                fng_quality_id,
                customer_id,
                prod,
                issue,
                SUM(prod - issue) OVER (
                    PARTITION BY fng_quality_id, customer_id
                    ORDER BY tran_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS closing,
                SUM(prod - issue) OVER (
                    PARTITION BY fng_quality_id, customer_id
                    ORDER BY tran_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                ) AS opening
            FROM filled
        )
        SELECT
            DATE_FORMAT(r.tran_date, '%d-%m-%Y')    AS report_date,
            r.fng_quality_id                        AS quality_id,
            fqm.quality_name                        AS quality_name,
            r.customer_id                           AS customer_id,
            cm.customer_name                        AS customer_name,
            COALESCE(r.opening, 0)                  AS opening,
            r.prod                                  AS production,
            r.issue                                 AS issue,
            COALESCE(r.closing, 0)                  AS closing
        FROM running r
        LEFT JOIN tbl_finishing_quality_mst fqm
               ON fqm.tbl_fngqual_mst_id = r.fng_quality_id
        LEFT JOIN tbl_customer_mst cm
               ON cm.tbl_cust_mst_id = r.customer_id
        WHERE r.tran_date BETWEEN :from_date AND :to_date
          AND (
                COALESCE(r.opening, 0) <> 0
             OR r.prod                <> 0
             OR r.issue               <> 0
             OR COALESCE(r.closing, 0) <> 0
          )
        ORDER BY r.tran_date, fqm.quality_name, cm.customer_name
    """
    return text(sql)
