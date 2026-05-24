"""
Jute Production - Other Entries Report Queries.

Source: tbl_daily_finishing — one row per (tran_date, spell_id).
        Aggregated up to one row per tran_date for the report.

Column mapping (table -> report):
    tran_date              -> report_date           (DATE_FORMAT dd-mm-YYYY)
    looms                  -> looms
    cuts                   -> cuts
    cutting + hemming      -> cutting_hemming_bdl   (combined column)
    heracle                -> heracle_bdl
    branding               -> branding
    hand_sewer             -> h_sewer_bdl
    bales                  -> bales_production
    issue_bales            -> bales_issue

Parameters: :branch_id (currently unused — tbl_daily_finishing has no branch
            column; add a filter if/when one is introduced),
            :from_date, :to_date ('YYYY-MM-DD')
"""

from sqlalchemy import text


def get_other_entries_query():
    sql = """
        SELECT
            DATE_FORMAT(tran_date, '%d-%m-%Y')                  AS report_date,
            COALESCE(SUM(looms), 0)                             AS looms,
            COALESCE(SUM(cuts), 0)                              AS cuts,
            COALESCE(SUM(COALESCE(cutting, 0) + COALESCE(hemming, 0)), 0)
                                                                AS cutting_hemming_bdl,
            COALESCE(SUM(heracle), 0)                           AS heracle_bdl,
            COALESCE(SUM(branding), 0)                          AS branding,
            COALESCE(SUM(hand_sewer), 0)                        AS h_sewer_bdl,
            COALESCE(SUM(bales), 0)                             AS bales_production,
            COALESCE(SUM(issue_bales), 0)                       AS bales_issue
        FROM tbl_daily_finishing
        WHERE tran_date BETWEEN :from_date AND :to_date
        GROUP BY tran_date
        ORDER BY tran_date
    """
    return text(sql)
