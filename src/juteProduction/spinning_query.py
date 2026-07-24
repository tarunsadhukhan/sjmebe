"""Raw SQL builders for the Spinning / Doff production entry feature (jute production module).

Mirrors drawing_query.py conventions: named binds, the ``:x IS NULL OR ...``
optional-filter idiom, and de-duplication left to the router where spell_code
fanout can occur. Reuses the mobile-app doff tables (daily_doff_tbl,
daily_doff_frames_winding) by raw SQL only — see SHARED BUILD SPEC for the exact
columns those tables expose.
"""

from sqlalchemy import text


# =============================================================================
# Setup / lookup builders
# =============================================================================


def get_spinning_machines_query():
    """Spinning-type machines for a company (identity only).

    Machine standards/config (bobbin weight, spindles, speed) live in the
    time-versioned jute_prod_spng_target_map and are resolved per-date by the
    caller (resolve_param); this query no longer joins any attribute table.
    The :co_id bind is kept for caller compatibility (machine scope is by type).
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            m.dept_id,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_spells_query():
    """Active spells with working hours from spell_mst (branch scoped via parent shift).

    Unlike the drawing variant this ALSO returns spell_id, because doff tables
    store spell_id (INT), not the spell_code string. Callers must de-duplicate by
    spell_code in Python (sls carries a duplicate A1 under a second branch's
    shift) keeping the first row per code.
    """
    return text(
        """
        SELECT sp.spell_id, sp.spell_code, sp.spell_name, sp.working_hours,
               sp.starting_time, sp.is_overnight, sp.shift_id
        FROM spell_mst sp
        INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id
        WHERE sp.status = 1
          AND sh.status = 1
          AND (:branch_id IS NULL OR sh.branch_id = :branch_id)
        ORDER BY sp.starting_time
        """
    )


def resolve_spell_id_query():
    """Resolve a spell_code string to its canonical spell_id (MIN dedupes branch fanout)."""
    return text(
        """
        SELECT MIN(spell_id) AS spell_id
        FROM spell_mst
        WHERE spell_code = :spell_code AND status = 1
        """
    )


def get_trollies_query():
    """Trolly master rows (branch + machine-type optional). Keep busket_weight
    column name; alias bucket_weight in the response.

    :machine_type_name NULL -> all rows (master list). When a stage name is
    passed it resolves to its machine_type_id and filters strictly, so untagged
    (NULL) trolleys are excluded from that stage's page.
    """
    return text(
        """
        SELECT
            t.trolly_id,
            t.trolly_name,
            t.trolly_weight,
            t.busket_weight AS bucket_weight,
            t.trolly_posting_code,
            t.branch_id,
            COALESCE(t.trolly_type, 'T') AS trolly_type,
            t.machine_type_id,
            mt.machine_type_name
        FROM trolly_mst t
        LEFT JOIN machine_type_mst mt ON mt.machine_type_id = t.machine_type_id AND mt.active = 1
        WHERE (:branch_id IS NULL OR t.branch_id = :branch_id)
          AND (:machine_type_name IS NULL OR mt.machine_type_name = :machine_type_name)
        ORDER BY t.trolly_name
        """
    )


def get_yarn_qualities_query():
    """Active yarn ITEMS (item_type_id=4) — the single yarn identity.

    A yarn IS an item (item_mst); its editable data lives on jute_yarn_mst. Returns
    item_id (the canonical key, was yarn_quality_id), item_code/item_name from
    item_mst, std_count from jute_yarn_mst.jute_yarn_count, and std_mr_pct (exposed
    for the Spinning SQC corrected-count calculation).

    Company scope lives on item_grp_mst.co_id (item_mst has no co_id by design), so
    the dropdown MUST filter ig.co_id = :co_id — otherwise items that share a code
    across companies (e.g. "13-SKWP" under both co 1 and co 9) appear duplicated.
    The :branch_id bind is kept for caller compatibility but unused — a yarn has no
    branch.
    """
    return text(
        """
        SELECT
            ym.item_id,
            im.item_code,
            im.item_name,
            ym.jute_yarn_count AS std_count,
            ym.std_mr_pct
        FROM jute_yarn_mst ym
        JOIN item_mst im ON im.item_id = ym.item_id
        JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        WHERE ig.item_type_id = 4
          AND ig.co_id = :co_id
          AND (:branch_id IS NULL OR :branch_id IS NOT NULL)
        ORDER BY im.item_name
        """
    )


# =============================================================================
# Doff entry builders
# =============================================================================


def get_doff_running_total_query():
    """Running net total and doff count for a machine within co/date/spell_id.

    Used to pre-fill the running total and next doff number. active IN (1, NULL)
    keeps legacy rows that pre-date the active flag.
    """
    return text(
        """
        SELECT
            COALESCE(SUM(net_weight), 0) AS total_net,
            COUNT(*) AS doff_count
        FROM daily_doff_tbl
        WHERE doff_date = :tran_date
          AND spell = :spell_id
          AND mc_id = :machine_id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_doff_entries_by_date_query():
    """Doff entries for the records grid (spell_id and machine optional).

    Yarn resolves to the doff row's own item_id when set, else falls back to the
    Frame -> Quality mapping (daily_doff_frames_winding, spg_wdg='S') for the same
    machine/spell/date. This lets the grid show the mapped yarn before the doff row
    is back-stamped. The frame-map join is pre-aggregated (one row per
    machine/spell/date via MAX) so duplicate active rows can't fan out the result.
    """
    return text(
        """
        SELECT
            dd.daily_doff_tbl_id,
            dd.branch_id,
            dd.doff_date,
            dd.spell AS spell_id,
            sp.spell_code,
            dd.mc_id,
            m.mech_code,
            m.machine_name,
            dd.trolly_id,
            t.trolly_name,
            COALESCE(dd.item_id, fm.item_id) AS item_id,
            im.item_code,
            im.item_name,
            dd.gross_weight,
            dd.tare_weight,
            dd.net_weight
        FROM daily_doff_tbl dd
        LEFT JOIN machine_mst m ON m.machine_id = dd.mc_id
        LEFT JOIN trolly_mst t ON t.trolly_id = dd.trolly_id
        LEFT JOIN (
            SELECT spell_code, MIN(spell_id) AS spell_id
            FROM spell_mst WHERE status = 1 GROUP BY spell_code
        ) sp ON sp.spell_id = dd.spell
        LEFT JOIN (
            SELECT mc_eb_id, spell_id, tran_date, MAX(item_id) AS item_id
            FROM daily_doff_frames_winding
            WHERE spg_wdg = 'S'
              AND item_id IS NOT NULL
              AND (active = 1 OR active IS NULL)
            GROUP BY mc_eb_id, spell_id, tran_date
        ) fm ON fm.mc_eb_id = dd.mc_id
            AND fm.spell_id = dd.spell
            AND fm.tran_date = dd.doff_date
        LEFT JOIN item_mst im ON im.item_id = COALESCE(dd.item_id, fm.item_id)
        WHERE dd.doff_date = :tran_date
          AND (dd.active = 1 OR dd.active IS NULL)
          AND (:spell_id IS NULL OR dd.spell = :spell_id)
          AND (:branch_id IS NULL OR dd.branch_id = :branch_id)
          AND (:machine_id IS NULL OR dd.mc_id = :machine_id)
        ORDER BY m.mech_code, dd.daily_doff_tbl_id
        """
    )


def dedup_doff_entries_query():
    """Dedup keep MAX(daily_doff_tbl_id) per machine within co/date/spell_id,
    deactivating the rest. Returns rowcount via .rowcount on execute."""
    return text(
        """
        UPDATE daily_doff_tbl dd
        INNER JOIN (
            SELECT mc_id, MAX(daily_doff_tbl_id) AS keep_id
            FROM daily_doff_tbl
            WHERE doff_date = :tran_date
              AND spell = :spell_id
              AND (active = 1 OR active IS NULL)
            GROUP BY mc_id
        ) k ON k.mc_id = dd.mc_id
        SET dd.active = 0
        WHERE dd.doff_date = :tran_date
          AND dd.spell = :spell_id
          AND (dd.active = 1 OR dd.active IS NULL)
          AND dd.daily_doff_tbl_id <> k.keep_id
        """
    )


# =============================================================================
# Frame-map (daily_doff_frames_winding, spg_wdg = 'S') builders
# =============================================================================


def get_frame_map_query():
    """All Spinning machines with today's SAVED mapping + the frame's most recent
    saved mapping (any spell) as an unsaved-draft suggestion.

    Join is on mc_eb_id = machine_id (mc_eb_id holds machine_id for spinning rows),
    today's tran_date, the resolved spell_id, and active.

    item_id/item_code/item_name      = today's SAVED mapping for this spell (NULL when
                                       nothing saved yet).
    prev_item_id/prev_item_name/prev_date = the frame's most recent saved S-mapping
                                       across ANY spell/date, EXCLUDING the current
                                       (tran_date, spell_id) cell (correlated subquery,
                                       one row per machine, latest tran_date then id).
                                       Surfaced so the client can prefill the dropdown
                                       and flag it unsaved until the operator clicks
                                       Save Map. Lets a never-mapped spell (e.g. a new
                                       B1) bootstrap from the latest A1 setup.
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.mech_code,
            m.machine_name,
            d.branch_id,
            f.daily_doff_frm_wdg_id,
            f.item_id,
            im.item_code,
            im.item_name,
            (
                SELECT p.item_id
                FROM daily_doff_frames_winding p
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_item_id,
            (
                SELECT pim.item_name
                FROM daily_doff_frames_winding p
                JOIN item_mst pim ON pim.item_id = p.item_id
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_item_name,
            (
                SELECT p.tran_date
                FROM daily_doff_frames_winding p
                WHERE p.mc_eb_id = m.machine_id
                  AND p.spg_wdg = 'S'
                  AND (p.active = 1 OR p.active IS NULL)
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.daily_doff_frm_wdg_id DESC
                LIMIT 1
            ) AS prev_date
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN daily_doff_frames_winding f
               ON f.mc_eb_id = m.machine_id
              AND f.spg_wdg = 'S'
              AND f.tran_date = :tran_date
              AND f.spell_id = :spell_id
              AND (f.active = 1 OR f.active IS NULL)
        LEFT JOIN item_mst im ON im.item_id = f.item_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_frame_map_active_row_query():
    """The active S-row id for one machine on a tran_date/spell_id (upsert lookup)."""
    return text(
        """
        SELECT daily_doff_frm_wdg_id
        FROM daily_doff_frames_winding
        WHERE spg_wdg = 'S'
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND mc_eb_id = :machine_id
          AND (active = 1 OR active IS NULL)
        ORDER BY daily_doff_frm_wdg_id DESC
        LIMIT 1
        """
    )


def update_frame_map_row_query():
    """Update an existing active S-row's quality mapping (stamps who/when)."""
    return text(
        """
        UPDATE daily_doff_frames_winding
        SET item_id = :item_id,
            updated_by = :updated_by,
            updated_date_time = NOW()
        WHERE daily_doff_frm_wdg_id = :id
        """
    )


def insert_frame_map_row_query():
    """Insert a fresh active S-row for a machine's quality mapping (stamps who/when)."""
    return text(
        """
        INSERT INTO daily_doff_frames_winding
            (tran_date, spell, spell_id, mc_eb_id, item_id,
             spg_wdg, branch_id, active, updated_by, updated_date_time)
        VALUES
            (:tran_date, :spell, :spell_id, :machine_id, :item_id,
             'S', :branch_id, 1, :updated_by, NOW())
        """
    )


def get_frame_map_last_updated_query():
    """The most recent save timestamp across a branch's active S-mapping rows.

    Surfaced in the Frame -> Quality grid so the operator can see when the branch's
    mapping was last touched. Branch-scoped (NULL branch_id = whole tenant)."""
    return text(
        """
        SELECT MAX(updated_date_time) AS last_updated
        FROM daily_doff_frames_winding
        WHERE spg_wdg = 'S'
          AND (active = 1 OR active IS NULL)
          AND (:branch_id IS NULL OR branch_id = :branch_id)
        """
    )


def backstamp_quality_query():
    """Back-stamp daily_doff_tbl.item_id from the S frame-map,
    joining on mc_id = mc_eb_id and the same spell_id and tran_date."""
    return text(
        """
        UPDATE daily_doff_tbl d
        INNER JOIN daily_doff_frames_winding f
                ON f.mc_eb_id = d.mc_id
               AND f.spg_wdg = 'S'
               AND f.spell_id = :spell_id
               AND f.tran_date = :tran_date
               AND (f.active = 1 OR f.active IS NULL)
        SET d.item_id = f.item_id
        WHERE d.doff_date = :tran_date
          AND d.spell = :spell_id
          AND (d.active = 1 OR d.active IS NULL)
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        """
    )


def operator_stamp_query():
    """Stamp daily_doff_tbl.eb_id from the on-machine operator's attendance.

    Joins daily_ebmc_attendance (by mc_id) to daily_attendance (by daily_atten_id)
    for the same date / spell NAME / branch, restricting to on-machine designations
    unless :ignore_on_machine = 1. Both the spell name and spell_id are bound:
    daily_attendance.spell holds the name string while daily_doff_tbl.spell holds
    the spell_id.
    """
    return text(
        """
        UPDATE daily_doff_tbl d
        INNER JOIN daily_ebmc_attendance dea
                ON dea.mc_id = d.mc_id
               AND dea.is_active = 1
        INNER JOIN daily_attendance da
                ON da.daily_atten_id = dea.daily_atten_id
               AND da.is_active = 1
               AND da.attendance_date = :tran_date
               AND da.spell = :spell_name
               AND (:branch_id IS NULL OR da.branch_id = :branch_id)
        LEFT JOIN designation_mst dm
                ON dm.designation_id = da.worked_designation_id
        SET d.eb_id = da.eb_id
        WHERE d.doff_date = :tran_date
          AND d.spell = :spell_id
          AND (d.active = 1 OR d.active IS NULL)
          AND (dm.on_machine = 'Yes' OR :ignore_on_machine = 1)
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        """
    )


# =============================================================================
# Planning-grid (jute_prod_spinning_daily) builders — per-frame-per-spell
# =============================================================================


def get_spinning_plan_driver_query():
    """Driver rows for the planning grid: active S-rows of daily_doff_frames_winding.

    Each row maps one machine to one yarn item for a (tran_date, spell_id). mc_eb_id
    holds machine_id for spg_wdg='S' rows. Joins surface the machine identity, the
    spell_code/working_hours (for shift bucket + minutes), the item_code/item_name,
    and the yarn's std_count (jute_yarn_mst.jute_yarn_count). Only rows with a
    non-null item_id participate (an unmapped frame has nothing to plan). spell_id
    filter is optional. Spindles are resolved per-date from jute_prod_spng_target_map
    by the caller (no longer joined here).
    """
    return text(
        """
        SELECT
            f.mc_eb_id AS machine_id,
            f.item_id,
            f.spell_id,
            m.mech_code,
            m.machine_name,
            d.branch_id,
            sp.spell_code,
            sp.working_hours,
            im.item_code,
            im.item_name,
            ym.jute_yarn_count AS std_count
        FROM daily_doff_frames_winding f
        INNER JOIN machine_mst m ON m.machine_id = f.mc_eb_id
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN (
            SELECT spell_id, spell_code, working_hours
            FROM spell_mst WHERE status = 1
        ) sp ON sp.spell_id = f.spell_id
        LEFT JOIN item_mst im ON im.item_id = f.item_id
        LEFT JOIN jute_yarn_mst ym ON ym.item_id = f.item_id
        WHERE f.spg_wdg = 'S'
          AND f.tran_date = :tran_date
          AND f.item_id IS NOT NULL
          AND (f.active = 1 OR f.active IS NULL)
          AND mt.active = 1
          AND mt.machine_type_name = :spinning_type
          AND (:spell_id IS NULL OR f.spell_id = :spell_id)
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code, f.spell_id
        """
    )


def get_doff_net_by_frame_query():
    """Act Prod Doff = SUM(net_weight) for one frame within co/date/spell_id/machine.

    daily_doff_tbl stores spell_id in `spell` and machine_id in `mc_id`; active rows
    are (active = 1 OR active IS NULL) per the mobile-app legacy flag.
    """
    return text(
        """
        SELECT COALESCE(SUM(net_weight), 0) AS act_prod_doff
        FROM daily_doff_tbl
        WHERE doff_date = :tran_date
          AND spell = :spell_id
          AND mc_id = :machine_id
          AND (active = 1 OR active IS NULL)
        """
    )


def get_winding_total_query():
    """Winding total W = SUM(reconciled_qty) for a quality on a date within a shift bucket.

    Reads the reconciliation view vw_winding_daily_reconciled (one row per co/date/
    spell_id/machine/quality, reconciled_qty = doff net - opening jugar + closing jugar
    in KG), replacing the retired manual aggregate jute_prod_winding_prod. The view is
    per spell_id, so spell_mst is joined to derive the shift bucket (LEFT(spell_code, 1))
    and the rows are aggregated up to a single W per (co, date, yarn item, shift). The
    planning-grid caller binds :item_id (the yarn item id). The view
    vw_winding_daily_reconciled now exposes item_id (sourced from
    jute_prod_winding_doff.item_id, renamed from yarn_quality_id), recreated in lockstep.
    branch_id is null-tolerant so a single-branch planning grid does not pull a
    company-wide winding total and over-allocate.
    """
    return text(
        """
        SELECT COALESCE(SUM(v.reconciled_qty), 0) AS winding_total
        FROM vw_winding_daily_reconciled v
        INNER JOIN spell_mst sp ON sp.spell_id = v.spell_id
        WHERE v.co_id = :co_id
          AND v.tran_date = :tran_date
          AND v.item_id = :item_id
          AND LEFT(sp.spell_code, 1) = :shift
          AND (:branch_id IS NULL OR v.branch_id = :branch_id OR v.branch_id IS NULL)
        """
    )


def get_spinning_daily_active_row_query():
    """Active spinning_daily row id for the per-frame-per-spell grain (upsert lookup).

    App-uniqueness: (co_id, tran_date, spell_id, machine_id, item_id, active=1).
    """
    return text(
        """
        SELECT spinning_daily_id
        FROM jute_prod_spinning_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND item_id = :item_id
          AND active = 1
        ORDER BY spinning_daily_id DESC
        LIMIT 1
        """
    )


def insert_spinning_daily_query():
    """Insert a full per-frame-per-spell planning snapshot."""
    return text(
        """
        INSERT INTO jute_prod_spinning_daily
            (co_id, branch_id, tran_date, spell_id, machine_id, item_id,
             spindles, minutes, act_count, std_count,
             std_speed, actual_speed, target_speed,
             std_tpi, actual_tpi, target_tpi,
             std_eff, target_eff,
             p100prod, std_prod, target_prod,
             act_prod_doff, winding_total, act_prod_wind,
             eff_doff, eff_winding, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id, :item_id,
             :spindles, :minutes, :act_count, :std_count,
             :std_speed, :actual_speed, :target_speed,
             :std_tpi, :actual_tpi, :target_tpi,
             :std_eff, :target_eff,
             :p100prod, :std_prod, :target_prod,
             :act_prod_doff, :winding_total, :act_prod_wind,
             :eff_doff, :eff_winding, 1, :updated_by)
        """
    )


def update_spinning_daily_query():
    """Update a full per-frame-per-spell planning snapshot."""
    return text(
        """
        UPDATE jute_prod_spinning_daily
        SET branch_id = :branch_id,
            spindles = :spindles,
            minutes = :minutes,
            act_count = :act_count,
            std_count = :std_count,
            std_speed = :std_speed,
            actual_speed = :actual_speed,
            target_speed = :target_speed,
            std_tpi = :std_tpi,
            actual_tpi = :actual_tpi,
            target_tpi = :target_tpi,
            std_eff = :std_eff,
            target_eff = :target_eff,
            p100prod = :p100prod,
            std_prod = :std_prod,
            target_prod = :target_prod,
            act_prod_doff = :act_prod_doff,
            winding_total = :winding_total,
            act_prod_wind = :act_prod_wind,
            eff_doff = :eff_doff,
            eff_winding = :eff_winding,
            updated_by = :updated_by
        WHERE spinning_daily_id = :id
        """
    )
