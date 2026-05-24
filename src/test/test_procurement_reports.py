"""
Tests for procurement report endpoints.
Tests GET /procurementReports/indent-itemwise endpoint.
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from datetime import date

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestIndentItemwiseReport:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_outstanding_filter_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&outstanding_filter=invalid")
        assert response.status_code == 400
        assert "outstanding_filter" in response.json()["detail"]

    def test_invalid_indent_type_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&indent_type=Invalid")
        assert response.status_code == 400
        assert "indent_type" in response.json()["detail"]

    def test_success_returns_data_and_total(self):
        mock_row = _mock_row({
            "indent_dtl_id": 10,
            "indent_id": 5,
            "indent_no": 1,
            "indent_date": date(2026, 3, 1),
            "branch_name": "Main Branch",
            "branch_prefix": "MAIN",
            "co_prefix": "ABC",
            "item_name": "Bolt M8",
            "item_grp_name": "Fasteners",
            "uom_name": "NOS",
            "indent_qty": 100.0,
            "outstanding_qty": 40.0,
            "po_consumed_qty": 60.0,
            "indent_type_id": "Regular",
            "expense_type_name": "General",
            "status_name": "Approved",
        })
        self.mock_session.execute.return_value.fetchall.return_value = [mock_row]
        self.mock_session.execute.return_value.scalar.return_value = 1

        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["item_name"] == "Bolt M8"
        assert body["data"][0]["indent_qty"] == 100.0
        assert body["data"][0]["outstanding_qty"] == 40.0

    def test_empty_result(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get("/api/procurementReports/indent-itemwise?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["total"] == 0

    def test_with_all_filters(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get(
            "/api/procurementReports/indent-itemwise"
            "?co_id=1&branch_id=2&date_from=2026-01-01&date_to=2026-03-06"
            "&indent_type=Regular&outstanding_filter=outstanding&search=bolt"
            "&page=1&limit=20"
        )
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
