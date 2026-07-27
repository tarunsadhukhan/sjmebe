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
    """One row per (date, shift, frame, employee, quality).

    run_eff comes straight from the view (doff_wt / run100 * 100, i.e. efficiency
    against actual running minutes). The 15-day columns are production-weighted
    running efficiency (sum doff_wt / sum run100) over each row's own window
    [doff_date - 15 days, doff_date] — per employee and per frame.
    """
    sql = """
with emp_daily as (
    select doff_date, emp_code,
           sum(if(run100 > 0, doff_wt, 0)) wt,
           sum(if(run100 > 0, run100, 0)) p100
    from view_emp_run_brk_trans
    where doff_date between date_sub(:from_date, interval 15 day) and :to_date
      and emp_code is not null
    group by doff_date, emp_code
),
frame_daily as (
    select doff_date, frame_no,
           sum(if(run100 > 0, doff_wt, 0)) wt,
           sum(if(run100 > 0, run100, 0)) p100
    from view_emp_run_brk_trans
    where doff_date between date_sub(:from_date, interval 15 day) and :to_date
    group by doff_date, frame_no
)
select verbt.report_date,verbt.spell_id,verbt.shift_name,verbt.emp_code,verbt.emp_name,verbt.frame_no,verbt.count,
whours_hh_mm power_min,verbt.loss_d_hh_mm loss_d,verbt.loss_m_hh_mm loss_m,verbt.loss_e_hh_mm loss_e,verbt.loss_i_hh_mm loss_i,
verbt.loss_idle_hh_mm loss_idle,verbt.tstop_hh_mm total_loss,verbt.totrun_hh_mm actual_run,  verbt.mcrunmins_hh_mm As_per_VVfd,
verbt.machine_doff,verbt.doff_wt, verbt.rpm,verbt.eff_100,verbt.actual_eff,verbt.run_eff,
e15.eff emp_eff_15d, f15.eff frame_eff_15d
from view_emp_run_brk_trans verbt
left join (
    select t.doff_date, t.emp_code,
           round(sum(w.wt) / nullif(sum(w.p100), 0) * 100, 2) eff
    from emp_daily t
    join emp_daily w
      on w.emp_code = t.emp_code
     and w.doff_date between date_sub(t.doff_date, interval 15 day) and t.doff_date
    where t.doff_date between :from_date and :to_date
    group by t.doff_date, t.emp_code
) e15 on e15.emp_code = verbt.emp_code and e15.doff_date = verbt.doff_date
left join (
    select t.doff_date, t.frame_no,
           round(sum(w.wt) / nullif(sum(w.p100), 0) * 100, 2) eff
    from frame_daily t
    join frame_daily w
      on w.frame_no = t.frame_no
     and w.doff_date between date_sub(t.doff_date, interval 15 day) and t.doff_date
    where t.doff_date between :from_date and :to_date
    group by t.doff_date, t.frame_no
) f15 on f15.frame_no = verbt.frame_no and f15.doff_date = verbt.doff_date
WHERE verbt.doff_date   BETWEEN :from_date AND :to_date
          AND (:shift_id IS NULL OR verbt.spell_id = :shift_id)
        ORDER BY verbt.doff_date, FIELD(verbt.shift_name, 'A', 'B1', 'B2', 'C'), verbt.frame_no
"""

    return text(sql)
