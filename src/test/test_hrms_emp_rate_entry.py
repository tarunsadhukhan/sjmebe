from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.hrms import empRateEntry
from src.main import app


client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestHrmsEmpRateEntry:
    def setup_method(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[empRateEntry.get_tenant_db] = lambda: self.mock_db
        app.dependency_overrides[empRateEntry.get_current_user_with_refresh] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_lookup_requires_emp_code(self):
        response = client.get("/api/hrmsMasters/emp_rate_employee_lookup?co_id=1")
        assert response.status_code == 400
        assert response.json()["detail"] == "emp_code is required"

    def test_lookup_returns_employee_data(self):
        self.mock_db.execute.return_value.fetchone.return_value = _mock_row(
            {
                "eb_id": 25,
                "emp_code": "EMP-001",
                "branch_id": 2,
                "employee_name": "John Doe",
            }
        )

        response = client.get("/api/hrmsMasters/emp_rate_employee_lookup?co_id=1&emp_code=EMP-001")
        assert response.status_code == 200
        body = response.json()
        assert body["found"] is True
        assert body["data"]["eb_id"] == 25
        assert body["data"]["branch_id"] == 2

    def test_create_rate_success(self):
        validate_result = MagicMock()
        validate_result.fetchone.return_value = _mock_row({"eb_id": 25})
        insert_result = MagicMock()
        self.mock_db.execute.side_effect = [validate_result, insert_result]

        response = client.post(
            "/api/hrmsMasters/emp_rate_create",
            json={
                "co_id": 1,
                "eb_id": 25,
                "rate": 510.5,
                "date_of_rate_update": "2026-04-25",
            },
        )

        assert response.status_code == 200
        assert response.json()["message"] == "Employee rate saved successfully"
        assert self.mock_db.commit.called

    def test_create_rate_requires_date(self):
        response = client.post(
            "/api/hrmsMasters/emp_rate_create",
            json={
                "co_id": 1,
                "eb_id": 25,
                "rate": 510.5,
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "date_of_rate_update is required"
