-- vw_hands_report : "Hands Report" grid (per the SJM paper form), one row per
-- (tran_date, branch, designation/particular). Columns pivot Shift x Shed x Metric:
--   Shifts   : A, B1, B2, C   (B1/B2 are the two spells of the B shift)
--   Sheds    : Old Shed (os) / New Shed (ns)   -> mechine_code_master.shed_type / daily_attendance.shed_type
--   Metrics  : mh_* = machine count (M/H)  ,  hands_* = actual hands = SUM(working_hours)/8
--
-- Sources (same underlying tables vw_man_machine reads):
--   tbl_daily_summ_mechine_data + mechine_code_master  -> machines (M/H), split by shed via mc.shed_type
--   daily_attendance                                   -> hands, split by shed via da.shed_type
-- Only ACTIVE machines are counted (mechine_code_master.is_active = 1); inactive machine
-- codes (incl. legacy rows with no designation link) are excluded from M/H.
--
-- Spell -> column folding for HANDS (per SJM rule "B1 and B2 mean B shift"):
--   A  = A + A1 + A2 + GS
--   B1 = B1 + B      (a full-B worker is counted in both halves)
--   B2 = B2 + B
--   C  = C + C1
-- Machines already carry explicit spell_b1 / spell_b2 columns, so no folding is
-- needed for M/H (mh_a = shift_a, mh_b1 = spell_b1, mh_b2 = spell_b2, mh_c = shift_c/spell_c).
--
-- total_hands is the honest actual head-count (each attendance row once, no B double-count).
--
-- Row spine = EVERY active designation for the branch (designation_mst.active=1) crossed with
-- each date that has any data, so all particulars appear even with 0 hands/machines (blank cells).

CREATE OR REPLACE VIEW `vw_hands_report` AS
WITH machines AS (
    SELECT
        t.tran_date,
        t.branch_id,
        mc.desig_id AS designation_id,
        SUM(CASE WHEN mc.shed_type = 'Old Shed' THEN t.shift_a  ELSE 0 END)                     AS mh_a_os,
        SUM(CASE WHEN mc.shed_type = 'New Shed' THEN t.shift_a  ELSE 0 END)                     AS mh_a_ns,
        SUM(CASE WHEN mc.shed_type = 'Old Shed' THEN t.spell_b1 ELSE 0 END)                     AS mh_b1_os,
        SUM(CASE WHEN mc.shed_type = 'New Shed' THEN t.spell_b1 ELSE 0 END)                     AS mh_b1_ns,
        SUM(CASE WHEN mc.shed_type = 'Old Shed' THEN t.spell_b2 ELSE 0 END)                     AS mh_b2_os,
        SUM(CASE WHEN mc.shed_type = 'New Shed' THEN t.spell_b2 ELSE 0 END)                     AS mh_b2_ns,
        SUM(CASE WHEN mc.shed_type = 'Old Shed' THEN COALESCE(t.shift_c, t.spell_c) ELSE 0 END) AS mh_c_os,
        SUM(CASE WHEN mc.shed_type = 'New Shed' THEN COALESCE(t.shift_c, t.spell_c) ELSE 0 END) AS mh_c_ns
    FROM tbl_daily_summ_mechine_data t
    JOIN mechine_code_master mc ON mc.mc_code_id = t.mc_code_id
    WHERE COALESCE(t.is_active, 1) = 1
      AND mc.is_active = 1
      AND mc.desig_id IS NOT NULL
    GROUP BY t.tran_date, t.branch_id, mc.desig_id
),
hands AS (
    SELECT
        da.attendance_date        AS tran_date,
        da.branch_id,
        da.worked_designation_id  AS designation_id,
        SUM(CASE WHEN da.shed_type = 'Old Shed' AND da.spell IN ('A','A1','A2','GS') THEN da.working_hours ELSE 0 END) / 8 AS hands_a_os,
        SUM(CASE WHEN da.shed_type = 'New Shed' AND da.spell IN ('A','A1','A2','GS') THEN da.working_hours ELSE 0 END) / 8 AS hands_a_ns,
        SUM(CASE WHEN da.shed_type = 'Old Shed' AND da.spell IN ('B','B1')          THEN da.working_hours ELSE 0 END) / 8 AS hands_b1_os,
        SUM(CASE WHEN da.shed_type = 'New Shed' AND da.spell IN ('B','B1')          THEN da.working_hours ELSE 0 END) / 8 AS hands_b1_ns,
        SUM(CASE WHEN da.shed_type = 'Old Shed' AND da.spell IN ('B','B2')          THEN da.working_hours ELSE 0 END) / 8 AS hands_b2_os,
        SUM(CASE WHEN da.shed_type = 'New Shed' AND da.spell IN ('B','B2')          THEN da.working_hours ELSE 0 END) / 8 AS hands_b2_ns,
        SUM(CASE WHEN da.shed_type = 'Old Shed' AND da.spell IN ('C','C1')          THEN da.working_hours ELSE 0 END) / 8 AS hands_c_os,
        SUM(CASE WHEN da.shed_type = 'New Shed' AND da.spell IN ('C','C1')          THEN da.working_hours ELSE 0 END) / 8 AS hands_c_ns,
        SUM(CASE WHEN da.shed_type = 'Old Shed' THEN da.working_hours ELSE 0 END) / 8 AS hands_total_os,
        SUM(CASE WHEN da.shed_type = 'New Shed' THEN da.working_hours ELSE 0 END) / 8 AS hands_total_ns
    FROM daily_attendance da
    WHERE da.is_active = 1
    GROUP BY da.attendance_date, da.branch_id, da.worked_designation_id
),
universe AS (
    -- every active designation for the branch, for each date that has any data
    SELECT dt.tran_date, dt.branch_id, dg.designation_id
    FROM (
        SELECT DISTINCT attendance_date AS tran_date, branch_id
        FROM daily_attendance WHERE is_active = 1
        UNION
        SELECT DISTINCT tran_date, branch_id
        FROM tbl_daily_summ_mechine_data WHERE COALESCE(is_active, 1) = 1
    ) dt
    JOIN designation_mst dg ON dg.branch_id = dt.branch_id AND dg.active = 1
)
SELECT
    u.tran_date,
    u.branch_id,
    d.dept_id,
    dept.dept_desc,
    dept.dept_code,
    dept.order_id                       AS dept_order,
    u.designation_id,
    d.desig                             AS particular,
    d.desig_code,
    ord.row_order,
    ROUND(COALESCE(m.mh_a_os, 0),  2)   AS mh_a_os,   ROUND(COALESCE(h.hands_a_os, 0),  2) AS hands_a_os,
    ROUND(COALESCE(m.mh_a_ns, 0),  2)   AS mh_a_ns,   ROUND(COALESCE(h.hands_a_ns, 0),  2) AS hands_a_ns,
    ROUND(COALESCE(m.mh_b1_os, 0), 2)   AS mh_b1_os,  ROUND(COALESCE(h.hands_b1_os, 0), 2) AS hands_b1_os,
    ROUND(COALESCE(m.mh_b1_ns, 0), 2)   AS mh_b1_ns,  ROUND(COALESCE(h.hands_b1_ns, 0), 2) AS hands_b1_ns,
    ROUND(COALESCE(m.mh_b2_os, 0), 2)   AS mh_b2_os,  ROUND(COALESCE(h.hands_b2_os, 0), 2) AS hands_b2_os,
    ROUND(COALESCE(m.mh_b2_ns, 0), 2)   AS mh_b2_ns,  ROUND(COALESCE(h.hands_b2_ns, 0), 2) AS hands_b2_ns,
    ROUND(COALESCE(m.mh_c_os, 0),  2)   AS mh_c_os,   ROUND(COALESCE(h.hands_c_os, 0),  2) AS hands_c_os,
    ROUND(COALESCE(m.mh_c_ns, 0),  2)   AS mh_c_ns,   ROUND(COALESCE(h.hands_c_ns, 0),  2) AS hands_c_ns,
    ROUND(COALESCE(h.hands_total_os, 0) + COALESCE(h.hands_total_ns, 0), 2) AS total_hands
FROM universe u
LEFT JOIN machines m ON m.tran_date = u.tran_date AND m.branch_id = u.branch_id AND m.designation_id = u.designation_id
LEFT JOIN hands    h ON h.tran_date = u.tran_date AND h.branch_id = u.branch_id AND h.designation_id = u.designation_id
LEFT JOIN designation_mst d    ON d.designation_id = u.designation_id
LEFT JOIN dept_mst        dept ON dept.dept_id      = d.dept_id
LEFT JOIN (
    SELECT desig_id, MIN(order_no) AS row_order
    FROM mechine_code_master
    WHERE desig_id IS NOT NULL AND is_active = 1
    GROUP BY desig_id
) ord ON ord.desig_id = u.designation_id;

-- Usage: SELECT * FROM vw_hands_report
--        WHERE tran_date = :d AND branch_id = :b
--        ORDER BY dept_order, row_order, particular;
