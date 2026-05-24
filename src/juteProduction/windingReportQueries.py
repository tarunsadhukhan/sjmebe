"""
Jute Production - Winding Report Queries.

Three report views are supported:
  1. /day-wise    Employee x Day production + total hours
  2. /fn-wise     Employee x Fortnight production + total hours
  3. /month-wise  Employee x Month production + total hours

Source:
  - daily_doff_frames_winding (spg_wdg='W', gross_weight>0)
      per (eb_id, tran_date, spell): net_weight = production,
      spellhrs (fixed 8) = total hours for that spell
  - hrms_ed_official_details   emp_code  (active=1)
  - hrms_ed_personal_details   first/middle/last name

Projection per row:
  emp_id      int        (eb_id)
  emp_code    string
  emp_name    string
  period_key  string     ('YYYY-MM-DD' for day, 'YYYY-MM-FN1/FN2' for
                          fortnight, 'YYYY-MM' for month)
  period_label string    display label (dd-mm-YYYY / FN1 MMM YYYY / MMM YYYY)
  production  numeric
  total_hours numeric

Parameters:
  :branch_id  int      (currently unused — table has no branch column;
                        add a filter if/when one is introduced)
  :from_date  'YYYY-MM-DD'
  :to_date    'YYYY-MM-DD'
"""

from sqlalchemy import text


# ---------------------------------------------------------------------------
# 1. Day-wise winding production per employee
# ---------------------------------------------------------------------------


def get_winding_day_wise_query():
    sql = """
        SELECT
            g.eb_id                                                AS emp_id,
            heod.emp_code                                          AS emp_code,
            CONCAT(
                hepd.first_name, ' ',
                COALESCE(hepd.middle_name, ''), ' ',
                COALESCE(hepd.last_name, '')
            )                                                      AS emp_name,
            DATE_FORMAT(g.tran_date, '%Y-%m-%d')                   AS period_key,
            DATE_FORMAT(g.tran_date, '%d-%m-%Y')                   AS period_label,
            ROUND(COALESCE(SUM(g.weight), 0), 2)                   AS production,
            COALESCE(SUM(g.spellhrs), 0)                           AS total_hours
        FROM (
            SELECT
                ddfw.eb_id,
                ddfw.tran_date,
                ddfw.spell,
                SUM(ddfw.net_weight) AS weight,
                8                    AS spellhrs
            FROM daily_doff_frames_winding ddfw
            WHERE ddfw.spg_wdg     = 'W'
              AND ddfw.gross_weight > 0
              AND ddfw.tran_date BETWEEN :from_date AND :to_date
            GROUP BY ddfw.eb_id, ddfw.tran_date, ddfw.spell
        ) g
        LEFT JOIN hrms_ed_official_details heod
               ON heod.eb_id = g.eb_id AND heod.active = 1
        LEFT JOIN hrms_ed_personal_details hepd
               ON hepd.eb_id = g.eb_id
        GROUP BY
            g.eb_id, heod.emp_code,
            hepd.first_name, hepd.middle_name, hepd.last_name,
            g.tran_date
        ORDER BY emp_code, g.tran_date
    """
    return text(sql)


# ---------------------------------------------------------------------------
# 2. Fortnight-wise winding production per employee
# ---------------------------------------------------------------------------


def get_winding_fn_wise_query():
    """
    Fortnight buckets: FN1 = days 1-15, FN2 = days 16-end of month.
    period_key = 'YYYY-MM-FN1' / 'YYYY-MM-FN2' (sortable).
    """
    sql = """
        SELECT
            g.eb_id                                                AS emp_id,
            heod.emp_code                                          AS emp_code,
            CONCAT(
                hepd.first_name, ' ',
                COALESCE(hepd.middle_name, ''), ' ',
                COALESCE(hepd.last_name, '')
            )                                                      AS emp_name,
            CONCAT(
                DATE_FORMAT(g.tran_date, '%Y-%m'),
                CASE WHEN DAY(g.tran_date) <= 15 THEN '-FN1' ELSE '-FN2' END
            )                                                      AS period_key,
            CONCAT(
                CASE WHEN DAY(g.tran_date) <= 15 THEN 'FN1 ' ELSE 'FN2 ' END,
                DATE_FORMAT(g.tran_date, '%b %Y')
            )                                                      AS period_label,
            ROUND(COALESCE(SUM(g.weight), 0), 2)                   AS production,
            COALESCE(SUM(g.spellhrs), 0)                           AS total_hours
        FROM (
            SELECT
                ddfw.eb_id,
                ddfw.tran_date,
                ddfw.spell,
                SUM(ddfw.net_weight) AS weight,
                8                    AS spellhrs
            FROM daily_doff_frames_winding ddfw
            WHERE ddfw.spg_wdg     = 'W'
              AND ddfw.gross_weight > 0
              AND ddfw.tran_date BETWEEN :from_date AND :to_date
            GROUP BY ddfw.eb_id, ddfw.tran_date, ddfw.spell
        ) g
        LEFT JOIN hrms_ed_official_details heod
               ON heod.eb_id = g.eb_id AND heod.active = 1
        LEFT JOIN hrms_ed_personal_details hepd
               ON hepd.eb_id = g.eb_id
        GROUP BY
            g.eb_id, heod.emp_code,
            hepd.first_name, hepd.middle_name, hepd.last_name,
            period_key, period_label
        ORDER BY emp_code, period_key
    """
    return text(sql)


# ---------------------------------------------------------------------------
# 3. Month-wise winding production per employee
# ---------------------------------------------------------------------------


def get_winding_daily_query():
    """
    One row per (date, quality, spell). Frontend pivots into shift columns:
      No of Winders per shift (A/B/C/Total), Production per shift (A/B/C/Total),
      and Avg Prod/8 Hrs (= total_prod / total_winders).

    Source: daily_doff_frames_winding rows where spg_wdg='W'.
      - winders = COUNT(DISTINCT eb_id) per (date, quality, spell)
      - production = SUM(net_weight)

    Quality display: spinning_type_mst + spinning_quality_mst (same masters
    used by the spinning report, since the winding rows reference the same
    quality_id column).
    """
    sql = """
        SELECT
            DATE_FORMAT(g.tran_date, '%d-%m-%Y')               AS report_date,
            g.quality_id                                       AS quality_id,
            g.quality_name                                     AS quality_name,
            sm.spell_id                                        AS spell_id,
            COALESCE(sm.spell_name, CONCAT('Shift ', g.spell)) AS spell_name,
            COALESCE(SUM(g.winders), 0)                        AS winders,
            ROUND(COALESCE(SUM(g.weight), 0), 2)               AS production
        FROM (
            SELECT
                ddfw.tran_date,
                ddfw.spell,
                ddfw.quality_id,
                CONCAT(
                    COALESCE(stm.spg_type_name, ''), ' ',
                    COALESCE(sqm.spg_quality, '')
                )                                    AS quality_name,
                SUM(ddfw.net_weight)                 AS weight,
                COUNT(DISTINCT ddfw.eb_id)           AS winders
            FROM daily_doff_frames_winding ddfw
            LEFT JOIN spinning_quality_mst sqm
                   ON sqm.spg_quality_mst_id = ddfw.quality_id
            LEFT JOIN spinning_type_mst stm
                   ON stm.spg_type_mst_id = sqm.spg_type_id
            WHERE ddfw.spg_wdg      = 'W'
              AND ddfw.gross_weight > 0
              AND ddfw.tran_date BETWEEN :from_date AND :to_date
            GROUP BY ddfw.tran_date, ddfw.spell, ddfw.quality_id, quality_name
        ) g
        LEFT JOIN spell_mst sm ON sm.spell_id = g.spell
        GROUP BY g.tran_date, sm.spell_id, sm.spell_name, g.quality_id, g.quality_name
        ORDER BY g.tran_date, g.quality_name, sm.spell_id
    """
    
    sql="""select  g.tran_date tdate,DATE_FORMAT(g.tran_date, '%d-%m-%Y')AS report_date,
        ddfw.quality_id quality_id,wqm.wng_quality quality_name,g.spell_id,sm.spell_name,
        g.cnt winders ,g.weight production
    from (
        select mc_eb_id eb_id,ddfw.tran_date,ddfw.spell AS spell_id,sum(ddfw.net_weight) weight,count(*) cnt from daily_doff_frames_winding ddfw
        where ddfw.spg_wdg ='W' and ddfw.gross_weight >0
                     AND ddfw.tran_date BETWEEN :from_date AND :to_date
        group by eb_id,ddfw.tran_date,ddfw.spell
        ) g
        left join  daily_doff_frames_winding ddfw
        on ddfw.tran_date =g.tran_date
                and ddfw.spell =g.spell_id
               and ddfw.mc_eb_id =g.eb_id
               and ddfw.spg_wdg ='W'
				and COALESCE(ddfw.gross_weight,0 )=0
        left join winding_quality_master wqm on wqm.wng_quality_mst_id =ddfw.quality_id
		left join spell_mst sm on sm.spell_id =g.spell_id"""
        
    return text(sql)


def get_winding_month_wise_query():
    sql = """
        SELECT
            g.eb_id                                                AS emp_id,
            heod.emp_code                                          AS emp_code,
            CONCAT(
                hepd.first_name, ' ',
                COALESCE(hepd.middle_name, ''), ' ',
                COALESCE(hepd.last_name, '')
            )                                                      AS emp_name,
            DATE_FORMAT(g.tran_date, '%Y-%m')                      AS period_key,
            DATE_FORMAT(g.tran_date, '%b %Y')                      AS period_label,
            ROUND(COALESCE(SUM(g.weight), 0), 2)                   AS production,
            COALESCE(SUM(g.spellhrs), 0)                           AS total_hours
        FROM (
            SELECT
                ddfw.eb_id,
                ddfw.tran_date,
                ddfw.spell,
                SUM(ddfw.net_weight) AS weight,
                8                    AS spellhrs
            FROM daily_doff_frames_winding ddfw
            WHERE ddfw.spg_wdg     = 'W'
              AND ddfw.gross_weight > 0
              AND ddfw.tran_date BETWEEN :from_date AND :to_date
            GROUP BY ddfw.eb_id, ddfw.tran_date, ddfw.spell
        ) g
        LEFT JOIN hrms_ed_official_details heod
               ON heod.eb_id = g.eb_id AND heod.active = 1
        LEFT JOIN hrms_ed_personal_details hepd
               ON hepd.eb_id = g.eb_id
        GROUP BY
            g.eb_id, heod.emp_code,
            hepd.first_name, hepd.middle_name, hepd.last_name,
            period_key, period_label
        ORDER BY emp_code, period_key
    """
    return text(sql)
