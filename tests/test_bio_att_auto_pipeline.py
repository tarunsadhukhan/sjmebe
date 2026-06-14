"""Unit tests for the pure logic in bio_att_auto_pipeline.

These cover the two decisions that drive correctness and don't need a DB:
  * compute_dates_to_process — each new date plus its prior day (night-shift OUT).
  * should_skip — high-water-mark skip decision.
"""

from datetime import date

from src.hrms.bio_att_auto_pipeline import compute_dates_to_process, should_skip


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
