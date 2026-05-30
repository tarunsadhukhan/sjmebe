"""
Jute Production - Spinning Employee/Frame Break-up Efficiency Report query.

Backs the frontend page at
    /dashboardportal/productionReports/spinningempbrkReports

Flat detail listing (one row per date / shift / frame / employee), matching the
"Spinning Efficiency" (Spg_Eff) printout:

    Date | Shift | Emp Id | Emp Name | Frame No | Count | Power Min |
    Loss Min [D M E I] | Total Loss | Actual Run | Machine Doff | Doff Wt |
    RPM | Effcy 100% | Actual Effcy

Sources:
    daily_doff_tbl              doff weight (SUM net_weight) + doff count per
                                (date, shift, machine, employee, quality)
    daily_doff_frames_winding   spinner (eb_id) + quality_id for the frame
    tbl_daily_vvfd_transaction  per-frame loss minutes (doff/elec/mech/oth)
    shift_mst                   shift name + working_hours (Power Min = *60)
    machine_mst                 frame / machine name
    frame_details_mst           speed (RPM) + no_of_spindle
    spinning_quality_mst        std_count (Count) + tpi
    hrms_ed_official_details    emp_code  ("Employee's I'd")
    hrms_ed_personal_details    emp_name

Computed columns:
    total_loss = loss_d + loss_m + loss_e + loss_i
    actual_run = (working_hours*60) - total_loss        (netmins)
    eff_100    = (speed*std_count*no_of_spindle*netmins)/(tpi*14400*36*2.2046)
    actual_eff = weight / eff_100 * 100

Parameters:
    :branch_id   int    (passed for parity; not referenced by this query)
    :from_date   'YYYY-MM-DD'
    :to_date     'YYYY-MM-DD'
    :shift_id    int | None   (NULL = all shifts; else filter pds.shift_id)
"""

from sqlalchemy import text


def get_spinning_emp_brk_detail_query():
    """One row per (date, shift, frame, employee, quality)."""
    sql = """
        SELECT
            DATE_FORMAT(pds.doff_date, '%d-%m-%Y')                     AS report_date,
            pds.shift_id                                              AS spell_id,
            pds.shift_name                                            AS shift_name,
            heod.emp_code                                             AS emp_code,
            CASE
                WHEN hepd.eb_id IS NULL THEN NULL
                ELSE CONCAT(
                    hepd.first_name,
                    IFNULL(hepd.middle_name, ''),
                    IFNULL(hepd.last_name, '')
                )
            END                                                       AS emp_name,
            pds.machine_name                                         AS frame_no,
            pds.std_count                                            AS count,
            pds.working_hours                                        AS power_min,
            pds.loss_min_doff                                        AS loss_d,
            pds.loss_min_mech                                        AS loss_m,
            pds.loss_min_elec                                        AS loss_e,
            pds.loss_min_oth                                         AS loss_i,
            (COALESCE(pds.loss_min_doff, 0) + COALESCE(pds.loss_min_mech, 0)
                + COALESCE(pds.loss_min_elec, 0) + COALESCE(pds.loss_min_oth, 0)) AS total_loss,
            pds.netmins                                             AS actual_run,
            pds.noofdoff                                            AS machine_doff,
            ROUND(pds.weight, 2)                                    AS doff_wt,
            pds.speed                                              AS rpm,
            ROUND(
                (pds.speed * pds.std_count * pds.no_of_spindle * pds.netmins)
                / (pds.tpi * 14400 * 36 * 2.2046)
            , 0)                                                    AS eff_100,
            ROUND(
                pds.weight
                / ((pds.speed * pds.std_count * pds.no_of_spindle * pds.netmins)
                    / (pds.tpi * 14400 * 36 * 2.2046)) * 100
            , 2)                                                    AS actual_eff
        FROM (
            SELECT
                pd.*,
                sfm.shift_name,
                mm.machine_name,
                fdm.speed,
                sqm.std_count,
                vvfd.mc_runs_time,
                vvfd.loss_min_doff,
                vvfd.loss_min_elec,
                vvfd.loss_min_mech,
                vvfd.loss_min_oth,
                fdm.speed * .12                                       AS eff100,
                pd.weight / (fdm.speed * .12) * 100                   AS eff,
                sfm.working_hours * 60                                AS working_hours,
                (sfm.working_hours * 60)
                    - (loss_min_doff + loss_min_elec + loss_min_mech + loss_min_oth) AS netmins,
                tpi,
                fdm.no_of_spindle
            FROM (
                SELECT
                    ddt.doff_date,
                    sm.shift_id,
                    ddt.mc_id,
                    ddfw.eb_id,
                    ddfw.quality_id,
                    COUNT(*)             AS noofdoff,
                    SUM(ddt.net_weight)  AS weight
                FROM daily_doff_tbl ddt
                LEFT JOIN daily_doff_frames_winding ddfw
                       ON ddt.doff_date = ddfw.tran_date
                      AND ddt.spell     = ddfw.spell
                      AND ddt.mc_id     = ddfw.mc_eb_id
                LEFT JOIN spell_mst sm ON sm.spell_id = ddt.spell
                WHERE ddt.doff_date BETWEEN :from_date AND :to_date
                GROUP BY ddt.doff_date, sm.shift_id, ddt.mc_id, ddfw.eb_id, ddfw.quality_id
            ) pd
            LEFT JOIN (
                SELECT tdvt.*, sm.shift_id
                FROM tbl_daily_vvfd_transaction tdvt
                LEFT JOIN spell_mst sm ON tdvt.spell_id = sm.spell_id
            ) vvfd
                   ON pd.doff_date = vvfd.tran_date
                  AND pd.shift_id  = vvfd.shift_id
                  AND pd.mc_id     = vvfd.mc_id
            LEFT JOIN shift_mst sfm ON sfm.shift_id = pd.shift_id
            LEFT JOIN machine_mst mm ON mm.machine_id = pd.mc_id
            LEFT JOIN frame_details_mst fdm ON fdm.mc_id = pd.mc_id
            LEFT JOIN spinning_quality_mst sqm ON sqm.spg_quality_mst_id = pd.quality_id
        ) pds
        LEFT JOIN hrms_ed_official_details heod
               ON pds.eb_id = heod.eb_id AND heod.active = 1
        LEFT JOIN hrms_ed_personal_details hepd
               ON pds.eb_id = hepd.eb_id
        WHERE pds.doff_date BETWEEN :from_date AND :to_date
          AND (:shift_id IS NULL OR pds.shift_id = :shift_id)
        ORDER BY pds.doff_date, pds.shift_id, pds.machine_name
    """
    return text(sql)
