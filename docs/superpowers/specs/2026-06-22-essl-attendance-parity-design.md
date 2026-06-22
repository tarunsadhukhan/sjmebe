# essl-Parity Rewrite of Bio-Attendance Daily Processing — Design

**Date:** 2026-06-22
**Author:** tarun (with Claude)
**Status:** Draft — awaiting review
**Repo:** `sjmvowerp3be` (FastAPI/Python backend)

## Problem

The biometric-attendance pipeline turns raw device punches (`bio_attendance_table`)
into daily attendance rows (`daily_attendance_basic`, `daily_attendance_process_table`).
Its output diverges from the **eSSL eTrack TrackLite** "Daily Attendance Detailed
Report", which is the customer's source of truth.

Concrete failure (emp `649`, tenant `sjm`):

| Day | eSSL (target) | Current backend |
|-----|---------------|-----------------|
| 20-Jun | **Shift C**, In 17:45 → Out 05:59⁺¹, Work 8:00, OT 4:14 | Shift B, In 17:45 → Out 21:45, Work 3:59 ❌ |
| 21-Jun | **Shift C**, In 17:43 → Out 05:58⁺¹, Work 8:00, OT 4:15 | Shift A, In **05:59** → Out 21:49, fake 245-min break ❌ |

### Root cause

The current logic mutates `device_direction` in the DB through five `_MARK_*`
SQL UPDATEs ([bioAttUpdation.py](../../../src/hrms/bioAttUpdation.py) ~L3440–3580),
force-marking only the first-IN and last-OUT, and decides "night shift" only when
the first-IN hour is `> 21`. Emp 649 clocks in at 17:45, so:

1. The night shift is never recognised → wrong shift (B instead of C).
2. The next-morning OUT punch is never pulled in → wrong out-time / duration.
3. The leftover morning punch (05:59) is consumed by the *next* day as a fresh IN
   → bogus second shift with a fake break.

eSSL instead **groups** the night shift (evening → next morning) and assigns
**strict chronological alternation** `in,out,in,out…`, which is what flips emp
649's 2nd consecutive `out` → `in` and the morning `in` → `out`.

## Goal

Replicate eSSL's Detailed-Report behaviour "exact as feasible", validated against
the eSSL Excel export as a golden dataset (Apr–Jun 2026, ~22.7k present rows).

## Empirically-derived eSSL rules (from the golden set)

Verified against the Excel (`DailyAttendance_DetailedReport (8).xls`, 38,436 rows):

- **InTime = first `in` punch; OutTime = last `out` punch** — matched 22,747/22,747
  and 22,169/22,186 respectively (17 edge cases).
- **Shift band by first-in hour:** 04–07→A, 08–10→GS, 11–16→B, ≥17→C.
- **Cross-midnight C-rule:** a first-in in hours 13–17 whose **last OUT lands next
  morning** is reclassified **C** (verified: hour-17 → C when crossed=2607, B when
  not=99). Scheduled times: A 06–14, B 14–22, C 22–06⁺¹, GS 10–18.
- **Work/OT ≈ span-based:** `work = min(8h, worked)`, `ot = max(0, worked − 8h)`,
  where `worked = span − breaks`. Span-based prediction matched 4,571/16,527 exactly;
  the bulk of misses are ±1–4 min (seconds-rounding) — precise rounding/break
  behaviour to be pinned by the validation loop.
- eSSL **honours the device's physical reader** (device_id 22 = in-reader,
  14 = out-reader) for non-night cases; 629 report rows keep consecutive
  same-direction punches (no universal alternation). Alternation is applied when
  resolving a night-shift crossing.

## Architecture

### New module: `src/hrms/essl_resolver.py` (pure, no DB)

```
resolve_employee_days(punches: list[Punch], *, off_days, holidays) -> list[DailyResult]
```

- **Input:** one employee's raw punches `(log_date: datetime, raw_dir: str,
  device_id: int)` over a window, plus off-day / holiday lookups for the dates.
- **Output:** one `DailyResult` per attendance-day with: `tran_date`, `shift`,
  `sched_in`, `sched_out`, `actual_in`, `actual_out`, `work_minutes`,
  `ot_minutes`, `break_minutes`, `total_minutes`, `late_minutes`,
  `early_going_minutes`, `status`, `punch_records`.
- **No DB access; never mutates `device_direction`.** Fully unit-testable.

### Algorithm

**P1 — grouping + direction (raw punches → labelled sessions):**

1. Sort the employee's punches chronologically across the window.
2. **Session segmentation:** start a new session at an in-ish punch following a
   gap; a session whose first-in is in the evening (first-in hour ≥ ~16) absorbs
   next-morning punches up to a morning cutoff (≈10:00) — the night shift. Each
   session is tagged to the calendar date of its first punch.
3. **Strict chronological alternation within a session:** 1st=in, 2nd=out, 3rd=in…
   Raw `device_direction`/`device_id` are used only as segmentation hints/tie-breakers,
   not as the final label.
4. `actual_in` = first `in`; `actual_out` = last `out`.

**P2 — computation (labelled session → row):**

- **Shift:** first-in-hour bands above, with the cross-midnight C-rule.
- **Work/OT:** `work = min(8h, worked)`, `ot = max(0, worked − 8h)`,
  `worked = span − breaks` (intermediate in/out pairs are breaks).
- **late_by** = `max(0, actual_in − sched_in)`;
  **early_going** = `max(0, sched_out − actual_out)`.
- **No-OutPunch:** session with only an IN → synthesize OUT at scheduled end,
  OT=0, status `Present (No OutPunch)` (mirrors eSSL `(SE)` marker).
- **Status:** Present / Present (No OutPunch) / weekly-off & holiday & off-day
  variants (`WeeklyOff Present`, `Holiday Present`, `Off Day Present`) from the
  existing `tbl_offday_mst` / holiday lookups. The odd `�Present` rows (191) are
  to be identified during validation and documented.

The two halves are independent: **P2 is validated directly against the Excel**
(it consumes eSSL's own resolved in/out + shift); **P1 is validated by reproducing
eSSL's punch_records direction string from raw data**.

### Integration

- [`_process_bprocess_day`](../../../src/hrms/bioAttUpdation.py) becomes a thin
  adapter: widen `FETCH_BPROCESS_PUNCHES_SQL` to fetch a per-employee window
  (D−1 evening … D+1 morning), call `resolve_employee_days`, write
  `daily_attendance_basic` + the spell row. **Delete the five `_MARK_*` UPDATEs**,
  `_bprocess_shift_for`, and `_split_worked_break_secs` (folded into the resolver).
- The pipeline ([bio_att_auto_pipeline.py](../../../src/hrms/bio_att_auto_pipeline.py))
  is **untouched** — it still calls `bprocess_core` → `b_atten_core`. Idempotent
  delete-then-rebuild per date is preserved. The look-back/ahead window makes a
  date resolve identically whether processed alone or in a batch.

### Sub-shifts (A1, A2, B1, B2, C)

Sub-shifts are a **VoWERP-internal spell concept** produced downstream in
[`b_atten_core`](../../../src/hrms/bioAttUpdation.py#L4280) via
[`_spell_label_for_b_atten`](../../../src/hrms/bioAttUpdation.py#L3253), which splits
each day into R (regular) and O (overtime) rows in `daily_attendance_process_table`.
**No eSSL report (Detailed/Basic/Summary) contains sub-shift labels** — eSSL only
emits base A/B/C/GS.

**Design decision:** keep the existing bucket+intime spell-derivation mechanism,
retarget its output set to exactly **{A1, A2, B1, B2, C}** (collapsing/removing the
current extras such as B, C1, C2, O as appropriate), and validate it with unit tests
against the spellcalculation rules.

> **ASSUMPTION — confirm at review:** the source of truth for the A1/A2/B1/B2/C band
> rules is the existing spellcalculation logic in the code. If a separate spell spec
> document exists, point to it and the resolver's sub-shift tests will target that
> instead.

## Validation harness (committed as permanent tests)

- **Golden fixture:** a committed JSON pairing raw punches (pulled read-only from
  `sjm`) with eSSL's expected output (from the Excel), keyed by `(emp_code, date)`.
  No live DB needed in CI. Stored under `tests/hrms/fixtures/`.
- **P2 tests:** eSSL resolved in/out + shift → assert work/ot/late/early/status.
- **P1 tests:** raw punches → assert direction sequence + in/out vs eSSL punch_records.
- **End-to-end:** raw punches → full `DailyResult` → assert vs eSSL row.
- **Scorecard:** a runnable per-field match-rate report that buckets residual
  mismatches, so "exact as feasible" is measured. Iterate until the rate plateaus;
  documented residuals (629 non-alternating rows, manual entries, `�Present`)
  become known exceptions here.

## Out of scope (YAGNI)

- Changing the fetch/upload paths or the high-water-mark scheduling logic.
- Changing the `daily_attendance_basic` / `daily_attendance_process_table` schemas.
- Any UI change.

## Risks

- **Reverse-engineering completeness:** rare eSSL quirks may resist exact match;
  mitigated by the scorecard + documented known-exceptions.
- **Night-shift window edges:** the morning cutoff (~10:00) and evening threshold
  (~16:00) are tunable parameters; the harness fixes them empirically.
- **Production data:** all DB use during development is read-only; the only writes
  are the existing idempotent `daily_attendance_*` rebuilds via the normal pipeline.
