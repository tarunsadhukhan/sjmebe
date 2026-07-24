"""Raw SQL builders for the three Weaving pages (jute production module).

The SINGLE shared query module imported by all three weaving routers, exactly as
``beaming_query.py`` is shared by the beaming routers:

* **Page A — Weaving Quality Master** (``jute_prod_weaving_quality``): woven-cloth item
  list, jute-yarn picker, quality list / row / duplicate-check, insert / update /
  soft-delete, plus the composite-warp component (``jute_prod_weaving_quality_dtl``)
  helpers.
* **Page B — Weaving Standards/Targets Map** (``jute_prod_weaving_target_map``): a clone
  of ``beaming_query``'s target-map section, but **QID-ONLY** (Q5): ``id_type`` is always
  ``'qid'`` (``ref_id = weaving_quality_id``); there are NO loom (``mcid``) standards, so
  the machine-ref join is dropped. Setup quality refs, flat list, single-row CRUD,
  LAST-DATE grid prefill + bulk-save exact-key lookups (all branch-agnostic).
* **Page C — Weaving Production Entry** (``jute_prod_weaving_daily`` + the spinning-style
  ``jute_prod_weaving_quality_map`` Loom->Quality map + ``jute_prod_weaving_beam_map``
  beam-change map): create-setup lookups, entries-by-date day grid (quality INHERITED via
  COALESCE from the quality map, NOT selected inline), machine-standards resolution, the
  planning-grid driver select (cloned from ``get_spinning_plan_driver_query`` but driven
  by the active quality map), the Loom->Quality map get/save/mapped, and the beam-map
  get/save.

Mirrors ``beaming_query.py`` / ``spinning_query.py`` conventions throughout: named binds,
the ``:x IS NULL OR ...`` optional-filter idiom, soft-delete via active=1, and
de-duplication left to the router. ``machine_mst`` / ``machine_type_mst`` filter
``active = 1``; ``spell_mst`` filters ``status = 1`` (NOT active).

The Weaving (Loom) machine type resolves against ``machine_type_mst.machine_type_name`` =
'Loom' (case-insensitive under MySQL's default collation; dev3 machine_type_id 6 'LOOM'),
bound at call time via :loom_type so no constant is imported here. Column names/types
match weaving_models.py exactly.
"""

from sqlalchemy import text


# =============================================================================
# PAGE A — Weaving Quality Master (jute_prod_weaving_quality)
# =============================================================================


def get_weaving_cloth_items_query():
    """Active woven-cloth items for the company — item_grp_mst.item_type_id = 5.

    Adapted from beaming_query.get_beaming_cloth_items_query (Jute Cloth = 5,
    WEAVING_ITEM_TYPE_IDS). Company scope lives on item_grp_mst.co_id (item_mst has
    no co_id by design).
    """
    return text(
        """
        SELECT i.item_id, i.item_code, i.item_name,
               g.item_grp_id, g.item_grp_name, g.item_type_id
        FROM item_mst i
        INNER JOIN item_grp_mst g ON g.item_grp_id = i.item_grp_id
        WHERE i.active = 1
          AND g.co_id = :co_id
          AND g.item_type_id = 5
        ORDER BY i.item_name
        """
    )


def get_weaving_yarns_query():
    """Active jute yarns for the composite-warp count picker (item_type_id = 4).

    Mirrors beaming_query.get_beaming_yarns_query: a yarn IS an item (item_mst); its
    count lives on jute_yarn_mst.jute_yarn_count. Returns item_id (canonical key),
    item_code/item_name, and jute_yarn_count so a component dialog can auto-fill the
    count from the chosen yarn. Company scope is on item_grp_mst.co_id.
    """
    return text(
        """
        SELECT
            ym.item_id,
            im.item_code,
            im.item_name,
            ym.jute_yarn_count
        FROM jute_yarn_mst ym
        JOIN item_mst im ON im.item_id = ym.item_id
        JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        WHERE ig.item_type_id = 4
          AND ig.co_id = :co_id
        ORDER BY im.item_name
        """
    )


def get_weaving_quality_list_query():
    """Active weaving-quality rows for a company, with item label join.

    Optional :item_id filter (one item's qualities); optional :search on code/name;
    optional branch filter that tolerates NULL branch rows (company-scoped master).
    Newest first.
    """
    return text(
        """
        SELECT
            q.weaving_quality_id,
            q.co_id,
            q.branch_id,
            q.item_id,
            im.item_code,
            im.item_name,
            q.weaving_quality_code,
            q.weaving_quality_name,
            q.ends,
            q.finished_length,
            q.ozs_yds,
            q.std_ozs_yds,
            q.no_of_jugar_per_cut,
            q.width,
            q.ports,
            q.reed_porter,
            q.shrinkage_pct,
            q.shots,
            q.mc_teeth,
            q.jbo_rbo,
            q.reed_space,
            q.tpi,
            q.yarn_count,
            q.is_composite,
            q.active
        FROM jute_prod_weaving_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:item_id IS NULL OR q.item_id = :item_id)
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
          AND (:search IS NULL
               OR q.weaving_quality_code LIKE :search
               OR q.weaving_quality_name LIKE :search)
        ORDER BY q.weaving_quality_id DESC
        """
    )


def get_weaving_quality_row_query():
    """A single active weaving-quality row by id (edit / delete existence check)."""
    return text(
        """
        SELECT weaving_quality_id, co_id, branch_id, item_id, weaving_quality_code,
               weaving_quality_name, ends, finished_length, ozs_yds, std_ozs_yds,
               no_of_jugar_per_cut, width, ports, reed_porter, shrinkage_pct, shots,
               mc_teeth, jbo_rbo, reed_space, tpi, yarn_count, is_composite, active
        FROM jute_prod_weaving_quality
        WHERE weaving_quality_id = :weaving_quality_id
          AND active = 1
        """
    )


def check_weaving_quality_duplicate_query():
    """Active duplicate guard on (co_id, item_id, weaving_quality_code).

    Optional :exclude_id excludes the row being edited so an update to itself is not
    flagged as a duplicate. Mirrors check_bm_quality_duplicate_query.
    """
    return text(
        """
        SELECT weaving_quality_id
        FROM jute_prod_weaving_quality
        WHERE co_id = :co_id
          AND item_id = :item_id
          AND weaving_quality_code = :weaving_quality_code
          AND active = 1
          AND (:exclude_id IS NULL OR weaving_quality_id <> :exclude_id)
        LIMIT 1
        """
    )


def insert_weaving_quality_query():
    """Insert a fresh active weaving-quality row (no created_* — trigger-based audit)."""
    return text(
        """
        INSERT INTO jute_prod_weaving_quality
            (co_id, branch_id, item_id, weaving_quality_code, weaving_quality_name,
             ends, finished_length, ozs_yds, std_ozs_yds, no_of_jugar_per_cut,
             width, ports, reed_porter, shrinkage_pct, shots, mc_teeth, jbo_rbo,
             reed_space, tpi, yarn_count, is_composite, active, updated_by)
        VALUES
            (:co_id, :branch_id, :item_id, :weaving_quality_code, :weaving_quality_name,
             :ends, :finished_length, :ozs_yds, :std_ozs_yds, :no_of_jugar_per_cut,
             :width, :ports, :reed_porter, :shrinkage_pct, :shots, :mc_teeth, :jbo_rbo,
             :reed_space, :tpi, :yarn_count, :is_composite, 1, :updated_by)
        """
    )


def update_weaving_quality_query():
    """Patch update one weaving-quality row by id.

    COALESCE keeps the existing value when a bind is NULL, so the router can pass only
    the fields the client sent (mirrors the beaming edit pattern). active is updatable so
    a soft-deleted row can be reactivated via edit if needed.
    """
    return text(
        """
        UPDATE jute_prod_weaving_quality
        SET weaving_quality_code = COALESCE(:weaving_quality_code, weaving_quality_code),
            weaving_quality_name = COALESCE(:weaving_quality_name, weaving_quality_name),
            ends                 = COALESCE(:ends, ends),
            finished_length      = COALESCE(:finished_length, finished_length),
            ozs_yds              = COALESCE(:ozs_yds, ozs_yds),
            std_ozs_yds          = COALESCE(:std_ozs_yds, std_ozs_yds),
            no_of_jugar_per_cut  = COALESCE(:no_of_jugar_per_cut, no_of_jugar_per_cut),
            width                = COALESCE(:width, width),
            ports                = COALESCE(:ports, ports),
            reed_porter          = COALESCE(:reed_porter, reed_porter),
            shrinkage_pct        = COALESCE(:shrinkage_pct, shrinkage_pct),
            shots                = COALESCE(:shots, shots),
            mc_teeth             = COALESCE(:mc_teeth, mc_teeth),
            jbo_rbo              = COALESCE(:jbo_rbo, jbo_rbo),
            reed_space           = COALESCE(:reed_space, reed_space),
            tpi                  = COALESCE(:tpi, tpi),
            yarn_count           = COALESCE(:yarn_count, yarn_count),
            is_composite         = COALESCE(:is_composite, is_composite),
            active               = COALESCE(:active, active),
            updated_by           = :updated_by,
            updated_date_time    = CURRENT_TIMESTAMP
        WHERE weaving_quality_id = :weaving_quality_id
        """
    )


def soft_delete_weaving_quality_query():
    """Soft-delete (active=0) one weaving-quality row by id."""
    return text(
        """
        UPDATE jute_prod_weaving_quality
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_quality_id = :weaving_quality_id
        """
    )


def get_weaving_quality_detail_query():
    """A single active weaving-quality parent row by id + co_id (edit dialog, Q6).

    Co-scoped variant of get_weaving_quality_row_query for the
    weaving_quality_detail/{id} endpoint — the router fetches the component rows
    separately via get_weaving_quality_components_query and nests them under
    ``components``.
    """
    return text(
        """
        SELECT weaving_quality_id, co_id, branch_id, item_id, weaving_quality_code,
               weaving_quality_name, ends, finished_length, ozs_yds, std_ozs_yds,
               no_of_jugar_per_cut, width, ports, reed_porter, shrinkage_pct, shots,
               mc_teeth, jbo_rbo, reed_space, tpi, yarn_count, is_composite, active
        FROM jute_prod_weaving_quality
        WHERE weaving_quality_id = :weaving_quality_id
          AND co_id = :co_id
          AND active = 1
        """
    )


def get_weaving_quality_components_query():
    """Active component rows for a composite weaving quality (Q6, mirror beaming).

    Returns the real (ends, count) warp-component pairs ordered by component_no for
    the edit dialog. Only populated when the parent is_composite=1 (>=2 rows);
    non-composite qualities have no rows here.
    """
    return text(
        """
        SELECT weaving_quality_dtl_id, component_no, ends, yarn_item_id, count
        FROM jute_prod_weaving_quality_dtl
        WHERE weaving_quality_id = :weaving_quality_id
          AND active = 1
        ORDER BY component_no
        """
    )


def insert_weaving_quality_component_query():
    """Insert one active component row for a composite weaving quality (Q6)."""
    return text(
        """
        INSERT INTO jute_prod_weaving_quality_dtl
            (weaving_quality_id, component_no, ends, yarn_item_id, count, active)
        VALUES
            (:weaving_quality_id, :component_no, :ends, :yarn_item_id, :count, 1)
        """
    )


def soft_delete_weaving_quality_components_query():
    """Soft-delete (active=0) ALL components of a weaving quality (replace-on-edit, Q6).

    Edit re-inserts the full component set, so the router clears the existing set
    first via this builder, then re-inserts via insert_weaving_quality_component_query.
    """
    return text(
        """
        UPDATE jute_prod_weaving_quality_dtl
        SET active = 0
        WHERE weaving_quality_id = :weaving_quality_id
          AND active = 1
        """
    )


# =============================================================================
# PAGE B — Weaving Standards/Targets Map (jute_prod_weaving_target_map)
# TWO-DIMENSIONAL clone of beaming_query's target-map section. id_type is 'mcid'
# (ref_id = machine_id, a LOOM) or 'qid' (ref_id =
# jute_prod_weaving_quality.weaving_quality_id). Loom (mcid) refs reuse PAGE C's
# get_weaving_entry_machines_query(); the queries below cover the qid refs + the
# id_type-agnostic list / row / grid resolve / bulk-save shape.
# =============================================================================


def get_weaving_target_qualities_query():
    """Active Weaving-Quality rows for the target-map QID grid refs (qid-only, Q5).

    Mirrors beaming_query.get_beaming_target_qualities_query: the grid ref is the
    weaving QUALITY (jute_prod_weaving_quality). Returns ref_id = weaving_quality_id,
    ref_code = weaving_quality_code, ref_name = weaving_quality_name so the router can
    build {ref_id, ref_code, ref_name} ref rows. Company-scoped (co_id); :branch_id
    is accepted for call-shape parity but quality is branch-agnostic (NULL-tolerant).
    Newest first.
    """
    return text(
        """
        SELECT
            q.weaving_quality_id,
            q.weaving_quality_code,
            q.weaving_quality_name,
            q.branch_id
        FROM jute_prod_weaving_quality q
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:branch_id IS NULL OR q.branch_id = :branch_id OR q.branch_id IS NULL)
        ORDER BY q.weaving_quality_id DESC
        """
    )


def get_weaving_target_map_list_query():
    """Active weaving target-map rows with optional id_type / ref_id / value_role /
    param filters. Newest effective_date first. QID-ONLY: the ref label comes from the
    Weaving Quality Master (jute_prod_weaving_quality, ref_id = weaving_quality_id).
    The :id_type bind is accepted for call-shape parity with beaming but in practice is
    always 'qid'."""
    return text(
        """
        SELECT
            tm.weaving_target_map_id,
            tm.co_id,
            tm.branch_id,
            tm.effective_date,
            tm.ref_id,
            tm.id_type,
            tm.value_role,
            tm.param,
            tm.value,
            tm.active,
            q.weaving_quality_code AS ref_code,
            q.weaving_quality_name AS ref_name
        FROM jute_prod_weaving_target_map tm
        LEFT JOIN jute_prod_weaving_quality q
               ON q.weaving_quality_id = tm.ref_id
        WHERE tm.co_id = :co_id
          AND tm.active = 1
          AND (:branch_id IS NULL OR tm.branch_id = :branch_id OR tm.branch_id IS NULL)
          AND (:id_type IS NULL OR tm.id_type = :id_type)
          AND (:ref_id IS NULL OR tm.ref_id = :ref_id)
          AND (:value_role IS NULL OR tm.value_role = :value_role)
          AND (:param IS NULL OR tm.param = :param)
        ORDER BY tm.effective_date DESC, tm.weaving_target_map_id DESC
        """
    )


def get_weaving_target_map_row_query():
    """A single active weaving target-map row by id (for edit / delete existence check)."""
    return text(
        """
        SELECT weaving_target_map_id, co_id, branch_id, effective_date, ref_id,
               id_type, value_role, param, value, active
        FROM jute_prod_weaving_target_map
        WHERE weaving_target_map_id = :id
          AND active = 1
        """
    )


def insert_weaving_target_map_query():
    """Insert a fresh active weaving standards/targets row (id_type always 'qid')."""
    return text(
        """
        INSERT INTO jute_prod_weaving_target_map
            (co_id, branch_id, effective_date, ref_id, id_type, value_role,
             param, value, active, updated_by)
        VALUES
            (:co_id, :branch_id, :effective_date, :ref_id, :id_type, :value_role,
             :param, :value, 1, :updated_by)
        """
    )


def update_weaving_target_map_query():
    """Patch update one weaving target-map row by id (value + effective_date + audit)."""
    return text(
        """
        UPDATE jute_prod_weaving_target_map
        SET value = COALESCE(:value, value),
            effective_date = COALESCE(:effective_date, effective_date),
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_target_map_id = :id
        """
    )


def soft_delete_weaving_target_map_query():
    """Soft-delete (active=0) one weaving target-map row by id."""
    return text(
        """
        UPDATE jute_prod_weaving_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_target_map_id = :id
        """
    )


def resolve_weaving_target_value_query():
    """LAST-DATE resolution: the value effective on :on_date for one resolution key.

    MAX(effective_date) <= :on_date among active rows for
    (co_id, ref_id, id_type, value_role, param). Branch-agnostic (mirrors beaming /
    resolve_param). Consumed by the Page C standards snapshot builder
    (services/weaving_standards.py).
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_weaving_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, weaving_target_map_id DESC
        LIMIT 1
        """
    )


def resolve_weaving_grid_cell_query():
    """LAST-DATE resolution for ONE grid cell, mirroring resolve_param semantics.

    Same WHERE/ORDER/LIMIT as resolve_weaving_target_value_query and applies NO branch
    filter, returning effective_date so the grid can expose source_date / is_exact
    (effective_date == :on_date). The grid reads values exactly as production does.
    """
    return text(
        """
        SELECT value, effective_date
        FROM jute_prod_weaving_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND active = 1
          AND effective_date <= :on_date
        ORDER BY effective_date DESC, weaving_target_map_id DESC
        LIMIT 1
        """
    )


def find_exact_weaving_grid_row_query():
    """Active row at the EXACT save key, BRANCH-AGNOSTIC (mirrors grid resolution).

    Used by target_map_bulk_save to decide insert-vs-update-vs-clear. Applies NO branch
    filter so save targets the SAME row the grid prefilled (resolve_weaving_grid_cell_query
    ignores branch_id); the newest-id tiebreak matches the grid's is_exact ORDER BY.
    """
    return text(
        """
        SELECT weaving_target_map_id, value
        FROM jute_prod_weaving_target_map
        WHERE co_id = :co_id
          AND ref_id = :ref_id
          AND id_type = :id_type
          AND value_role = :value_role
          AND param = :param
          AND effective_date = :effective_date
          AND active = 1
        ORDER BY weaving_target_map_id DESC
        LIMIT 1
        """
    )


def update_weaving_grid_value_query():
    """Set value (+ audit cols) on one active grid row by id."""
    return text(
        """
        UPDATE jute_prod_weaving_target_map
        SET value = :value,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_target_map_id = :id
        """
    )


def clear_weaving_grid_value_query():
    """Soft-delete (active=0) one grid row by id, clearing the cell."""
    return text(
        """
        UPDATE jute_prod_weaving_target_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_target_map_id = :id
        """
    )


# =============================================================================
# PAGE C — Weaving Production Entry (jute_prod_weaving_daily)
# create_setup lookups + entries_by_date day grid + planning-grid driver select.
# Looms resolve by machine_type_name 'Loom' (:loom_type, case-insensitive).
# =============================================================================


def get_weaving_entry_machines_query():
    """Loom-type machines for the entry create-setup (resolve by NAME 'Loom').

    Machine identity only; quality is inherited from the §6.6 quality map, standards
    resolve per-date from the qid target map. machine_mst/machine_type_mst filter
    active=1. line_no is the dev3 line column (NOT line_number).
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.machine_name,
            m.mech_code,
            m.dept_id,
            m.line_no,
            d.dept_desc AS dept_name,
            d.branch_id
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :loom_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_weaving_spells_query():
    """Active spells with working hours for the entry header.

    spell_mst filters status = 1 (NOT active); shift_mst filters status = 1. Returns
    spell_id (daily table stores INT spell_id) plus the code/name/hours. Callers must
    de-dup by spell_code in Python (branch fanout), keeping the first row per code.
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


def resolve_weaving_spell_id_query():
    """Resolve a spell_code string to its canonical spell_id (MIN dedupes branch fanout).

    Mirrors spinning_query.resolve_spell_id_query: the weaving GET grids receive the
    spell *code* ('A1', 'B1', ...) from the client and must map it to the INT spell_id
    the daily/map tables store.
    """
    return text(
        """
        SELECT MIN(spell_id) AS spell_id
        FROM spell_mst
        WHERE spell_code = :spell_code AND status = 1
        """
    )


def get_weaving_eb_list_query():
    """Active employee (eb) list for display joins / pickers.

    The eb identity is the HRMS employee (hrms_ed_personal_details, keyed by eb_id);
    there is no eb_master table. Joins hrms_ed_official_details (active=1) for emp_code
    and branch scope. Branch-scoped, NULL-tolerant. On the weaving screen EB is NOT
    entered (resolved via attendance view, Q7); this list is kept for parity and any
    best-effort eb label lookups.
    """
    return text(
        """
        SELECT
            p.eb_id,
            o.emp_code,
            CONCAT(p.first_name, ' ', COALESCE(p.last_name, '')) AS eb_name,
            o.branch_id
        FROM hrms_ed_personal_details p
        LEFT JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
        WHERE p.active = 1
          AND (:branch_id IS NULL OR o.branch_id = :branch_id OR o.branch_id IS NULL)
        ORDER BY o.emp_code, p.first_name
        """
    )


def get_weaving_entry_qualities_query():
    """All active weaving qualities for the company (item->quality reference / picker).

    Returns the item label and the quality's construction attrs (ends, finished_length,
    ozs_yds, std_ozs_yds, no_of_jugar_per_cut, is_composite) so the FE can render the
    mapped quality read-only and the compute layer can snapshot standards. Quality is
    MAPPED (Loom->Quality map), not selected inline on the production grid. Optional
    :item_id filter.
    """
    return text(
        """
        SELECT
            q.weaving_quality_id,
            q.item_id,
            im.item_code,
            im.item_name,
            q.weaving_quality_code,
            q.weaving_quality_name,
            q.ends,
            q.finished_length,
            q.ozs_yds,
            q.std_ozs_yds,
            q.no_of_jugar_per_cut,
            q.is_composite
        FROM jute_prod_weaving_quality q
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE q.co_id = :co_id
          AND q.active = 1
          AND (:item_id IS NULL OR q.item_id = :item_id)
        ORDER BY im.item_name, q.weaving_quality_code
        """
    )


def get_weaving_entries_by_date_query():
    """Weaving-daily entries for the day grid — read from vw_weaving_daily.

    STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24): the daily table stores INPUTS
    ONLY; every derived column (open_jugar, jugar, finished_length/ozs_yds/std_ozs_yds/
    no_of_jugar_per_cut, std/act speed+picks, std/target eff, working_hours,
    production_yds/kg/mt, std_prod_yds, target_prod_yds, efficiency, std_prod_kg,
    target_kg) is computed on read by the view. Quality is INHERITED inside the view via
    COALESCE(daily.weaving_quality_id, quality_map.weaving_quality_id); the view already
    surfaces spell_code, mech_code/machine_name/line_no and the item/quality labels, so
    this just filters + orders. spell_id, machine_id, branch_id optional.
    """
    return text(
        """
        SELECT
            v.weaving_daily_id,
            v.co_id,
            v.branch_id,
            v.tran_date,
            v.spell_id,
            v.spell_code,
            v.machine_id,
            v.mech_code,
            v.machine_name,
            v.line_no,
            v.weaving_quality_id,
            v.item_id,
            v.item_code,
            v.item_name,
            v.weaving_quality_code,
            v.weaving_quality_name,
            v.is_composite,
            v.eb_id,
            v.beam_no,
            v.cuts,
            v.close_jugar,
            v.less_production,
            v.open_jugar,
            v.jugar,
            v.finished_length,
            v.ozs_yds,
            v.std_ozs_yds,
            v.no_of_jugar_per_cut,
            v.std_speed,
            v.act_speed,
            v.std_picks,
            v.act_picks,
            v.std_eff,
            v.target_eff,
            v.eff_speed,
            v.eff_picks,
            v.working_hours,
            v.production_yds,
            v.production_kg,
            v.production_mt,
            v.std_prod_yds,
            v.target_prod_yds,
            v.efficiency,
            v.std_prod_kg,
            v.target_kg
        FROM vw_weaving_daily v
        WHERE v.co_id = :co_id
          AND v.tran_date = :tran_date
          AND (:spell_id IS NULL OR v.spell_id = :spell_id)
          AND (:machine_id IS NULL OR v.machine_id = :machine_id)
          AND (:branch_id IS NULL OR v.branch_id = :branch_id OR v.branch_id IS NULL)
        ORDER BY v.mech_code, v.weaving_daily_id DESC
        """
    )


def get_weaving_plan_driver_query():
    """Driver rows for the planning grid: active jute_prod_weaving_quality_map rows
    LEFT JOIN vw_weaving_daily (FREEZE NOTHING + VIEW, 2026-06-24).

    The grid is DRIVEN by the Loom->Quality map (mapped looms, even with no entry yet) —
    only rows WHERE active AND weaving_quality_id IS NOT NULL participate (an unmapped
    loom has nothing to plan). Each driver row LEFT JOINs the view on
    (co_id, tran_date, spell_id, machine_id, weaving_quality_id) so a saved daily entry
    contributes its INPUTS (cuts, close_jugar, less_production) and EVERY view-computed
    column (open_jugar, jugar, production_yds/kg/mt, std_prod_yds, target_prod_yds,
    efficiency, std_prod_kg, target_kg, eff_speed/eff_picks, working_hours). A mapped
    loom with no entry yet keeps NULL view columns (the router coalesces to 0). The map
    still supplies the construction attrs from the quality master so an empty cell can
    show finished_length/ozs_yds/no_of_jugar_per_cut. spell_id, machine_id optional;
    looms resolved by NAME 'Loom' (:loom_type).
    """
    return text(
        """
        SELECT
            qm.weaving_quality_map_id,
            qm.machine_id,
            qm.spell_id,
            qm.weaving_quality_id,
            q.item_id,
            m.mech_code,
            m.machine_name,
            m.line_no,
            d.branch_id,
            sp.spell_code,
            sp.working_hours AS spell_working_hours,
            im.item_code,
            im.item_name,
            q.weaving_quality_code,
            q.weaving_quality_name,
            q.ends,
            q.finished_length,
            q.ozs_yds,
            q.std_ozs_yds,
            q.no_of_jugar_per_cut,
            q.is_composite,
            v.weaving_daily_id,
            v.eb_id,
            v.beam_no,
            v.cuts,
            v.close_jugar,
            v.less_production,
            v.open_jugar,
            v.jugar,
            v.std_speed,
            v.act_speed,
            v.std_picks,
            v.act_picks,
            v.std_eff,
            v.target_eff,
            v.eff_speed,
            v.eff_picks,
            v.working_hours,
            v.production_yds,
            v.production_kg,
            v.production_mt,
            v.std_prod_yds,
            v.target_prod_yds,
            v.efficiency,
            v.std_prod_kg,
            v.target_kg
        FROM jute_prod_weaving_quality_map qm
        INNER JOIN machine_mst m ON m.machine_id = qm.machine_id
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN (
            SELECT spell_id, spell_code, working_hours
            FROM spell_mst WHERE status = 1
        ) sp ON sp.spell_id = qm.spell_id
        LEFT JOIN jute_prod_weaving_quality q ON q.weaving_quality_id = qm.weaving_quality_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        LEFT JOIN vw_weaving_daily v
               ON v.co_id = qm.co_id
              AND v.tran_date = qm.tran_date
              AND v.spell_id = qm.spell_id
              AND v.machine_id = qm.machine_id
              AND v.weaving_quality_id = qm.weaving_quality_id
        WHERE qm.co_id = :co_id
          AND qm.active = 1
          AND qm.tran_date = :tran_date
          AND qm.weaving_quality_id IS NOT NULL
          AND mt.active = 1
          AND mt.machine_type_name = :loom_type
          AND (:spell_id IS NULL OR qm.spell_id = :spell_id)
          AND (:machine_id IS NULL OR qm.machine_id = :machine_id)
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code, qm.spell_id
        """
    )


def get_weaving_daily_active_row_query():
    """Active weaving_daily row id for the entry/plan grain (upsert lookup).

    App-uniqueness: (co_id, tran_date, spell_id, machine_id, weaving_quality_id,
    active=1).
    """
    return text(
        """
        SELECT weaving_daily_id
        FROM jute_prod_weaving_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND weaving_quality_id = :weaving_quality_id
          AND active = 1
        ORDER BY weaving_daily_id DESC
        LIMIT 1
        """
    )


def insert_weaving_daily_query():
    """Insert one per-loom/per-quality/per-spell production entry — INPUTS ONLY.

    STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24): the table stores only identity +
    operator inputs (cuts, close_jugar, less_production); open_jugar, jugar and every
    resolved-standard / computed output are recomputed on read by vw_weaving_daily, NOT
    stored. close_jugar is the operator's closing-jugar reading (0 <= cj <= jc, enforced
    in the router). No created_* — trigger-based audit.
    """
    return text(
        """
        INSERT INTO jute_prod_weaving_daily
            (co_id, branch_id, tran_date, spell_id, machine_id, weaving_quality_id,
             eb_id, beam_no, cuts, close_jugar, less_production, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id, :weaving_quality_id,
             :eb_id, :beam_no, :cuts, :close_jugar, :less_production, 1, :updated_by)
        """
    )


def update_weaving_daily_query():
    """Update one per-loom/per-quality/per-spell production entry by id — INPUTS ONLY.

    Only identity (branch/quality/eb/beam) + the operator inputs (cuts, close_jugar,
    less_production) are updatable; every derived column lives in vw_weaving_daily.
    """
    return text(
        """
        UPDATE jute_prod_weaving_daily
        SET branch_id = :branch_id,
            weaving_quality_id = :weaving_quality_id,
            eb_id = :eb_id,
            beam_no = :beam_no,
            cuts = :cuts,
            close_jugar = :close_jugar,
            less_production = :less_production,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_daily_id = :id
        """
    )


def update_weaving_daily_less_production_query():
    """Set ONLY less_production (reduce-jugar) on one daily row, by weaving_daily_id.

    Used by the Production Adjustment tab so an adjustment never disturbs the entry inputs
    (cuts/close_jugar/quality stay exactly as the operator saved them); the view re-derives
    production_yds from the new less_production. Stamps who/when.
    """
    return text(
        """
        UPDATE jute_prod_weaving_daily
        SET less_production = :less_production,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_daily_id = :id
        """
    )


def soft_delete_weaving_daily_query():
    """Soft-delete (active=0) one weaving-daily row by id."""
    return text(
        """
        UPDATE jute_prod_weaving_daily
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_daily_id = :id
        """
    )


# NOTE (FREEZE NOTHING + VIEW, 2026-06-24): get_weaving_idle_hours_query and
# get_weaving_prev_close_jugar_query were DELETED. Net working_hours (gross spell hours
# minus stoppage) and open_jugar (prior-spell close carry-forward) are now computed
# inside vw_weaving_daily — the former via a correlated SUM(jute_prod_stoppage_hours),
# the latter via a LAG window over existing active rows in spell order across days. The
# server no longer resolves either on save; it persists inputs only.


# =============================================================================
# PAGE C tab — Loom -> Quality map (jute_prod_weaving_quality_map)
# Clone of spinning_query's frame-map (daily_doff_frames_winding S-rows): one ACTIVE
# row per (tran_date, spell_id, machine_id). Production inherits quality from here.
# =============================================================================


def get_weaving_quality_map_query():
    """All Loom-type machines with today's SAVED Loom->Quality mapping + a carry-forward
    draft (the loom's most-recent saved mapping across ANY spell/date) as prev_quality_*.

    Clone of spinning_query.get_frame_map_query, adapted to the dedicated
    jute_prod_weaving_quality_map table (machine_id, not mc_eb_id). Looms resolved by
    NAME 'Loom' (:loom_type).

    weaving_quality_id/weaving_quality_code/weaving_quality_name
        = today's SAVED mapping for this (spell_id, tran_date) — NULL when nothing saved.
    prev_quality_id/prev_quality_code/prev_quality_name/prev_date
        = the loom's most-recent saved mapping across ANY spell/date, EXCLUDING the
          current (tran_date, spell_id) cell (correlated subquery, latest tran_date then
          id). Surfaced so the client can prefill the dropdown and flag it unsaved until
          the operator clicks Save Map — lets a never-mapped spell bootstrap from the
          latest prior setup.
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.mech_code,
            m.mech_posting_code,
            m.machine_name,
            m.line_no,
            d.branch_id,
            qm.weaving_quality_map_id,
            qm.weaving_quality_id,
            q.weaving_quality_code,
            q.weaving_quality_name,
            (
                SELECT p.weaving_quality_id
                FROM jute_prod_weaving_quality_map p
                WHERE p.machine_id = m.machine_id
                  AND p.co_id = :co_id
                  AND p.active = 1
                  AND p.weaving_quality_id IS NOT NULL
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.weaving_quality_map_id DESC
                LIMIT 1
            ) AS prev_quality_id,
            (
                SELECT pq.weaving_quality_code
                FROM jute_prod_weaving_quality_map p
                JOIN jute_prod_weaving_quality pq ON pq.weaving_quality_id = p.weaving_quality_id
                WHERE p.machine_id = m.machine_id
                  AND p.co_id = :co_id
                  AND p.active = 1
                  AND p.weaving_quality_id IS NOT NULL
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.weaving_quality_map_id DESC
                LIMIT 1
            ) AS prev_quality_code,
            (
                SELECT pq.weaving_quality_name
                FROM jute_prod_weaving_quality_map p
                JOIN jute_prod_weaving_quality pq ON pq.weaving_quality_id = p.weaving_quality_id
                WHERE p.machine_id = m.machine_id
                  AND p.co_id = :co_id
                  AND p.active = 1
                  AND p.weaving_quality_id IS NOT NULL
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.weaving_quality_map_id DESC
                LIMIT 1
            ) AS prev_quality_name,
            (
                SELECT p.tran_date
                FROM jute_prod_weaving_quality_map p
                WHERE p.machine_id = m.machine_id
                  AND p.co_id = :co_id
                  AND p.active = 1
                  AND p.weaving_quality_id IS NOT NULL
                  AND NOT (p.tran_date = :tran_date AND p.spell_id = :spell_id)
                ORDER BY p.tran_date DESC, p.weaving_quality_map_id DESC
                LIMIT 1
            ) AS prev_date
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN jute_prod_weaving_quality_map qm
               ON qm.machine_id = m.machine_id
              AND qm.co_id = :co_id
              AND qm.tran_date = :tran_date
              AND qm.spell_id = :spell_id
              AND qm.active = 1
        LEFT JOIN jute_prod_weaving_quality q ON q.weaving_quality_id = qm.weaving_quality_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :loom_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_weaving_quality_map_active_row_query():
    """The active map row id for one loom on a tran_date/spell_id (upsert lookup).

    One ACTIVE row per (co_id, tran_date, spell_id, machine_id). Newest id wins on ties.
    """
    return text(
        """
        SELECT weaving_quality_map_id
        FROM jute_prod_weaving_quality_map
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND active = 1
        ORDER BY weaving_quality_map_id DESC
        LIMIT 1
        """
    )


def update_weaving_quality_map_row_query():
    """Update an existing active map row's quality assignment (stamps who/when)."""
    return text(
        """
        UPDATE jute_prod_weaving_quality_map
        SET weaving_quality_id = :weaving_quality_id,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_quality_map_id = :id
        """
    )


def insert_weaving_quality_map_row_query():
    """Insert a fresh active Loom->Quality map row (stamps who/when)."""
    return text(
        """
        INSERT INTO jute_prod_weaving_quality_map
            (co_id, branch_id, tran_date, spell_id, machine_id, weaving_quality_id,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id, :weaving_quality_id,
             1, :updated_by)
        """
    )


def get_weaving_quality_map_mapped_query():
    """Saved Loom->Quality mappings for a (tran_date, spell_id) — the mapped view.

    Clone of the spinning frame_map "mapped" read: only looms that actually have an
    active mapping for this cell, with the machine + quality labels. Branch-scoped,
    NULL-tolerant. Looms resolved by NAME 'Loom' (:loom_type).
    """
    return text(
        """
        SELECT
            qm.weaving_quality_map_id,
            qm.machine_id,
            m.mech_code,
            m.machine_name,
            m.line_no,
            qm.weaving_quality_id,
            q.weaving_quality_code,
            q.weaving_quality_name,
            q.item_id,
            im.item_code,
            im.item_name,
            qm.branch_id,
            qm.updated_date_time
        FROM jute_prod_weaving_quality_map qm
        INNER JOIN machine_mst m ON m.machine_id = qm.machine_id
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        LEFT JOIN jute_prod_weaving_quality q ON q.weaving_quality_id = qm.weaving_quality_id
        LEFT JOIN item_mst im ON im.item_id = q.item_id
        WHERE qm.co_id = :co_id
          AND qm.active = 1
          AND qm.tran_date = :tran_date
          AND qm.weaving_quality_id IS NOT NULL
          AND mt.active = 1
          AND mt.machine_type_name = :loom_type
          AND (:spell_id IS NULL OR qm.spell_id = :spell_id)
          AND (:machine_id IS NULL OR qm.machine_id = :machine_id)
          AND (:branch_id IS NULL OR qm.branch_id = :branch_id OR qm.branch_id IS NULL)
        ORDER BY m.mech_code, qm.spell_id
        """
    )


def get_weaving_quality_map_last_updated_query():
    """The most recent save timestamp across a branch's active Loom->Quality map rows.

    Surfaced in the Loom->Quality grid so the operator can see when the branch's mapping
    was last touched. Branch-scoped (NULL branch_id = whole tenant).
    """
    return text(
        """
        SELECT MAX(updated_date_time) AS last_updated
        FROM jute_prod_weaving_quality_map
        WHERE co_id = :co_id
          AND active = 1
          AND (:branch_id IS NULL OR branch_id = :branch_id)
        """
    )


def get_weaving_adjustment_grid_query():
    """Production-Adjustment grid: every Loom with its mapped quality + that daily row's
    current less_production (reduce-jugar) for one (tran_date, spell_id).

    Drives the Production Adjustment tab. Looms resolved by NAME 'Loom' (:loom_type,
    case-insensitive) via machine_type_mst, branch-scoped and NULL-tolerant on :branch_id.
    LEFT JOINs the active Loom->Quality map (so an unmapped loom still appears with NULL
    quality) and the active daily row at the mapped quality, surfacing weaving_daily_id +
    COALESCE(less_production, 0) so the FE can patch only that one input. Newest cell wins
    via the upsert grain; machine_mst/machine_type_mst filter active=1.
    """
    return text(
        """
        SELECT
            m.machine_id, m.mech_code, m.mech_posting_code, m.machine_name, m.line_no,
            d.branch_id,
            qm.weaving_quality_id,
            q.weaving_quality_code, q.weaving_quality_name,
            wd.weaving_daily_id,
            COALESCE(wd.less_production, 0) AS less_production
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        LEFT JOIN jute_prod_weaving_quality_map qm
               ON qm.machine_id = m.machine_id AND qm.co_id = :co_id
              AND qm.tran_date = :tran_date AND qm.spell_id = :spell_id AND qm.active = 1
        LEFT JOIN jute_prod_weaving_quality q ON q.weaving_quality_id = qm.weaving_quality_id
        LEFT JOIN jute_prod_weaving_daily wd
               ON wd.co_id = :co_id AND wd.tran_date = :tran_date AND wd.spell_id = :spell_id
              AND wd.machine_id = m.machine_id AND wd.weaving_quality_id = qm.weaving_quality_id
              AND wd.active = 1
        WHERE m.active = 1 AND mt.active = 1 AND mt.machine_type_name = :loom_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


# =============================================================================
# PAGE C tab — Beam -> Loom map (jute_prod_weaving_beam_map)
# Beam change recorded per (tran_date, spell_id, machine_id); production beam_no is
# resolved from the LATEST beam-change for (loom, spell, date) (Q7).
# =============================================================================


def get_weaving_beam_map_query():
    """Latest beam per loom for a (tran_date, spell_id) — the Beam-Change tab grid.

    Returns every Loom-type machine with its most-recent active beam_no for the cell
    (correlated subquery: latest id among active rows for the loom/spell/date), so the
    client can show/edit the mounted beam. Looms resolved by NAME 'Loom' (:loom_type).
    Branch-scoped, NULL-tolerant.
    """
    return text(
        """
        SELECT
            m.machine_id,
            m.mech_code,
            m.machine_name,
            m.line_no,
            d.branch_id,
            (
                SELECT b.weaving_beam_map_id
                FROM jute_prod_weaving_beam_map b
                WHERE b.machine_id = m.machine_id
                  AND b.co_id = :co_id
                  AND b.tran_date = :tran_date
                  AND b.spell_id = :spell_id
                  AND b.active = 1
                ORDER BY b.weaving_beam_map_id DESC
                LIMIT 1
            ) AS weaving_beam_map_id,
            (
                SELECT b.beam_no
                FROM jute_prod_weaving_beam_map b
                WHERE b.machine_id = m.machine_id
                  AND b.co_id = :co_id
                  AND b.tran_date = :tran_date
                  AND b.spell_id = :spell_id
                  AND b.active = 1
                ORDER BY b.weaving_beam_map_id DESC
                LIMIT 1
            ) AS beam_no
        FROM machine_mst m
        INNER JOIN machine_type_mst mt ON mt.machine_type_id = m.machine_type_id
        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
        WHERE m.active = 1
          AND mt.active = 1
          AND mt.machine_type_name = :loom_type
          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
        ORDER BY m.mech_code
        """
    )


def get_weaving_latest_beam_no_query():
    """The latest active beam_no for one loom on a (tran_date, spell_id) (resolution).

    Used by the entry/compute layer to stamp jute_prod_weaving_daily.beam_no from the
    §6.7 beam map (beam_no is NOT entered on the production row, Q7). Newest id wins.
    """
    return text(
        """
        SELECT beam_no
        FROM jute_prod_weaving_beam_map
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND active = 1
        ORDER BY weaving_beam_map_id DESC
        LIMIT 1
        """
    )


def get_weaving_beam_map_active_row_query():
    """The active beam-map row id for one loom on a tran_date/spell_id (upsert lookup).

    Beam change is upsert-per-cell (one active row per loom/spell/date). Newest id wins.
    """
    return text(
        """
        SELECT weaving_beam_map_id
        FROM jute_prod_weaving_beam_map
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND active = 1
        ORDER BY weaving_beam_map_id DESC
        LIMIT 1
        """
    )


def update_weaving_beam_map_row_query():
    """Update an existing active beam-map row's beam_no (stamps who/when)."""
    return text(
        """
        UPDATE jute_prod_weaving_beam_map
        SET beam_no = :beam_no,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_beam_map_id = :id
        """
    )


def insert_weaving_beam_map_row_query():
    """Insert a fresh active beam->loom map row (stamps who/when)."""
    return text(
        """
        INSERT INTO jute_prod_weaving_beam_map
            (co_id, branch_id, tran_date, spell_id, machine_id, beam_no,
             active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, :machine_id, :beam_no,
             1, :updated_by)
        """
    )


def soft_delete_weaving_beam_map_row_query():
    """Soft-delete (active=0) one beam-map row by id (clear a mounted beam)."""
    return text(
        """
        UPDATE jute_prod_weaving_beam_map
        SET active = 0,
            updated_by = :updated_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_beam_map_id = :id
        """
    )
