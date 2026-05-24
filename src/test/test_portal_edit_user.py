from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.common.portal import users as portal_users_module
from src.main import app


client = TestClient(app)


class TestEditPortalUser:
    def setup_method(self):
        self.mock_session = MagicMock()
        app.dependency_overrides[portal_users_module.get_tenant_db] = lambda: self.mock_session
        app.dependency_overrides[portal_users_module.get_portal_optional_token_payload] = (
            lambda: {"user_id": 99}
        )

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_edit_user_accepts_query_param_user_id(self):
        mock_user = MagicMock()
        mock_user.user_id = 20
        mock_user.active = True

        delete_result = MagicMock()
        delete_result.rowcount = 2
        self.mock_session.query.return_value.filter.return_value.first.return_value = mock_user
        self.mock_session.execute.side_effect = [delete_result, None, None]

        response = client.post(
            "/api/admin/PortalData/edit_user_portal?userId=20",
            json={
                "is_active": False,
                "branch_roles": [
                    {"company_id": 1, "branch_id": 10, "role_id": "3"},
                    {"company_id": 1, "branch_id": 11, "role_id": "4"},
                ],
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "message": "User updated successfully",
            "user_id": 20,
            "roles_mapped": 2,
        }
        assert mock_user.active is False
        assert self.mock_session.commit.called

    def test_edit_user_requires_user_id(self):
        response = client.post(
            "/api/admin/PortalData/edit_user_portal",
            json={
                "is_active": True,
                "branch_roles": [],
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "user_id is required"