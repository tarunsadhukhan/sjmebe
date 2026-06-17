# Design: Apply `daily_attendance_mod` overrides after the bio-attendance final process

**Date:** 2026-06-17
**Repo:** `sjmvowerp3be` (FastAPI/Python backend)
**Area:** HRMS bio-attendance pipeline

## Problem

After the automated bio-attendance pipeline runs its final process, the
`daily_attendance` rows reflect values computed by the pipeline
(`spell`, `worked_department_id`, `worked_designation_id`, `attendance_type`).
Users make manual corrections to a separate table, `daily_attendance_mod`.
Those corrections are currently never copied back into `daily_attendance`, so:

1. Manual corrections to `spell` / `worked_department_id` /
   `worked_designation_id` are lost on every re-run of the final process.
2. A dept/designation correction never propagates to later dates, because the
   pipeline resolves an employee's dept/desig from the *last-date*
   `daily_attendance` row — which still holds the uncorrected value.

## Goal

After the final process finishes building/reconciling `daily_attendance` for a
date, copy the manual corrections from `daily_attendance_mod` into the matching
`daily_attendance` rows for that date.

## Decisions (confirmed with user)

- **Match keys:** `eb_id`, `bio_id`, `attendance_date`, `attendance_type`.
- **Overwritten columns:** `spell`, `worked_department_id`,
  `worked_designation_id` (plus `update_date_time` bumped to `NOW()`).
- `attendance_type` is a **match key only** — never overwritten.
- **NULL handling:** use `COALESCE(mod_value, existing_value)` so a
  partially-filled `daily_attendance_mod` row does not wipe good values.
- **Source scope:** restrict to `daily_attendance.attendance_source = 'BIO'` —
  the copy only touches rows the bio pipeline owns.
- **Propagation strategy:** feedback-loop only. No change to dept/desig
  resolution. A correction copied into `daily_attendance` for date D becomes the
  new `MAX(attendance_date)` row that the resolver reads when processing D+1, so
  corrections propagate forward naturally. (The alternative — making
  `daily_attendance_mod` a top-priority source inside the resolver — was
  explicitly rejected as unnecessary.)

## "Last-date dept/desig" verification (the user's second concern)

Verified in code:

- Dept/desig are resolved during the chain (`etrack_process_d_core` /
  `bprocess_core` in `bioAttUpdation.py`) via `_ETRACK_PROC_LAST_DAILY_ATT_SQL`,
  which selects `worked_department_id` / `worked_designation_id` from the
  `daily_attendance` row with `MAX(attendance_date)` per `eb_id`
  (fallback: `hrms_ed_official_details`).
- The final process (`finalize_daily_attendance`) then writes those resolved
  values into the new/updated `daily_attendance` rows.

**Conclusion:** the final process already writes the *last-date* dept/desig. The
only gap was that manual corrections living in `daily_attendance_mod` were never
folded back into `daily_attendance`, so the "last date" the resolver reads could
be stale relative to a correction. The override copy closes that gap; combined
with `MAX(attendance_date)` resolution it gives forward propagation with no
resolver change.

## Design

### New SQL constant (in `src/hrms/bioAttUpdation.py`, alongside the `FINAL_*` SQL)

```sql
UPDATE daily_attendance da
JOIN daily_attendance_mod m
  ON  m.eb_id           = da.eb_id
  AND m.bio_id          = da.bio_id
  AND m.attendance_date = da.attendance_date
  AND m.attendance_type = da.attendance_type
SET da.spell                 = COALESCE(m.spell, da.spell),
    da.worked_department_id  = COALESCE(m.worked_department_id,  da.worked_department_id),
    da.worked_designation_id = COALESCE(m.worked_designation_id, da.worked_designation_id),
    da.update_date_time      = NOW()
WHERE da.attendance_date    = :tran_date
  AND da.attendance_source  = 'BIO'
```

Named constant: `FINAL_APPLY_MOD_OVERRIDES_SQL`.

### New helper (in `src/hrms/bioAttUpdation.py`)

```python
def apply_mod_overrides(db: Session, tran_date: str) -> int:
    """Copy manual corrections from daily_attendance_mod into daily_attendance
    for `tran_date`. Matches on eb_id + bio_id + attendance_date +
    attendance_type; overwrites spell / worked_department_id /
    worked_designation_id (COALESCE-protected against NULLs in the mod row),
    restricted to attendance_source='BIO'. Does NOT commit — the caller commits.
    Returns the number of daily_attendance rows updated.
    """
    res = db.execute(FINAL_APPLY_MOD_OVERRIDES_SQL, {"tran_date": tran_date})
    return int(res.rowcount or 0)
```

### Call site

Inside `step3_final_process` (in `src/hrms/bio_att_scheduler.py`), after
`finalize_daily_attendance(...)` and `FINAL_MARK_PROCESSED_SQL`, before the final
`db.commit()`, and only when `not dry_run`:

```python
mod_overrides = apply_mod_overrides(db, tran_date)
db.commit()
result["mod_overrides"] = mod_overrides
```

The `dry_run` early-return path returns `mod_overrides: 0` for shape parity.

Placing the copy inside `step3_final_process` means every caller of the final
process benefits with no extra wiring:

- the automated pipeline (`bio_att_auto_pipeline._run_chain_for_date`),
- the manual scheduler (`bio_att_scheduler.run`),
- the `/bio_att...` final-process route (if it calls `step3_final_process`).

Because the pipeline processes dates in ascending order, the override for date D
is applied before D+1 is resolved, so forward propagation works within a single
multi-date run.

## Edge cases

- **No mod row for a date:** `UPDATE ... JOIN` matches nothing → 0 rows updated,
  `daily_attendance` left as the final process produced it. Safe.
- **Mod row but no matching `attendance_type` in `daily_attendance`:** no match,
  no update. The override only touches rows that exist.
- **Multiple `daily_attendance` rows per `bio_id`+date (working + OT):** the
  `attendance_type` match key distinguishes them; each mod row updates only its
  own `attendance_type` row.
- **Partially-filled mod row (some override columns NULL):** `COALESCE` keeps the
  existing `daily_attendance` value for the NULL columns.
- **Idempotent / re-run safe:** re-applying the same overrides is a no-op beyond
  bumping `update_date_time`.

## Testing

- Unit-level: seed `daily_attendance` + `daily_attendance_mod` for a date, call
  `apply_mod_overrides`, assert spell/dept/desig copied, `attendance_type`
  unchanged, non-BIO rows untouched, NULL mod columns preserved via COALESCE,
  return count correct.
- Integration: run `step3_final_process` (non-dry-run) and assert the result dict
  includes `mod_overrides` and the rows reflect the corrections.

## Out of scope

- No change to dept/desig resolution logic.
- No new `daily_attendance_mod` write path / UI (assumed to already exist).
- No schema/migration changes (`daily_attendance_mod` assumed to exist with
  columns `eb_id`, `bio_id`, `attendance_date`, `attendance_type`, `spell`,
  `worked_department_id`, `worked_designation_id`).
