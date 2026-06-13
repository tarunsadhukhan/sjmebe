# Automated Hourly Bio-Attendance Pipeline — Design

**Date:** 2026-06-13
**Repo:** `sjmvowerp3be` (FastAPI backend)
**Status:** Approved design — ready for implementation plan

## Problem

Biometric device punches land in the tenant's `bio_attendance_table` roughly
once per hour (the table is populated by an **external** process — this feature
does NOT fetch from the device). Today, turning those raw punches into rows in
`daily_attendance` is a **manual** sequence of dialog clicks on the Bio
Attendance Updation page:

  Etrack Process (D) → Bprocess → B Atten → Final Process

We want this to happen automatically: every hour, process any punches that have
not yet been processed, and — critically — **re-process a date when a later
punch arrives** so working hours are recomputed once the OUT punch is present.

### The late-OUT requirement (core scenario)

An employee's IN punch at 06:00 may be processed by the 07:00 run while the OUT
punch has not yet arrived. The OUT punch lands later (e.g. 14:00 or 18:00). The
pipeline must pick that up on a later run and recompute `check_out` and working
hours for that date.

This already works mechanically because `_process_bprocess_day` **rebuilds the
entire day from scratch** (deletes the day's rows, then re-derives from all
punches currently present for that date):

- With only an IN punch it writes status `Present (No OutPunch)` and a
  synthesized span.
- Once the OUT punch exists and the date is re-processed, it computes the real
  IN/OUT pair, working hours, and OT.
- For **night shifts**, the OUT punch lands on `tran_date + 1`; the bprocess
  punch query for `tran_date` already pulls next-day early-morning punches to
  close the night shift.

So the only thing the new job must guarantee is: **whenever new punches arrive,
re-run the full chain for the affected date(s)** — and for a night-shift OUT
that arrives the next morning, also re-run the *previous* day.

## Goals

- Run the bprocess chain automatically every hour for one configured
  tenant/branch.
- Skip runs when there are no new punches.
- Re-process a date when later punches (especially the OUT punch) arrive.
- Reuse existing processing logic — no duplicated business rules, no HTTP
  self-calls.
- Be opt-in and configurable via environment variables; off by default.

## Non-Goals (YAGNI)

- Multi-tenant / multi-branch auto-discovery (single env-driven entry for now).
- Fetching punches from the Etrack SQL Server (the table is populated
  externally; the existing `bio_att_scheduler.py` CLI still covers SQL-Server
  pull when needed).
- Multi-worker safety beyond a documented caveat (see Risks).
- A UI for configuring or monitoring the job.

## Decisions (from brainstorming)

| Question | Decision |
|----------|----------|
| Where does it run | In-app **APScheduler** job inside the FastAPI process |
| Cadence | **Every 1 hour** (`IntervalTrigger`, interval configurable) |
| Idle run (no new punches) | **Skip entirely** |
| Scope | **Single tenant/branch**, env-driven |
| Data ingestion | **None** — table populated externally; job only processes |
| Chain | **All four**: etrack(D) → bprocess → b_atten → final |
| New-data detection | High-water mark on `bio_att_id` (auto-increment PK) |

## Architecture

### Components

1. **`src/hrms/bio_att_auto_pipeline.py`** (new)
   - State helpers for the high-water mark table `bio_att_auto_state`.
   - `run_once(tenant, branch_id, company_id) -> dict` — one pipeline pass
     (detect new data → compute dates → run chain per date → advance
     high-water). Also callable manually for verification.
   - `start_scheduler()` / `stop_scheduler()` — create/own the
     `AsyncIOScheduler`, register the hourly job, behind the env flag.

2. **`src/hrms/bioAttUpdation.py`** (edit — refactor only)
   - Extract the inline logic of the `bio_att_etrack_process_d` route into a
     reusable `etrack_process_d_core(db, tran_date) -> dict`.
   - Extract the inline logic of the `bio_att_b_atten` route into a reusable
     `b_atten_core(db, tran_date) -> dict`.
   - Both existing HTTP routes call the extracted helpers — **route behavior
     unchanged**.

3. **`src/main.py`** (edit)
   - In the existing `@app.on_event("startup")` / `shutdown` hooks, call
     `start_scheduler()` / `stop_scheduler()` (guarded by the env flag).

4. **`requirements.txt`** (edit)
   - Add `APScheduler` (currently not installed).

### Reuse map (no duplicated business rules)

| Chain step | Reused implementation |
|------------|----------------------|
| etrack(D)  | new `etrack_process_d_core` (extracted from route) |
| bprocess   | `_process_bprocess_day` + the resolve block (shared with the route) |
| b_atten    | new `b_atten_core` (extracted from route) |
| final      | `step3_final_process` from `bio_att_scheduler.py` |

Tenant MySQL session reuses `bio_att_scheduler.make_session(tenant)`.

## Configuration (environment variables)

Loaded from the same env files as the app.

| Var | Default | Meaning |
|-----|---------|---------|
| `BIO_ATT_AUTO_ENABLED` | `false` | Master on/off. Scheduler only starts when true. |
| `BIO_ATT_AUTO_TENANT` | — | Tenant/subdomain = MySQL DB name (e.g. `dev3`). |
| `BIO_ATT_AUTO_BRANCH` | — | `branch_id` for `daily_attendance`. |
| `BIO_ATT_AUTO_COMPANY_ID` | `2` | Company id (kept for parity / future use). |
| `BIO_ATT_AUTO_INTERVAL_MIN` | `60` | Interval between runs, minutes. |

If `ENABLED` is true but `TENANT`/`BRANCH` are missing, log an error and do not
start the job.

## Data: high-water state table

Created in the tenant DB on first run (idempotent `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS bio_att_auto_state (
    branch_id        INT          NOT NULL PRIMARY KEY,
    last_bio_att_id  BIGINT       NOT NULL DEFAULT 0,
    last_run_at      DATETIME     NULL
);
```

`bio_att_id` is the auto-increment PK of `bio_attendance_table`, so it is
monotonic and reliable even when `bio_att_log_id` arrives blank/0 (it is filled
later by the etrack(D) pre-step). That is why detection keys on `bio_att_id`,
not `bio_att_log_id`.

> Implementation note to verify during the plan: confirm `bio_att_id` is the
> auto-increment PK of `bio_attendance_table` (strongly indicated by existing
> `ORDER BY bio_att_id DESC` usage and the `id = bio_att_id` mapping in the UI).

## Control Flow — `run_once`

```
1. db = make_session(tenant)
2. Ensure bio_att_auto_state exists; read last_bio_att_id for branch (default 0).
3. current_max = SELECT MAX(bio_att_id) FROM bio_attendance_table
4. If current_max is NULL or current_max <= last_bio_att_id:
       log "no new data, skipping"; return {skipped: true}
5. new_dates = SELECT DISTINCT DATE(log_date)
               FROM bio_attendance_table
               WHERE bio_att_id > last_bio_att_id AND log_date IS NOT NULL
6. dates_to_process = sorted( new_dates ∪ { d - 1 day for d in new_dates } )
7. For each tran_date in dates_to_process:   # per-date error isolation
       try:
           etrack_process_d_core(db, tran_date)
           # bprocess: resolve + _process_bprocess_day (off-day aware)
           run_bprocess(db, tran_date)
           b_atten_core(db, tran_date)
           step3_final_process(db, tran_date=tran_date, branch_id=branch_id)
       except Exception:
           log.error(...); db.rollback(); continue
8. UPDATE bio_att_auto_state SET last_bio_att_id = current_max,
                                  last_run_at = NOW()  WHERE branch_id = :b
9. Close db. Return summary {processed_dates, max_id}.
```

The `−1 day` term (step 6) is what closes a night shift whose OUT punch arrives
the following morning. Re-processing an unchanged date is harmless because every
step deletes-then-rebuilds the date.

## Error handling & logging

- All output under a dedicated `bio_att_auto` logger.
- Per-date `try/except`: one failing date does not block the others; the failed
  date is rolled back and logged; the high-water mark still advances at the end
  (a transient failure will be retried only if new punches later land for that
  date — acceptable for v1; noted as a known limitation).
- Job registered with `max_instances=1`, `coalesce=True` so a slow run never
  overlaps or stacks missed runs.

## Risks / Caveats

- **Multiple uvicorn workers**: an in-process scheduler starts once per worker,
  so the job would fire N times. Current deployment is single-worker. Documented
  in code; if multi-worker is ever needed, gate with a DB lock or move to the
  CLI + OS scheduler. (Out of scope for v1.)
- **High-water advances past a failed date**: if a date errors, it won't be
  retried until new punches arrive for it. Acceptable for v1; revisit if it
  bites.
- **APScheduler new dependency**: must be added and installed in the runtime
  environment (and bundled if a frozen `dist/` build is produced).

## Testing & verification

- Unit tests (no live DB) for the pure logic:
  - date-set computation: `new_dates ∪ {d−1}` from a set of new rows.
  - skip decision when `current_max <= last_bio_att_id`.
- Manual verification on `dev3`:
  1. Set env vars, `BIO_ATT_AUTO_ENABLED=true`, short interval.
  2. Insert an IN-only punch for today → confirm `daily_attendance` gets a
     `Present (No OutPunch)` row.
  3. Insert the matching OUT punch → confirm next run recomputes check-out and
     working hours.
  4. Insert a night-shift OUT on the next day → confirm the prior day's night
     shift closes.
- `run_once(...)` callable directly for a one-shot manual run.

## Files touched

| File | Change |
|------|--------|
| `src/hrms/bio_att_auto_pipeline.py` | NEW — state, `run_once`, scheduler start/stop |
| `src/hrms/bioAttUpdation.py` | extract `etrack_process_d_core`, `b_atten_core`; routes call them |
| `src/main.py` | start/stop scheduler in lifecycle hooks (env-gated) |
| `requirements.txt` | add `APScheduler` |
