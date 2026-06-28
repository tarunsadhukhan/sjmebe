"""compare_attendance_excel.py — reconcile the biometric vendor's Excel report
against daily_attendance_process_table for a tenant (default: sjm).

The Excel (DailyAttendance_Detailed_SortedByEcode_Date.xlsx) is the device
vendor's truth: one row per (E.Code, Date) with actual in/out, Work Dur., OT,
Shift and Status. daily_attendance_process_table is what our pipeline built from
the SAME punches — 0..N spell rows per (employee, date).

DB model (verified against live sjm data):
  * Ot_hours is ~0; overtime / off-day work is a SEPARATE spell row carrying
    attendance_type='O' with the hours in Working_hours.
  * So  Excel Work Dur. <-> sum(Working_hours where type='R')
        Excel OT        <-> sum(Working_hours where type='O') (+ any Ot_hours)
  * check_in/check_out are the first/last punch -> their time-of-day should equal
    the vendor's A.InTime/A.OutTime to the minute when the pipeline is correct.
  * Hours are slabbed in the pipeline (>=7->8, [3,7)->4, <3->0); the vendor's are
    exact. We slab the vendor value with the same rule before comparing.

Output workbook (default e:\\downloads\\Attendance_Compare.xlsx):
  Detail      — every Excel row, vendor vs DB side by side, per-row reason
  Extra in DB — process-table (emp_code, date) pairs absent from the Excel
  Summary     — counts by match status and by reason

Run:
  python -m scripts.compare_attendance_excel              # full run
  python -m scripts.compare_attendance_excel --selftest   # parser/slab asserts only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from src.hrms.bio_att_scheduler import make_session  # noqa: E402  (loads env/database.env)

DEFAULT_EXCEL = r"e:\downloads\DailyAttendance_Detailed_SortedByEcode_Date.xlsx"
DEFAULT_OUT = r"e:\downloads\Attendance_Compare.xlsx"


# ── pure helpers (self-tested) ──────────────────────────────────────────────

def hhmm_to_hours(v) -> float:
    """'8:00' / '4:03' / '12:03:18' -> decimal hours. Blank / NaN -> 0.0."""
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return 0.0
    p = s.split(":")
    try:
        h = int(p[0])
        m = int(p[1]) if len(p) > 1 else 0
        sec = int(p[2]) if len(p) > 2 else 0
    except ValueError:
        return 0.0
    return round(h + m / 60 + sec / 3600, 4)


def bucket_hours(h: float) -> float:
    """Pipeline's hour slabbing — mirrors bioAttUpdation.py:1616-1618."""
    if h >= 7:
        return 8.0
    if h >= 3:
        return 4.0
    return 0.0


def parse_clock(v) -> str:
    """'05:54:22' -> '05:54' (minute precision). Blank / NaN -> ''."""
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return ""
    p = s.split(":")
    try:
        return f"{int(p[0]):02d}:{int(p[1]):02d}"
    except (ValueError, IndexError):
        return ""


def norm_code(x) -> str:
    """Canonicalise an employee code so the vendor's zero-padded '00003' matches
    the DB's bare '3'. Non-numeric codes (e.g. 'C0000') are left as-is."""
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return ""
    return (s.lstrip("0") or "0") if s.isdigit() else s


def clean_status(v) -> str:
    """Drop vendor mojibake (non-ASCII replacement chars) and collapse spaces.
    '\\ufffdPresent' -> 'Present'; 'WeeklyOff \\ufffdPresent' -> 'WeeklyOff Present'."""
    s = re.sub(r"[^\x20-\x7E]", "", str(v or ""))
    return re.sub(r"\s+", " ", s).strip()


def selftest() -> None:
    assert hhmm_to_hours("8:00") == 8.0
    assert hhmm_to_hours("") == 0.0
    assert hhmm_to_hours("nan") == 0.0
    assert hhmm_to_hours("12:03:18") == round(12 + 3 / 60 + 18 / 3600, 4)
    assert bucket_hours(hhmm_to_hours("8:00")) == 8.0
    assert bucket_hours(hhmm_to_hours("7:37")) == 8.0
    assert bucket_hours(hhmm_to_hours("4:03")) == 4.0
    assert bucket_hours(hhmm_to_hours("3:58")) == 4.0
    assert bucket_hours(hhmm_to_hours("2:30")) == 0.0
    assert parse_clock("05:54:22") == "05:54"
    assert parse_clock("") == ""
    assert clean_status("�Present") == "Present"
    assert clean_status("WeeklyOff �Present") == "WeeklyOff Present"
    assert clean_status("Present  (No OutPunch)") == "Present (No OutPunch)"
    assert norm_code("00003") == "3"
    assert norm_code("3") == "3"
    assert norm_code("10408") == "10408"
    assert norm_code("C0000") == "C0000"
    print("selftest: OK")


# ── load Excel ──────────────────────────────────────────────────────────────

def load_excel(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Attendance", dtype=str)
    out = pd.DataFrame()
    out["emp_code"] = df["E. Code"].map(norm_code)
    out["date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y").dt.strftime("%Y-%m-%d")
    out["vendor_name"] = df["Name"].astype(str).str.strip()
    out["status"] = df["Status"].map(clean_status)
    out["shift"] = df["Shift"].astype(str).str.strip()
    out["ex_in"] = df["A. InTime"].map(parse_clock)
    out["ex_out"] = df["A. OutTime"].map(parse_clock)
    out["ex_work_h"] = df["Work Dur."].map(hhmm_to_hours)
    out["ex_ot_h"] = df["OT"].map(hhmm_to_hours)
    out["excel_punched"] = out["ex_in"] != ""
    return out


# ── load + aggregate DB ─────────────────────────────────────────────────────

DB_FETCH_SQL = text(
    """
    SELECT o.emp_code                                          AS emp_code,
           DATE(d.attendance_date)                             AS attendance_date,
           d.spell_name                                        AS spell_name,
           d.attendance_type                                   AS attendance_type,
           d.check_in                                          AS check_in,
           d.check_out                                         AS check_out,
           d.Working_hours                                     AS working_hours,
           d.Ot_hours                                          AS ot_hours,
           TRIM(CONCAT_WS(' ', p.first_name,
                               IFNULL(p.middle_name, ''),
                               IFNULL(p.last_name, ''))) AS emp_name
      FROM daily_attendance_process_table d
      LEFT JOIN hrms_ed_official_details o ON o.eb_id = d.eb_id
      LEFT JOIN hrms_ed_personal_details p ON p.eb_id = d.eb_id
     WHERE d.attendance_date BETWEEN :d1 AND :d2
    """
)


def aggregate_db(db, d1: str, d2: str) -> dict:
    """One row per (emp_code, date): min in, max out, regular/off hours split by
    attendance_type, spell + type sets, row count."""
    rows = db.execute(DB_FETCH_SQL, {"d1": d1, "d2": d2}).mappings().fetchall()
    agg: dict = {}
    for r in rows:
        emp_code = None if r["emp_code"] is None else norm_code(r["emp_code"])
        d = r["attendance_date"]
        key = (emp_code, d.isoformat() if hasattr(d, "isoformat") else str(d))
        a = agg.setdefault(
            key,
            {"emp_name": r["emp_name"] or "", "in": None, "out": None,
             "reg": 0.0, "o": 0.0, "spells": set(), "types": set(), "n": 0},
        )
        a["n"] += 1
        ci, co = r["check_in"], r["check_out"]
        if ci is not None:
            a["in"] = ci if a["in"] is None else min(a["in"], ci)
        if co is not None:
            a["out"] = co if a["out"] is None else max(a["out"], co)
        wh = float(r["working_hours"] or 0)
        ot = float(r["ot_hours"] or 0)
        t = (r["attendance_type"] or "").strip().upper()
        if t == "O":
            a["o"] += wh
        else:  # 'R', 'P' or unknown -> treated as regular work
            a["reg"] += wh
        a["o"] += ot
        if r["spell_name"]:
            a["spells"].add(str(r["spell_name"]))
        if t:
            a["types"].add(t)
        if not a["emp_name"] and r["emp_name"]:
            a["emp_name"] = r["emp_name"]
    return agg


# ── comparison ──────────────────────────────────────────────────────────────

def evaluate(ex, a, official_codes):
    """Return (overall_match, reason_category, reason) for one Excel row vs its DB
    aggregate `a` (None when no DB row exists). `reason_category` is a short rollup
    key for the Summary; `reason` is the full per-row detail."""
    notes: list[str] = []
    cat = None  # first (highest-priority) mismatch category
    punched = ex["excel_punched"]
    offday = "weeklyoff" in ex["status"].lower()
    has_db = a is not None and a["n"] > 0

    def flag(category, note):
        nonlocal cat
        if cat is None:
            cat = category
        notes.append(note)

    # ── presence reconciliation ──
    if not has_db:
        if not punched:
            return "OK", "match (absent both sides)", "no punches in vendor report; no process-table row (expected)"
        if ex["emp_code"] not in official_codes:
            return "MISMATCH", "unmapped employee", "vendor shows punches but emp_code not in employee master (active=1) - attendance cannot be built"
        return "MISMATCH", "missing process row", "vendor shows punches but no process-table row (punch not ingested / eb_id unresolved / spell window unmatched)"
    if not punched:
        return "MISMATCH", "vendor absent, db has row", f"vendor=no punch ({ex['status'] or 'blank'}) but process table has {a['n']} row(s)"

    # ── both sides present — field comparison ──
    db_in = a["in"].strftime("%H:%M") if a["in"] is not None else ""
    db_out = a["out"].strftime("%H:%M") if a["out"] is not None else ""

    if ex["ex_in"] and db_in and ex["ex_in"] != db_in:
        flag("in-time differs", f"in-time differs (vendor {ex['ex_in']} vs db {db_in})")
    if ex["ex_out"] == "":
        notes.append("vendor has no out-punch")
    elif db_out and ex["ex_out"] != db_out:
        flag("out-time differs", f"out-time differs (vendor {ex['ex_out']} vs db {db_out})")

    # hours, slab-aware (regular vs off/OT)
    ex_work_b = bucket_hours(ex["ex_work_h"])
    ex_ot_b = bucket_hours(ex["ex_ot_h"])
    if ex_work_b != round(a["reg"], 2):
        flag("working hrs differ", f"working hrs differ (vendor {ex['ex_work_h']:.2f}->slab {ex_work_b} vs db {a['reg']:.2f})")
    elif abs(ex["ex_work_h"] - a["reg"]) > 0.01:
        notes.append("working hrs match after 0/4/8 slabbing")
    if ex_ot_b != round(a["o"], 2):
        flag("OT/off hrs differ", f"OT/off hrs differ (vendor {ex['ex_ot_h']:.2f}->slab {ex_ot_b} vs db {a['o']:.2f})")
    elif abs(ex["ex_ot_h"] - a["o"]) > 0.01:
        notes.append("OT/off hrs match after 0/4/8 slabbing")

    # off-day classification (type O expected on a weekly-off worked day)
    if offday:
        notes.append("weekly-off worked: vendor books hours as OT, pipeline books them under attendance_type=O")
        if "O" not in a["types"]:
            flag("weekly-off, no O row", "but db has no attendance_type=O row")

    # shift vs spell — informational (B1/A2 sub-spells make exact match rare)
    shift = ex["shift"]
    if shift and shift not in ("NS", "GS"):
        initials = {s[0].upper() for s in a["spells"] if s}
        if shift[0].upper() not in initials:
            notes.append(f"shift/spell differ (vendor {shift} vs db {sorted(a['spells'])})")

    if cat is not None:
        return "MISMATCH", cat, "; ".join(notes)
    if not notes:
        return "OK", "match", "all fields match"
    if offday:
        return "OK", "match (weekly-off O-model)", "; ".join(notes)
    if any("slabbing" in n for n in notes):
        return "OK", "match (after slabbing)", "; ".join(notes)
    return "OK", "match", "; ".join(notes)


def build_detail(excel_df, agg, official_codes):
    used_keys = set()
    recs = []
    for ex in excel_df.to_dict("records"):
        key = (ex["emp_code"], ex["date"])
        a = agg.get(key)
        if a is not None:
            used_keys.add(key)
        status, category, reason = evaluate(ex, a, official_codes)
        recs.append({
            "emp_code": ex["emp_code"],
            "emp_name": (a["emp_name"] if a else "") or ex["vendor_name"],
            "date": ex["date"],
            "status": ex["status"],
            "shift": ex["shift"],
            "vendor_in": ex["ex_in"],
            "db_in": a["in"].strftime("%H:%M") if a and a["in"] is not None else "",
            "vendor_out": ex["ex_out"],
            "db_out": a["out"].strftime("%H:%M") if a and a["out"] is not None else "",
            "vendor_work_h": round(ex["ex_work_h"], 2),
            "db_regular_h": round(a["reg"], 2) if a else "",
            "vendor_ot_h": round(ex["ex_ot_h"], 2),
            "db_off_ot_h": round(a["o"], 2) if a else "",
            "db_spells": ",".join(sorted(a["spells"])) if a else "",
            "db_types": ",".join(sorted(a["types"])) if a else "",
            "db_rows": a["n"] if a else 0,
            "overall_match": status,
            "reason_category": category,
            "reason": reason,
        })
    return pd.DataFrame(recs), used_keys


def build_extra(agg, used_keys):
    recs = []
    for (emp_code, date), a in agg.items():
        if (emp_code, date) in used_keys:
            continue
        recs.append({
            "emp_code": emp_code if emp_code is not None else "(eb_id unmapped)",
            "emp_name": a["emp_name"],
            "date": date,
            "db_in": a["in"].strftime("%H:%M") if a["in"] is not None else "",
            "db_out": a["out"].strftime("%H:%M") if a["out"] is not None else "",
            "db_regular_h": round(a["reg"], 2),
            "db_off_ot_h": round(a["o"], 2),
            "db_spells": ",".join(sorted(a["spells"])),
            "db_types": ",".join(sorted(a["types"])),
            "db_rows": a["n"],
            "reason": "process-table row(s) with no matching (emp_code, date) in vendor Excel",
        })
    return pd.DataFrame(recs).sort_values(["date", "emp_code"]) if recs else pd.DataFrame()


def build_summary(detail, extra):
    overview = pd.DataFrame({
        "metric": ["vendor rows", "OK", "MISMATCH", "extra-in-DB (emp,date) pairs"],
        "count": [len(detail),
                  int((detail["overall_match"] == "OK").sum()),
                  int((detail["overall_match"] == "MISMATCH").sum()),
                  len(extra)],
    })
    rc = (detail.groupby(["overall_match", "reason_category"]).size()
          .reset_index(name="count").sort_values(["overall_match", "count"],
                                                  ascending=[True, False]))
    return overview, rc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--excel", default=DEFAULT_EXCEL)
    p.add_argument("--tenant", default="sjm")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--selftest", action="store_true", help="run parser/slab asserts and exit")
    args = p.parse_args(argv)

    if args.selftest:
        selftest()
        return

    selftest()  # cheap guard before doing real work
    excel_df = load_excel(args.excel)
    d1, d2 = excel_df["date"].min(), excel_df["date"].max()
    print(f"Excel rows read: {len(excel_df)}  date range: {d1} .. {d2}")

    db = make_session(args.tenant)
    try:
        agg = aggregate_db(db, d1, d2)
        official_codes = {
            norm_code(r[0])
            for r in db.execute(
                text("SELECT emp_code FROM hrms_ed_official_details WHERE active=1 AND emp_code IS NOT NULL")
            ).fetchall()
        }
    finally:
        db.close()
    print(f"DB (emp,date) aggregates: {len(agg)}   employee-master codes: {len(official_codes)}")

    detail, used_keys = build_detail(excel_df, agg, official_codes)
    extra = build_extra(agg, used_keys)
    overview, reason_counts = build_summary(detail, extra)

    with pd.ExcelWriter(args.out, engine="openpyxl") as xw:
        detail.to_excel(xw, sheet_name="Detail", index=False)
        (extra if not extra.empty else pd.DataFrame([{"info": "none"}])).to_excel(
            xw, sheet_name="Extra in DB", index=False)
        overview.to_excel(xw, sheet_name="Summary", index=False, startrow=0)
        reason_counts.to_excel(xw, sheet_name="Summary", index=False, startrow=len(overview) + 3)

    ok = int((detail["overall_match"] == "OK").sum())
    mm = int((detail["overall_match"] == "MISMATCH").sum())
    print(f"Detail: {len(detail)} rows  ->  OK={ok}  MISMATCH={mm}")
    print(f"Extra in DB: {len(extra)} (emp,date) pairs")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
