"""Unit tests for the pure logic in bio_att_auto_pipeline.

These cover the two decisions that drive correctness and don't need a DB:
  * compute_dates_to_process — each new date plus its prior day (night-shift OUT).
  * should_skip — high-water-mark skip decision.
"""

from datetime import date

from src.hrms.bio_att_auto_pipeline import (
    compute_dates_to_process,
    compute_high_water_mark,
    should_skip,
)


def test_compute_dates_includes_prior_day():
    result = compute_dates_to_process([date(2026, 6, 13)])
    assert result == [date(2026, 6, 12), date(2026, 6, 13)]


def test_compute_dates_dedups_and_sorts():
    # 13th and 14th -> {12,13} ∪ {13,14} = 12,13,14 (no dup of 13).
    result = compute_dates_to_process([date(2026, 6, 14), date(2026, 6, 13)])
    assert result == [date(2026, 6, 12), date(2026, 6, 13), date(2026, 6, 14)]


def test_compute_dates_empty():
    assert compute_dates_to_process([]) == []


def test_compute_dates_crosses_month_boundary():
    result = compute_dates_to_process([date(2026, 7, 1)])
    assert result == [date(2026, 6, 30), date(2026, 7, 1)]


def test_should_skip_when_no_rows():
    assert should_skip(None, 0) is True


def test_should_skip_when_not_advanced():
    assert should_skip(100, 100) is True
    assert should_skip(99, 100) is True


def test_should_not_skip_when_new_rows():
    assert should_skip(101, 100) is False


# ── compute_high_water_mark — advance only across fully-succeeded dates ───────
# The mark must never jump past a date whose chain did not complete through
# final process; otherwise a partial run (e.g. basic written but final_process
# lost the connection) silently loses those punches forever.

def test_high_water_advances_to_max_when_nothing_failed():
    # failed_min_new_id is None -> every date succeeded -> advance fully.
    assert compute_high_water_mark(current_max=500, last_id=100,
                                   failed_min_new_id=None) == 500


def test_high_water_stops_just_before_first_failed_punch():
    # A date failed; its earliest new punch is id 350 -> lock the mark at 349 so
    # 350+ (the failed date and everything after) is retried next tick.
    assert compute_high_water_mark(current_max=500, last_id=100,
                                   failed_min_new_id=350) == 349


def test_high_water_never_moves_backward():
    # Failed punch id is at/below the existing mark -> keep the mark, don't rewind.
    assert compute_high_water_mark(current_max=500, last_id=100,
                                   failed_min_new_id=100) == 100
    assert compute_high_water_mark(current_max=500, last_id=100,
                                   failed_min_new_id=80) == 100


def test_high_water_does_not_exceed_current_max():
    assert compute_high_water_mark(current_max=500, last_id=100,
                                   failed_min_new_id=900) == 500
