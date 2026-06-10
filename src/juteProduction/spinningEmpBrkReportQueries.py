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
    select verbt.report_date,verbt.spell_id,verbt.shift_name,verbt.emp_code,verbt.emp_name,verbt.frame_no,verbt.count,
whours_hh_mm power_min,verbt.loss_d_hh_mm loss_d,verbt.loss_m_hh_mm loss_m,verbt.loss_e_hh_mm loss_e,verbt.loss_i_hh_mm loss_i,
verbt.loss_idle_hh_mm loss_idle,verbt.tstop_hh_mm total_loss,verbt.totrun_hh_mm actual_run,  verbt.mcrunmins_hh_mm As_per_VVfd,
verbt.machine_doff,verbt.doff_wt, verbt.rpm,verbt.eff_100,verbt.actual_eff   
from view_emp_run_brk_trans verbt 
WHERE verbt.doff_date   BETWEEN :from_date AND :to_date
          AND (:shift_id IS NULL OR verbt.spell_id = :shift_id)
        ORDER BY doff_date, spell_id, frame_no          
"""
    
    return text(sql)
