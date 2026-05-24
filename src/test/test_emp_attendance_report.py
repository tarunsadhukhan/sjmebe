"""Tests for HRMS Employee Attendance Report endpoints."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from src.hrms.empAttendanceReport import (
    _build_columns,
    _daterange,
    _month_iter,
    _parse_date,
)

PREFIX = "/api/hrmsReports"


def _get_client():
    """Lazy-import TestClient so pure-function tests still run without httpx."""
    from fastapi.testclient import TestClient
    from src.main import app

    return TestClient(app), app


def _row(mapping: dict):
    r = MagicMock()
    r._mapping = mapping
    return r


# ─── Helper function tests ──────────────────────────────────────────


class TestHelpers:
    def test_parse_date_valid(self):
        assert _parse_date("2026-04-01", "from_date") == date(2026, 4, 1)

    def test_parse_date_missing_raises_400(self):
        with pytest.raises(Exception) as exc:
            _parse_date(None, "from_date")
        assert "required" in str(exc.value).lower()

    def test_parse_date_invalid_format_raises_400(self):
        with pytest.raises(Exception) as exc:
            _parse_date("01-04-2026", "from_date")
        assert "invalid" in str(exc.value).lower()

    def test_daterange_inclusive(self):
        days = list(_daterange(date(2026, 4, 1), date(2026, 4, 3)))
        assert days == [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]

    def test_month_iter_spans_year_boundary(self):
        months = list(_month_iter(date(2025, 11, 15), date(2026, 2, 5)))
        assert months == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]


# ─── _build_columns tests ───────────────────────────────────────────


class TestBuildColumns:
    def test_daily_columns_one_per_day(self):
        cols, buckets = _build_columns(
            "daily", date(2026, 4, 1), date(2026, 4, 3), []
        )
        assert [c["key"] for c in cols] == [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
        ]
        assert [c["label"] for c in cols] == ["01/04", "02/04", "03/04"]
        assert len(buckets) == 3
        # daily buckets are single-day
        for key, s, e in buckets:
            assert s == e

    def test_monthly_columns_format(self):
        cols, buckets = _build_columns(
            "monthly", date(2024, 1, 15), date(2024, 3, 10), []
        )
        assert [c["label"] for c in cols] == ["Jan'24", "Feb'24", "Mar'24"]
        # First bucket clipped to from_date
        assert buckets[0][1] == date(2024, 1, 15)
        # Last bucket clipped to to_date
        assert buckets[-1][2] == date(2024, 3, 10)

    def test_fnwise_uses_period_names_and_clips(self):
        periods = [
            {
                "fne_id": 1,
                "fne_name": "FN1-Apr",
                "from_date": date(2026, 4, 1),
                "to_date": date(2026, 4, 15),
            },
            {
                "fne_id": 2,
                "fne_name": "FN2-Apr",
                "from_date": date(2026, 4, 16),
                "to_date": date(2026, 4, 30),
            },
        ]
        cols, buckets = _build_columns(
            "fnwise", date(2026, 4, 5), date(2026, 4, 20), periods
        )
        assert [c["label"] for c in cols] == ["FN1-Apr", "FN2-Apr"]
        # Clipped to requested window
        assert buckets[0][1] == date(2026, 4, 5)
        assert buckets[0][2] == date(2026, 4, 15)
        assert buckets[1][1] == date(2026, 4, 16)
        assert buckets[1][2] == date(2026, 4, 20)

    def test_invalid_mode_raises(self):
        with pytest.raises(Exception):
            _build_columns("weekly", date(2026, 4, 1), date(2026, 4, 3), [])


# ─── Endpoint tests ─────────────────────────────────────────────────


class TestEmpAttendanceReportEndpoint:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        from src.authorization.utils import get_current_user_with_refresh
        from src.config.db import get_tenant_db

        self._db = MagicMock()
        self._client, app = _get_client()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {
            "user_id": 1
        }
        app.dependency_overrides[get_tenant_db] = lambda: self._db
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id_returns_400(self):
        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?mode=daily&from_date=2026-04-01&to_date=2026-04-03"
        )
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_invalid_mode_returns_400(self):
        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?co_id=1&mode=weekly&from_date=2026-04-01&to_date=2026-04-03"
        )
        assert resp.status_code == 400

    def test_from_date_after_to_date_returns_400(self):
        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?co_id=1&mode=daily&from_date=2026-04-10&to_date=2026-04-01"
        )
        assert resp.status_code == 400

    def test_daily_aggregates_hours_rounded_to_1dp(self):
        # Two attendance rows for same emp, same day should sum to 8.5h.
        self._db.execute.return_value.fetchall.return_value = [
            _row(
                {
                    "eb_id": 100,
                    "emp_code": "0003",
                    "emp_name": "NABCD",
                    "status_name": "Active",
                    "sub_dept_code": "BL",
                    "sub_dept_name": "Bailing",
                    "attendance_date": date(2026, 4, 1),
                    "working_hours": 4.25,
                }
            ),
            _row(
                {
                    "eb_id": 100,
                    "emp_code": "0003",
                    "emp_name": "NABCD",
                    "status_name": "Active",
                    "sub_dept_code": "BL",
                    "sub_dept_name": "Bailing",
                    "attendance_date": date(2026, 4, 1),
                    "working_hours": 4.25,
                }
            ),
            _row(
                {
                    "eb_id": 100,
                    "emp_code": "0003",
                    "emp_name": "NABCD",
                    "status_name": "Active",
                    "sub_dept_code": "BL",
                    "sub_dept_name": "Bailing",
                    "attendance_date": date(2026, 4, 2),
                    "working_hours": 8.0,
                }
            ),
        ]

        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?co_id=1&mode=daily&from_date=2026-04-01&to_date=2026-04-02&branch_id=1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert [c["key"] for c in body["columns"]] == [
            "2026-04-01",
            "2026-04-02",
        ]
        assert len(body["data"]) == 1
        row = body["data"][0]
        assert row["emp_code"] == "0003"
        assert row["values"]["2026-04-01"] == 8.5
        assert row["values"]["2026-04-02"] == 8.0
        # Total in daily mode = sum of hours, 1dp
        assert row["total"] == 16.5

    def test_monthly_converts_hours_to_days_rounded(self):
        # 80 hours / 8 = 10 days
        rows = [
            _row(
                {
                    "eb_id": 1,
                    "emp_code": "E1",
                    "emp_name": "A",
                    "status_name": "Active",
                    "sub_dept_code": "X1",
                    "sub_dept_name": "X",
                    "attendance_date": date(2026, 1, d),
                    "working_hours": 8.0,
                }
            )
            for d in range(1, 11)
        ]
        self._db.execute.return_value.fetchall.return_value = rows

        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?co_id=1&mode=monthly&from_date=2026-01-01&to_date=2026-01-31&branch_id=1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["columns"][0]["label"] == "Jan'26"
        assert body["data"][0]["values"]["2026-01"] == 10
        assert body["data"][0]["total"] == 10

    def test_less_than_filter_excludes_employees(self):
        # less_than is now applied in SQL, so the mocked DB simply returns
        # the rows the SQL would have returned (only emp A; emp B was
        # filtered out by the WHERE COALESCE(ad.attended_days, 0) < :less_than
        # clause). We assert the bind was passed and the result is honoured.
        rows = []
        for d in range(1, 4):
            rows.append(
                _row(
                    {
                        "eb_id": 1,
                        "emp_code": "A",
                        "emp_name": "A",
                        "status_name": "Active",
                        "sub_dept_code": "X1",
                        "sub_dept_name": "X",
                        "attendance_date": date(2026, 1, d),
                        "working_hours": 8.0,
                    }
                )
            )
        self._db.execute.return_value.fetchall.return_value = rows

        resp = self._client.get(
            f"{PREFIX}/emp_attendance_report"
            "?co_id=1&mode=monthly&from_date=2026-01-01&to_date=2026-01-31"
            "&less_than=5&branch_id=1"
        )
        assert resp.status_code == 200
        codes = [r["emp_code"] for r in resp.json()["data"]]
        assert codes == ["A"]
        # Verify less_than reached the SQL bind dict.
        call_args = self._db.execute.call_args
        assert call_args is not None
        binds = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs
        assert binds["less_than"] == 5


class TestEmpAttendanceSetupEndpoint:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        from src.authorization.utils import get_current_user_with_refresh
        from src.config.db import get_tenant_db

        self._db = MagicMock()
        self._client, app = _get_client()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {
            "user_id": 1
        }
        app.dependency_overrides[get_tenant_db] = lambda: self._db
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id_returns_400(self):
        resp = self._client.get(f"{PREFIX}/emp_attendance_setup")
        assert resp.status_code == 400

    def test_returns_departments_and_periods(self):
        # First call -> departments; second call -> fne_master.
        dept_rows = [_row({"dept_id": 1, "dept_name": "Bailing"})]
        fne_rows = [
            _row(
                {
                    "fne_id": 1,
                    "fne_name": "FN1-Apr",
                    "from_date": date(2026, 4, 1),
                    "to_date": date(2026, 4, 15),
                }
            )
        ]
        self._db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=dept_rows)),
            MagicMock(fetchall=MagicMock(return_value=fne_rows)),
        ]

        resp = self._client.get(f"{PREFIX}/emp_attendance_setup?co_id=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["departments"] == [{"dept_id": 1, "dept_name": "Bailing"}]
        assert body["fne_periods"][0]["fne_name"] == "FN1-Apr"

    def test_setup_degrades_when_fne_master_missing(self):
        dept_rows = [_row({"dept_id": 1, "dept_name": "Bailing"})]
        # Departments OK; fne query raises (table missing).
        self._db.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=dept_rows)),
            Exception("Table 'dev3.fne_master' doesn't exist"),
        ]

        resp = self._client.get(f"{PREFIX}/emp_attendance_setup?co_id=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["departments"] == [{"dept_id": 1, "dept_name": "Bailing"}]
        assert body["fne_periods"] == []
