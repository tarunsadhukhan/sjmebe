import jwt
from datetime import datetime, timedelta, timezone

from src.authorization.utils import ALGORITHM, SECRET_KEY
from src.common.portal.approval import get_portal_optional_token_payload as approval_payload
from src.common.portal.roles import get_portal_optional_token_payload as roles_payload
from src.common.portal.users import get_portal_optional_token_payload as users_payload


def _create_token(payload: dict, expire_in_minutes: int = 30) -> str:
    token_payload = payload.copy()
    token_payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expire_in_minutes)
    return jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)


def test_optional_payload_helpers_default_to_user_1_without_token():
    assert roles_payload(access_token=None, authorization=None)["user_id"] == 1
    assert users_payload(access_token=None, authorization=None)["user_id"] == 1
    assert approval_payload(access_token=None, authorization=None)["user_id"] == 1


def test_optional_payload_helpers_read_user_id_from_bearer():
    token = _create_token({"user_id": 777, "type": "portal"})
    auth_header = f"Bearer {token}"

    assert roles_payload(access_token=None, authorization=auth_header)["user_id"] == 777
    assert users_payload(access_token=None, authorization=auth_header)["user_id"] == 777
    assert approval_payload(access_token=None, authorization=auth_header)["user_id"] == 777


def test_optional_payload_helpers_fallback_on_invalid_token():
    bad_auth = "Bearer invalid.token.value"

    assert roles_payload(access_token=None, authorization=bad_auth)["user_id"] == 1
    assert users_payload(access_token=None, authorization=bad_auth)["user_id"] == 1
    assert approval_payload(access_token=None, authorization=bad_auth)["user_id"] == 1
