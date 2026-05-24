import asyncio
from types import SimpleNamespace

from src.common.portal.menu import (
    PermissionCheckRequest,
    check_portal_permission,
    get_portal_permissions,
)


class _PermissionRecord:
    def __init__(self, permissions, user_id=0):
        self.permissions = permissions
        self.user_id = user_id


def test_check_portal_permission_allows_when_token_missing():
    payload = PermissionCheckRequest(path="/dashboardportal/masters/items", action="view")
    request = SimpleNamespace(cookies={})

    result = asyncio.run(check_portal_permission(payload, request))

    assert result["allowed"] is True
    assert result["access_type_id"] is None


def test_get_portal_permissions_returns_empty_when_token_missing():
    request = SimpleNamespace(cookies={})

    result = asyncio.run(get_portal_permissions(request))

    assert result.permissions == {}


def test_check_portal_permission_uses_permission_map_when_token_present(monkeypatch):
    payload = PermissionCheckRequest(path="/dashboardportal/masters/items", action="view")
    request = SimpleNamespace(cookies={"portal_permission_token": "perm-token"})

    monkeypatch.setattr(
        "src.common.portal.menu.get_permissions",
        lambda token: _PermissionRecord({"masters/items": 1}, user_id=77),
    )

    result = asyncio.run(check_portal_permission(payload, request))

    assert result["allowed"] is True
    assert result["access_type_id"] == 1


def test_check_portal_permission_respects_action_threshold(monkeypatch):
    payload = PermissionCheckRequest(path="/dashboardportal/masters/items", action="edit")
    request = SimpleNamespace(cookies={"portal_permission_token": "perm-token"})

    monkeypatch.setattr(
        "src.common.portal.menu.get_permissions",
        lambda token: _PermissionRecord({"masters/items": 1}, user_id=77),
    )

    result = asyncio.run(check_portal_permission(payload, request))

    assert result["allowed"] is False
    assert result["access_type_id"] == 1


def test_get_portal_permissions_returns_permissions_when_token_present(monkeypatch):
    request = SimpleNamespace(cookies={"portal_permission_token": "perm-token"})

    monkeypatch.setattr(
        "src.common.portal.menu.get_permissions",
        lambda token: _PermissionRecord({"masters/items": 3}, user_id=77),
    )

    result = asyncio.run(get_portal_permissions(request))

    assert result.permissions == {"masters/items": 3}
