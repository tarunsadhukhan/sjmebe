import jwt
from datetime import datetime, timedelta, timezone

from src.authorization.utils import ALGORITHM, SECRET_KEY
from src.common.portal.menu import get_portal_token_payload


def _create_token(payload: dict, expire_in_minutes: int = 30) -> str:
    token_payload = payload.copy()
    token_payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expire_in_minutes)
    return jwt.encode(token_payload, SECRET_KEY, algorithm=ALGORITHM)


def test_get_portal_token_payload_accepts_cookie_token():
    token = _create_token({"user_id": 101, "type": "portal"})

    payload = get_portal_token_payload(access_token=token, authorization=None)

    assert payload["user_id"] == 101
    assert payload["type"] == "portal"
    assert payload["access_expired"] is False


def test_get_portal_token_payload_accepts_bearer_when_cookie_missing():
    token = _create_token({"user_id": 202, "type": "portal"})

    payload = get_portal_token_payload(
        access_token=None,
        authorization=f"Bearer {token}",
    )

    assert payload["user_id"] == 202
    assert payload["type"] == "portal"
    assert payload["access_expired"] is False


def test_get_portal_token_payload_allows_when_cookie_and_bearer_missing():
    payload = get_portal_token_payload(access_token=None, authorization=None)

    assert payload["access_expired"] is False


def test_get_portal_token_payload_allows_invalid_authorization_format():
    payload = get_portal_token_payload(access_token=None, authorization="Token abc.def.ghi")

    assert payload["access_expired"] is False


def test_get_portal_token_payload_allows_invalid_bearer_token():
    payload = get_portal_token_payload(access_token=None, authorization="Bearer invalid.token.value")

    assert payload["access_expired"] is False
