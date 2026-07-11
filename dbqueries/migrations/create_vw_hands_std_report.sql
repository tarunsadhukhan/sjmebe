-- vw_hands_std_report : "Actual vs Std Hands" grid, one row per (tran_date, branch, designation).
-- Columns pivot Shift {A, B, C} x Metric {act (actual hands), std (standard hands)}.
--   act_x = actual hands = SUM(working_hours)/8, folded to shift (A=A/A1/A2/GS, B=B/B1/B2, C=C/C1),
--           each attendance row counted ONCE (no B1/B2 double count — this is shift level, not spell).
--   std_x = standard hands:
--             FIXED    designations -> designation_norms_mst.shift_a/b/c (fixed_variable='F')
--             VARIABLE designations -> SUM over active machines of machines_in_shift / no_of_mcs * no_of_hands
--                                      (tbl_daily_summ_mechine_data x mc_occu_link_mst), summed across sheds.
-- Excess/Short (computed in the FE) = act - std.
--
-- NB: this deliberately does NOT read vw_man_machine — that view inflates actual hands via a
-- non-branch-scoped spell_mst join (spell names repeat per branch). Actual is recomputed here.
--
-- Row spine = every active designation for the branch (designation_mst.active=1) x each date with data,
-- so all particulars appear even with 0 act/std (blank cells). Order by dept_code, desig_code in queries.

CREATE OR REPLACE VIEW `vw_hands_std_report` AS
WITH act AS (
    SELECT
        da.attendance_date       AS tran_date,
        da.branch_id,
        da.worked_designation_id AS designation_id,
        SUM(CASE WHEN da.spell IN ('A','A1','A2','GS') THEN da.working_hours ELSE 0 END) / 8 AS act_a,
        SUM(CASE WHEN da.spell IN ('B','B1','B2')      THEN da.working_hours ELSE 0 END) / 8 AS act_b,
        SUM(CASE WHEN da.spell IN ('C','C1')           THEN da.working_hours ELSE 0 END) / 8 AS act_c
    FROM daily_attendance da
    WHERE da.is_active = 1
    GROUP BY da.attendance_date, da.branch_id, da.worked_designation_id
),
std_f AS (   -- fixed designations: norm is date-independent
    SELECT desig_id AS designation_id, shift_a AS std_a, shift_b AS std_b, shift_c AS std_c
    FROM designation_norms_mst
    WHERE COALESCE(active, 1) = 1 AND fixed_variable = 'F'
),
std_v AS (   -- variable designations: machine-derived, per date, summed across all sheds/machines
    SELECT
        t.tran_date,
        t.branch_id,
        mc.desig_id AS designation_id,
        SUM(t.shift_a                     / NULLIF(molm.no_of_mcs, 0) * molm.no_of_hands) AS std_a,
        SUM(t.shift_b                     / NULLIF(molm.no_of_mcs, 0) * molm.no_of_hands) AS std_b,
        SUM(COALESCE(t.shift_c, t.spell_c)/ NULLIF(molm.no_of_mcs, 0) * molm.no_of_hands) AS std_c
    FROM tbl_daily_summ_mechine_data t
    JOIN mechine_code_master mc   ON mc.mc_code_id = t.mc_code_id
                                 AND mc.is_active = 1 AND mc.desig_id IS NOT NULL
    JOIN mc_occu_link_mst    molm ON molm.mc_id = t.mc_code_id AND COALESCE(molm.active, 1) = 1
    WHERE COALESCE(t.is_active, 1) = 1
    GROUP BY t.tran_date, t.branch_id, mc.desig_id
),
universe AS (
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
    dg.dept_id,
    dept.dept_desc,
    dept.dept_code,
    u.designation_id,
    dg.desig       AS particular,
    dg.desig_code,
    ROUND(COALESCE(a.act_a, 0), 2)                               AS act_a,
    ROUND(COALESCE(sf.std_a, sv.std_a, 0), 2)                    AS std_a,
    ROUND(COALESCE(a.act_b, 0), 2)                               AS act_b,
    ROUND(COALESCE(sf.std_b, sv.std_b, 0), 2)                    AS std_b,
    ROUND(COALESCE(a.act_c, 0), 2)                               AS act_c,
    ROUND(COALESCE(sf.std_c, sv.std_c, 0), 2)                    AS std_c
FROM universe u
JOIN designation_mst dg ON dg.designation_id = u.designation_id
LEFT JOIN dept_mst dept  ON dept.dept_id = dg.dept_id
LEFT JOIN act   a  ON a.tran_date  = u.tran_date AND a.branch_id  = u.branch_id AND a.designation_id  = u.designation_id
LEFT JOIN std_f sf ON sf.designation_id = u.designation_id
LEFT JOIN std_v sv ON sv.tran_date = u.tran_date AND sv.branch_id = u.branch_id AND sv.designation_id = u.designation_id;

-- Usage: SELECT * FROM vw_hands_std_report WHERE tran_date=:d AND branch_id=:b
--        ORDER BY CAST(dept_code AS UNSIGNED), desig_code IS NULL, CAST(desig_code AS UNSIGNED), particular;
