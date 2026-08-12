"""
Jute Production - Assorting Report Queries.

Source:
  - assorting_entry       one row per selector-trolly weighment:
                          entry_date, shed_type, branch_id, mc_id,
                          selector_id, quality_id, trolly_id, trolly_no,
                          gross_wt, tare_wt, net_wt
  - machine_mst           machine_name (machine_id = mc_id)
  - tbl_selector_mst      selector_name
  - jute_quality_mst      jute_quality (jute_qlty_id = quality_id)
  - trolly_mst            trolly_name fallback when trolly_no is blank

Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
"""

from sqlalchemy import text


def get_assorting_entries_query():
    """One row per assorting entry in [:from_date, :to_date].

    branch filter also passes NULL-branch rows (legacy data predates the
    branch_id column).
    """
    sql = """
        SELECT
            DATE_FORMAT(s.entry_date, '%d-%m-%Y')  AS report_date,
            s.shed_type                            AS shed_type,
            s.mc_id                                AS mc_id,
            mm.machine_name                        AS mc_name,
            s.selector_id                          AS selector_id,
            sm.selector_name                       AS selector_name,
            s.quality_id                           AS quality_id,
            COALESCE(jqm.jute_quality,
                     CONCAT('Quality #', s.quality_id)) AS quality_name,
            COALESCE(NULLIF(s.trolly_no, ''), tm.trolly_name) AS trolly_no,
            COALESCE(s.gross_wt, 0)                AS gross_wt,
            COALESCE(s.tare_wt, 0)                 AS tare_wt,
            COALESCE(s.net_wt, 0)                  AS net_wt
        FROM assorting_entry s
        LEFT JOIN machine_mst mm       ON mm.machine_id = s.mc_id
        LEFT JOIN tbl_selector_mst sm  ON sm.tbl_selector_mst_id = s.selector_id
        LEFT JOIN jute_quality_mst jqm ON jqm.jute_qlty_id = s.quality_id
        LEFT JOIN trolly_mst tm        ON tm.trolly_id = s.trolly_id
        WHERE s.entry_date BETWEEN :from_date AND :to_date
          AND (s.branch_id = :branch_id OR s.branch_id IS NULL)
        ORDER BY s.entry_date, sm.selector_name, s.id
    """
    return text(sql)
