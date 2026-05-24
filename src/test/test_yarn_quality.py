"""
Tests for Yarn Quality Master endpoints.
Tests for src/masters/yarnQuality.py

Updated to use item_grp_id (from item_grp_mst) instead of jute_yarn_type_id.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.yarnQuality import optional_auth

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestYarnQualityEndpoints:
    """Tests for Yarn Quality Master API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI dependencies for all endpoint tests."""
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[optional_auth] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_yarn_quality_create_setup_success(self):
        """Should return yarn types list for create setup."""
        yarn_type_row = _mock_row({"item_grp_id": 1, "item_grp_name": "Polyester", "item_grp_code": "PLY"})
        branch_row = _mock_row({"branch_id": 1, "branch_name": "Main"})

        # create_setup calls execute twice: yarn_types then branches
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [yarn_type_row],
            [branch_row],
        ]

        response = client.get("/api/yarnQualityMaster/yarn_quality_create_setup?co_id=1")

        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        assert "yarn_types" in data
        assert isinstance(data["yarn_types"], list)

    def test_yarn_quality_create_setup_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnQualityMaster/yarn_quality_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_yarn_quality_table_success(self):
        """Should return yarn quality list with pagination."""
        mock_row = _mock_row({
            "yarn_quality_id": 1,
            "quality_code": "QC001",
            "item_grp_id": 1,
            "yarn_type_name": "Polyester",
            "twist_per_inch": 10.5,
            "std_count": 20.0,
            "std_doff": 100,
            "std_wt_doff": 5.5,
            "is_active": 1,
            "branch_id": 1,
            "co_id": 1,
        })

        # First call for count, second for data
        count_row = MagicMock()
        count_row._mapping = {"total": 1}
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [mock_row]

        response = client.get(
            "/api/yarnQualityMaster/yarn_quality_table?co_id=1&page=1&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data

    def test_yarn_quality_table_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnQualityMaster/yarn_quality_table")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_yarn_quality_create_success(self):
        """Should create a new yarn quality record."""
        # Mock duplicate check returning no match
        dup_result = MagicMock()
        dup_result._mapping = {"count": 0}
        self._mock_session.execute.return_value.fetchone.return_value = dup_result
        self._mock_session.add = MagicMock()
        self._mock_session.commit = MagicMock()

        def set_id(obj):
            obj.yarn_quality_id = 1
        self._mock_session.refresh.side_effect = set_id

        payload = {
            "co_id": "1",
            "quality_code": "QC001",
            "item_grp_id": "1",
            "twist_per_inch": "10.5",
            "std_count": "20.0",
            "std_doff": "100",
            "std_wt_doff": "5.5",
            "is_active": 1,
        }

        response = client.post(
            "/api/yarnQualityMaster/yarn_quality_create",
            json=payload
        )

        assert response.status_code in [200, 201]
        assert "message" in response.json()

    def test_yarn_quality_create_missing_quality_code(self):
        """Should return 400 when quality_code is missing."""
        payload = {
            "co_id": "1",
            "item_grp_id": "1",
            "twist_per_inch": "10.5",
        }

        response = client.post(
            "/api/yarnQualityMaster/yarn_quality_create",
            json=payload
        )

        assert response.status_code == 400
        assert "required" in response.json().get("detail", "").lower()

    def test_yarn_quality_create_duplicate_code(self):
        """Should return 409 when quality code already exists."""
        dup_result = MagicMock()
        dup_result._mapping = {"count": 1}
        self._mock_session.execute.return_value.fetchone.return_value = dup_result

        payload = {
            "co_id": "1",
            "quality_code": "QC001",
            "item_grp_id": "1",
            "twist_per_inch": "10.5",
        }

        response = client.post(
            "/api/yarnQualityMaster/yarn_quality_create",
            json=payload
        )

        assert response.status_code == 409
        assert "already exists" in response.json().get("detail", "").lower()

    def test_yarn_quality_edit_setup_success(self):
        """Should return yarn quality details and types for edit."""
        quality_row = _mock_row({
            "yarn_quality_id": 1,
            "quality_code": "QC001",
            "item_grp_id": 1,
            "yarn_type_name": "Polyester",
            "twist_per_inch": 10.5,
            "std_count": 20.0,
            "std_doff": 100,
            "std_wt_doff": 5.5,
            "is_active": 1,
            "branch_id": 1,
            "co_id": 1,
        })
        type_row = _mock_row({"item_grp_id": 1, "item_grp_name": "Polyester", "item_grp_code": "PLY"})
        branch_row = _mock_row({"branch_id": 1, "branch_name": "Main"})

        self._mock_session.execute.return_value.fetchone.return_value = quality_row
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [type_row],
            [branch_row],
        ]

        response = client.get(
            "/api/yarnQualityMaster/yarn_quality_edit_setup?co_id=1&yarn_quality_id=1"
        )

        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        assert "yarn_quality_details" in data
        assert "yarn_types" in data

    def test_yarn_quality_edit_setup_not_found(self):
        """Should return 404 when yarn quality not found."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get(
            "/api/yarnQualityMaster/yarn_quality_edit_setup?co_id=1&yarn_quality_id=999"
        )

        assert response.status_code == 404
        assert "not found" in response.json().get("detail", "").lower()

    def test_yarn_quality_edit_success(self):
        """Should update an existing yarn quality record."""
        existing = MagicMock()
        existing.yarn_quality_id = 1
        existing.quality_code = "QC001"
        existing.item_grp_id = 1
        existing.twist_per_inch = 10.5
        existing.std_count = 20.0
        existing.std_doff = 100
        existing.std_wt_doff = 5.5
        existing.is_active = 1
        existing.updated_by = 1

        self._mock_session.query.return_value.filter.return_value.first.return_value = existing
        self._mock_session.execute.return_value.fetchone.return_value = MagicMock(_mapping={"count": 0})

        payload = {
            "yarn_quality_id": "1",
            "co_id": "1",
            "quality_code": "QC001_UPDATED",
            "item_grp_id": "1",
            "twist_per_inch": "11.0",
            "std_count": "21.0",
            "std_doff": "101",
            "std_wt_doff": "5.6",
            "is_active": 1,
        }

        response = client.put(
            "/api/yarnQualityMaster/yarn_quality_edit",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "message" in data

    def test_yarn_quality_edit_not_found(self):
        """Should return 404 when yarn quality to edit not found."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        payload = {
            "yarn_quality_id": "999",
            "co_id": "1",
            "quality_code": "QC001",
            "item_grp_id": "1",
        }

        response = client.put(
            "/api/yarnQualityMaster/yarn_quality_edit",
            json=payload
        )

        assert response.status_code == 404
        assert "not found" in response.json().get("detail", "").lower()
