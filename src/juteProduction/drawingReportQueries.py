"""
Jute Production - Drawing Report Queries.

Source tables:
  tbl_daily_drawing  (one row per date+spell+machine)
    - tran_date         report date
    - spell_id          shift / spell
    - mc_id             FK to machine_mst.machine_id
    - opening_meter     opening meter reading
    - closing_meter     closing meter reading
    - difference        closing - opening (meters drawn)
    - const_meter       rated meters (for eff %)
    - running_hours     working hours
    - branch_id         scoping

  tbl_drawing_mst    (drawing machine master)
    - mc_id, short_name, shed_type, drg_type, const_meter, branch_id

Machine name is resolved via machine_mst.machine_name.

Drawing has no inventory tracking — to keep response shape parity with the
spreader endpoints, opening/issue/closing are returned as 0 and "production"
carries SUM(unit) (meters drawn).
"""

from sqlalchemy import text


def get_drawing_summary_query():
    """
    Date-wise drawing summary.

    For each date in [from_date, to_date] with at least one entry, returns:
      - opening    : 0 (no inventory tracking on drawing)
      - production : SUM(difference) on that date
      - issue      : 0
      - closing    : 0

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            DATE_FORMAT(d.date, '%d-%m-%Y') AS report_date,
            0 AS opening,
            d.prod AS production,
            0 AS issue,
            0 AS closing
        FROM (
            SELECT
                s.tran_date AS date,
                COALESCE(SUM(s.difference), 0) AS prod
            FROM tbl_daily_drawing s
            WHERE s.branch_id = :branch_id
              AND s.tran_date BETWEEN :from_date AND :to_date
            GROUP BY s.tran_date
        ) d
        ORDER BY d.date
    """
    return text(sql)


def get_drawing_date_production_query():
    """
    Date + machine-wise drawing production.

    Returns one row per (date, mc_id) with:
      - opening    : 0
      - production : SUM(difference)
      - issue      : 0
      - closing    : 0
      - eff        : SUM(difference) / SUM(const_meter) * 100

    Frontend groups by date and appends a TOTAL row at the end of each date
    group.

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            DATE_FORMAT(s.tran_date, '%d-%m-%Y') AS report_date,
            s.mc_id AS quality_id,
            COALESCE(mm.machine_name, CONCAT('Machine #', s.mc_id)) AS quality_name,
            0 AS opening,
            COALESCE(SUM(s.difference), 0) AS production,
            0 AS issue,
            0 AS closing,
            COALESCE(ROUND(SUM(s.difference) / NULLIF(SUM(s.const_meter), 0) * 100, 2), 0) AS eff
        FROM tbl_daily_drawing s
        LEFT JOIN machine_mst mm ON mm.machine_id = s.mc_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date BETWEEN :from_date AND :to_date
          AND s.mc_id IS NOT NULL
        GROUP BY s.tran_date, s.mc_id, mm.machine_name
        ORDER BY s.tran_date, quality_name
    """
    return text(sql)


def get_drawing_date_issue_query():
    """
    Date + machine-wise output rows for the matrix view.

    Drawing has no issue concept — returns SUM(difference) as "issue" so the
    frontend pivot renders meaningful date x machine output.

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            DATE_FORMAT(s.tran_date, '%d-%m-%Y') AS report_date,
            s.mc_id AS quality_id,
            COALESCE(mm.machine_name, CONCAT('Machine #', s.mc_id)) AS quality_name,
            COALESCE(SUM(s.difference), 0) AS issue
        FROM tbl_daily_drawing s
        LEFT JOIN machine_mst mm ON mm.machine_id = s.mc_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date BETWEEN :from_date AND :to_date
          AND s.mc_id IS NOT NULL
        GROUP BY s.tran_date, s.mc_id, mm.machine_name
        ORDER BY s.tran_date, quality_name
    """
    return text(sql)


def get_drawing_shift_matrix_query():
    """
    Machine x shift matrix over the date range.

    Returns one row per (mc_id, spell_id) with:
      - op    : MIN(opening_meter)  — earliest opening reading in the range
      - cl    : MAX(closing_meter)  — latest closing reading in the range
      - unit  : SUM(unit)           — total meters drawn
      - eff   : AVG(eff)            — average efficiency %

    Frontend pivots these into shift A / B / C columns per machine, plus an
    Overall group that sums units across shifts.

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
                 SELECT
            s.mc_id AS mc_id,m.shed_type,m.drg_type,
            COALESCE(mm.machine_name , CONCAT('Machine #', s.mc_id)) AS mc_short_name,
            s.spell_id AS spell_id,
            COALESCE(sp.spell_name, CONCAT('Shift ', s.spell_id)) AS spell_name,
            COALESCE(MIN(s.opening_meter), 0) AS op,
            COALESCE(MAX(s.closing_meter), 0) AS cl,
            COALESCE(SUM(s.difference ), 0) AS unit,
            COALESCE(round(s.difference/m.const_meter*100,2)  , 0) AS eff
        FROM tbl_daily_drawing s
        left join machine_mst mm on mm.machine_id =s.mc_id 
        LEFT JOIN tbl_drawing_mst m ON m.mc_id = s.mc_id
        LEFT JOIN spell_mst sp ON sp.spell_id = s.spell_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date  BETWEEN :from_date AND :to_date
          AND s.mc_id IS NOT NULL
        GROUP BY s.mc_id, mm.machine_name , s.spell_id, sp.spell_name,m.shed_type ,m.drg_type 
        ORDER BY shed_type,drg_type,mc_short_name, s.spell_id

    """
    return text(sql)


def get_drawing_quality_details_query():
    """
    Per-machine totals over the date range.

    Returns one row per machine with:
      - total_production : SUM(difference)
      - total_issue      : 0 (no issue concept)
      - balance          : total_production

    Parameters: :branch_id (int), :from_date, :to_date ('YYYY-MM-DD')
    """
    sql = """
        SELECT
            s.mc_id AS quality_id,
            COALESCE(mm.machine_name, CONCAT('Machine #', s.mc_id)) AS quality_name,
            COALESCE(SUM(s.difference), 0) AS total_production,
            0 AS total_issue,
            COALESCE(SUM(s.difference), 0) AS balance
        FROM tbl_daily_drawing s
        LEFT JOIN machine_mst mm ON mm.machine_id = s.mc_id
        WHERE s.branch_id = :branch_id
          AND s.tran_date BETWEEN :from_date AND :to_date
          AND s.mc_id IS NOT NULL
        GROUP BY s.mc_id, mm.machine_name
        ORDER BY quality_name
    """
    return text(sql)
