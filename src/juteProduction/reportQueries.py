"""
Jute Production - Spreader Report Queries.

Source table: tbl_daily_sperder (one row per machine-spell-quality entry).
  - tran_date      report date
  - quality_id     FK to jute_quality_mst.jute_qlty_id
  - production     production count (raw integer)
  - issue          issue count (raw integer)
  - branch_id      scoping

Quality name is resolved via jute_quality_mst.jute_quality.
"""

from sqlalchemy import text


def get_spreader_summary_query():
    """
    Date-wise spreader summary with running balance.

    For each date in [from_date, to_date], returns:
      - opening    : cumulative production - cumulative issue BEFORE that date
      - production : SUM(production) on that date
      - issue      : SUM(issue) on that date
      - closing    : opening + production - issue

    Only dates with at least one row in tbl_daily_sperder appear (no date-spine
    densification) so empty days are skipped, matching the jute summary
    behaviour.

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        WITH historical_open AS (
            SELECT
                COALESCE((
                    SELECT SUM(s.production)
                    FROM tbl_daily_sperder s
                    WHERE s.branch_id = :branch_id
                      AND s.tran_date < :from_date
                ), 0)
                -
                COALESCE((
                    SELECT SUM(s.issue)
                    FROM tbl_daily_sperder s
                    WHERE s.branch_id = :branch_id
                      AND s.tran_date < :from_date
                ), 0) AS opening_bal
        ),
        daily AS (
            SELECT
                s.tran_date AS dt,
                COALESCE(SUM(s.production), 0) AS prod,
                COALESCE(SUM(s.issue), 0)      AS iss
            FROM tbl_daily_sperder s
            WHERE s.branch_id = :branch_id
              AND s.tran_date BETWEEN :from_date AND :to_date
            GROUP BY s.tran_date
        )
        SELECT
            DATE_FORMAT(d.dt, '%d-%m-%Y') AS report_date,
            (
                ho.opening_bal
                + SUM(d.prod - d.iss) OVER (ORDER BY d.dt)
                - (d.prod - d.iss)
            ) AS opening,
            d.prod AS production,
            d.iss  AS issue,
            (
                ho.opening_bal + SUM(d.prod - d.iss) OVER (ORDER BY d.dt)
            ) AS closing
        FROM daily d
        CROSS JOIN historical_open ho
        ORDER BY d.dt
    """
    return text(sql)


def get_spreader_date_production_query():
    """
    Date + quality-wise spreader report with running balance per quality.

    Returns one row per (tran_date, sprd_quality_id) with opening, production,
    issue, and closing. Frontend groups by date and appends a TOTAL row at the
    end of each date group.

    Opening / closing use a per-quality running balance:
        opening[q, day] = hist_open[q] + SUM(prod - iss) OVER (PARTITION BY q ORDER BY day) - (prod - iss)
        closing[q, day] = opening + production - issue

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        WITH daily_data AS (
            SELECT
                s.tran_date AS dt,
                s.sprd_quality_id AS quality_id,
                COALESCE(SUM(s.production), 0) AS prod,
                COALESCE(SUM(s.issue), 0)      AS iss
            FROM tbl_daily_sperder s
            WHERE s.branch_id = :branch_id
              AND s.tran_date BETWEEN :from_date AND :to_date
              AND s.sprd_quality_id IS NOT NULL
            GROUP BY s.tran_date, s.sprd_quality_id
        ),
        hist_open AS (
            SELECT
                s.sprd_quality_id AS quality_id,
                COALESCE(SUM(s.production), 0) - COALESCE(SUM(s.issue), 0) AS opening_bal
            FROM tbl_daily_sperder s
            WHERE s.branch_id = :branch_id
              AND s.tran_date < :from_date
              AND s.sprd_quality_id IS NOT NULL
            GROUP BY s.sprd_quality_id
        )
        SELECT
            DATE_FORMAT(d.dt, '%d-%m-%Y') AS report_date,
            d.quality_id,
            COALESCE(sqm.sprd_jute_quality, CONCAT('Quality #', d.quality_id)) AS quality_name,
            (
                COALESCE(ho.opening_bal, 0)
                + SUM(d.prod - d.iss) OVER (PARTITION BY d.quality_id ORDER BY d.dt)
                - (d.prod - d.iss)
            ) AS opening,
            d.prod AS production,
            d.iss  AS issue,
            (
                COALESCE(ho.opening_bal, 0)
                + SUM(d.prod - d.iss) OVER (PARTITION BY d.quality_id ORDER BY d.dt)
            ) AS closing
        FROM daily_data d
        LEFT JOIN hist_open ho ON ho.quality_id = d.quality_id
        LEFT JOIN sprd_jute_quality_mst sqm ON sqm.sprd_jute_qlty_id = d.quality_id
        ORDER BY d.dt, quality_name
    """
    return text(sql)


def get_spreader_date_issue_query():
    """
    Date + quality-wise issue rows for the matrix view.

    Returns one row per (tran_date, sprd_quality_id) with the summed issue.
    Frontend pivots this into a date x quality matrix.

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            DATE_FORMAT(s.tran_date, '%d-%m-%Y') AS report_date,
            s.sprd_quality_id AS quality_id,
            COALESCE(sqm.sprd_jute_quality, CONCAT('Quality #', s.sprd_quality_id)) AS quality_name,
            COALESCE(SUM(s.issue), 0) AS issue
        FROM tbl_daily_sperder s
        LEFT JOIN sprd_jute_quality_mst sqm ON sqm.sprd_jute_qlty_id = s.sprd_quality_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date BETWEEN :from_date AND :to_date
          AND s.sprd_quality_id IS NOT NULL
        GROUP BY s.tran_date, s.sprd_quality_id, sqm.sprd_jute_quality
        ORDER BY s.tran_date, quality_name
    """
    return text(sql)


def get_spreader_quality_details_query():
    """
    Per-quality totals over the date range.

    Returns one row per quality with:
      - total_production : SUM(production)
      - total_issue      : SUM(issue)
      - balance          : total_production - total_issue

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            s.sprd_quality_id AS quality_id,
            COALESCE(sqm.sprd_jute_quality, CONCAT('Quality #', s.sprd_quality_id)) AS quality_name,
            COALESCE(SUM(s.production), 0) AS total_production,
            COALESCE(SUM(s.issue), 0)      AS total_issue,
            (COALESCE(SUM(s.production), 0) - COALESCE(SUM(s.issue), 0)) AS balance
        FROM tbl_daily_sperder s
        LEFT JOIN sprd_jute_quality_mst sqm ON sqm.sprd_jute_qlty_id = s.sprd_quality_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date BETWEEN :from_date AND :to_date
          AND s.sprd_quality_id IS NOT NULL
        GROUP BY s.sprd_quality_id, sqm.sprd_jute_quality
        ORDER BY quality_name
    """
    return text(sql)
