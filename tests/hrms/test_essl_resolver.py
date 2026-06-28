"""Unit tests for the pure essl_resolver (no DB).

Cases use real punch sequences from tenant `sjm` whose expected output was read
straight from the eSSL "Daily Attendance Detailed Report" Excel, so they pin the
behaviours that motivated the rewrite:

  * night-shift grouping (evening IN + next-morning OUT) -> Shift C
  * the "two consecutive OUTs -> last treated as IN" reconciliation (emp 649)
  * a long day shift whose only two punches are >10h apart is NOT split (11858)
  * a pure night worker whose every calendar day holds a morning exit + an
    evening start is split correctly (481)
  * positional in/out (first punch / last punch), minute-truncated durations
  * off-day -> all-OT, and the no-out-punch synthesis
"""

from datetime import datetime

from src.hrms.essl_resolver import (
    Punch,
    resolve_employee_days,
    resolve_session,
    segment_sessions,
)


def _p(s, dev):
    """Build a Punch from 'YYYY-MM-DD HH:MM:SS' and a device id (22=in,14=out)."""
    return Punch(datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
                 "in" if dev == 22 else "out", dev)


# ── emp 649: night shift with two consecutive OUTs ────────────────────────────

def test_emp649_night_shift_two_outs():
    # Raw device feed for 2026-06-20 (eSSL: C, in 17:45:27 -> out 05:59:25,
    # work 8:00, OT 4:14). The 21:45:09 + 21:45:22 are BOTH on the OUT reader.
    punches = [
        _p("2026-06-20 17:45:27", 22),
        _p("2026-06-20 21:45:09", 14),
        _p("2026-06-20 21:45:22", 14),
        _p("2026-06-21 05:59:25", 22),
    ]
    days = resolve_employee_days(punches)
    assert len(days) == 1
    d = days[0]
    assert d.tran_date.isoformat() == "2026-06-20"
    assert d.shift == "C"
    assert d.actual_in == datetime(2026, 6, 20, 17, 45, 27)
    assert d.actual_out == datetime(2026, 6, 21, 5, 59, 25)
    # span 17:45 -> 05:59 (+1d) = 12h14m = 734 min; eSSL: work 8:00, OT 4:14.
    assert d.total_minutes == 734
    assert d.work_minutes == 480
    assert d.ot_minutes == 254


# ── emp 11858: long day shift, only two punches >10h apart, must NOT split ─────

def test_emp11858_long_day_not_split():
    punches = [
        _p("2026-04-01 07:43:54", 22),
        _p("2026-04-01 17:56:54", 14),
    ]
    days = resolve_employee_days(punches)
    assert len(days) == 1
    d = days[0]
    assert d.shift == "A"
    assert d.actual_in == datetime(2026, 4, 1, 7, 43, 54)
    assert d.actual_out == datetime(2026, 4, 1, 17, 56, 54)
    assert d.total_minutes == 613  # 10:13 (minute-truncated, eSSL match)


# ── emp 481: pure night worker — morning exit + evening start on each day ──────

def test_emp481_night_worker_split_by_day():
    # 31-Mar morning exit (prev night), 31-Mar evening start, 01-Apr morning exit.
    punches = [
        _p("2026-03-31 21:46:07", 22),
        _p("2026-04-01 05:54:50", 14),
        _p("2026-04-01 21:44:31", 22),
        _p("2026-04-02 05:54:10", 14),
    ]
    days = {d.tran_date.isoformat(): d for d in resolve_employee_days(punches)}
    # Two night sessions, each evening IN paired with the NEXT morning OUT.
    assert days["2026-03-31"].shift == "C"
    assert days["2026-03-31"].actual_in == datetime(2026, 3, 31, 21, 46, 7)
    assert days["2026-03-31"].actual_out == datetime(2026, 4, 1, 5, 54, 50)
    assert days["2026-04-01"].actual_in == datetime(2026, 4, 1, 21, 44, 31)
    assert days["2026-04-01"].actual_out == datetime(2026, 4, 2, 5, 54, 10)


# ── positional in/out: first punch is IN, last is OUT, regardless of reader ────

def test_positional_in_out_ignores_device_label():
    # Day shift where the device mislabels a mid punch; in/out stay positional.
    punches = [
        _p("2026-05-01 06:00:00", 14),   # first punch, OUT reader, still the IN
        _p("2026-05-01 14:05:00", 22),   # last punch, IN reader, still the OUT
    ]
    d = resolve_employee_days(punches)[0]
    assert d.actual_in == datetime(2026, 5, 1, 6, 0, 0)
    assert d.actual_out == datetime(2026, 5, 1, 14, 5, 0)


# ── shift bands ───────────────────────────────────────────────────────────────

def test_shift_bands():
    def shift(hhmm):
        s = resolve_employee_days([
            _p(f"2026-05-01 {hhmm}:00", 22),
            _p(f"2026-05-01 {hhmm}:00", 14),  # same minute -> 0-dur, just for shift
        ])
        return s[0].shift if s else None
    assert shift("06:00") == "A"
    assert shift("09:30") == "GS"
    assert shift("13:30") == "B"   # afternoon, same-day -> B (no midnight cross)


def test_evening_start_crossing_midnight_is_C():
    d = resolve_employee_days([
        _p("2026-05-01 17:30:00", 22),
        _p("2026-05-02 02:00:00", 14),
    ])[0]
    assert d.shift == "C"


def test_evening_start_same_night_is_B():
    d = resolve_employee_days([
        _p("2026-05-01 17:30:00", 22),
        _p("2026-05-01 21:30:00", 14),
    ])[0]
    assert d.shift == "B"


# ── break-aware duration ──────────────────────────────────────────────────────

def test_break_minutes_subtracted_from_worked():
    # 06:00 in, 10:00 out, 11:00 in, 15:00 out -> 1h break; span 9h, worked 8h.
    d = resolve_employee_days([
        _p("2026-05-01 06:00:00", 22),
        _p("2026-05-01 10:00:00", 14),
        _p("2026-05-01 11:00:00", 22),
        _p("2026-05-01 15:00:00", 14),
    ])[0]
    assert d.break_minutes == 60
    assert d.total_minutes == 8 * 60  # worked = span(540) - break(60) = 480


# ── off day -> all OT ─────────────────────────────────────────────────────────

def test_off_day_all_overtime():
    session = [
        _p("2026-05-01 06:00:00", 22),
        _p("2026-05-01 14:00:00", 14),
    ]
    d = resolve_session(session, is_off_day=True)
    assert d.work_minutes == 0
    assert d.ot_minutes == 480
    assert "Off Day" in d.status


# ── no out punch -> synthesized, no OT ────────────────────────────────────────

def test_no_out_punch():
    d = resolve_employee_days([_p("2026-05-01 06:05:00", 22)])[0]
    assert d.actual_out is None
    assert d.ot_minutes == 0
    assert "No OutPunch" in d.status


# ── near-duplicate punches (<=2 min apart) collapse to one event ──────────────

def test_near_duplicate_punches_within_2min_collapse():
    # A double-tap at clock-in (06:00, 06:01, 06:02) is one event: no spurious
    # break / short-out; worked = the full 06:00 -> 14:00 span.
    d = resolve_employee_days([
        _p("2026-05-01 06:00:00", 22),
        _p("2026-05-01 06:01:00", 14),   # 1 min after kept 06:00 -> dropped
        _p("2026-05-01 06:02:00", 22),   # 2 min after kept 06:00 -> dropped
        _p("2026-05-01 14:00:00", 14),
    ])[0]
    assert d.actual_in == datetime(2026, 5, 1, 6, 0, 0)
    assert d.actual_out == datetime(2026, 5, 1, 14, 0, 0)
    assert d.break_minutes == 0
    assert d.total_minutes == 480


def test_punches_more_than_2min_apart_are_kept():
    # A genuine 3-minute break is preserved (not collapsed).
    d = resolve_employee_days([
        _p("2026-05-01 06:00:00", 22),
        _p("2026-05-01 10:00:00", 14),
        _p("2026-05-01 10:03:00", 22),   # 3 min after kept 10:00 -> kept
        _p("2026-05-01 14:00:00", 14),
    ])[0]
    assert d.break_minutes == 3
    assert d.total_minutes == 8 * 60 - 3


# ── continuous multi-shift worker: split per shift-day (no >11h rest gap) ──────

def test_continuous_worker_split_into_daily_sessions():
    # emp 10874: punches every ~8h across days with no >11h gap. eSSL reports one
    # Shift-C session per day (afternoon IN -> next-morning OUT); the resolver must
    # split per shift-day, not merge all days into a single session.
    punches = [_p(s, 22) for s in [
        "2026-06-01 14:02:36", "2026-06-01 22:00:26", "2026-06-01 22:00:36",
        "2026-06-02 05:56:50", "2026-06-02 14:02:52", "2026-06-02 22:00:41",
        "2026-06-02 22:00:49", "2026-06-03 05:57:53", "2026-06-03 13:45:56",
        "2026-06-03 22:00:13", "2026-06-03 22:00:22", "2026-06-04 05:56:03",
    ]]
    days = {d.tran_date.isoformat(): d for d in resolve_employee_days(punches)}
    assert days["2026-06-01"].shift == "C"
    assert days["2026-06-01"].actual_in == datetime(2026, 6, 1, 14, 2, 36)
    assert days["2026-06-01"].actual_out == datetime(2026, 6, 2, 5, 56, 50)
    assert days["2026-06-01"].work_minutes == 480       # vendor: work 8:00
    assert days["2026-06-01"].ot_minutes == 474         # vendor: OT 7:54
    assert days["2026-06-02"].actual_in == datetime(2026, 6, 2, 14, 2, 52)
    assert days["2026-06-02"].actual_out == datetime(2026, 6, 3, 5, 57, 53)
    assert days["2026-06-03"].actual_in == datetime(2026, 6, 3, 13, 45, 56)
    assert days["2026-06-03"].actual_out == datetime(2026, 6, 4, 5, 56, 3)


def test_single_long_presence_under_cap_not_split():
    # A genuine ~16h presence (one shift-day, under MAX_SESSION_HOURS) with mid
    # punches so no single gap exceeds 11h: stays one session, not chopped.
    d = resolve_employee_days([
        _p("2026-05-01 06:00:00", 22),
        _p("2026-05-01 14:00:00", 14),   # mid punch keeps gaps < 11h
        _p("2026-05-01 22:00:00", 14),
    ])
    assert len(d) == 1
    assert d[0].actual_in == datetime(2026, 5, 1, 6, 0, 0)
    assert d[0].actual_out == datetime(2026, 5, 1, 22, 0, 0)


# ── segmentation: distinct days separated ─────────────────────────────────────

def test_segmentation_separates_distinct_days():
    punches = [
        _p("2026-05-01 06:00:00", 22), _p("2026-05-01 14:00:00", 14),
        _p("2026-05-02 06:00:00", 22), _p("2026-05-02 14:00:00", 14),
    ]
    assert len(segment_sessions(punches)) == 2
