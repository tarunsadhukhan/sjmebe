import logging
import os
from typing import Dict

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
)
from src.common.portal.permission_cache import get_permissions, replace_permissions
from src.common.portal.query import get_portal_user_menus
from src.config.db import get_tenant_db

router = APIRouter()
logger = logging.getLogger(__name__)


class PermissionCheckRequest(BaseModel):
    path: str
    action: str


class PermissionResponse(BaseModel):
    permissions: Dict[str, int]


def _cookie_settings() -> Dict[str, str | bool | None]:
    env_value = os.getenv("ENV", "development")
    return {
        "domain": ".vowerp.co.in" if env_value == "production" else None,
        "secure": env_value == "production",
        "samesite": "None" if env_value == "production" else "Lax",
    }


def _is_sub_sub_menu(menu_parent_id: int | None, parent_lookup: Dict[int, int | None]) -> bool:
    if menu_parent_id is None:
        return False
    parent_parent = parent_lookup.get(menu_parent_id)
    return parent_parent is not None


def _normalise_path(path: str | None) -> str:
    if not path:
        return ""

    cleaned = path.strip()
    if not cleaned:
        return ""

    cleaned = cleaned.lstrip("/")
    prefix = "dashboardportal/"
    if cleaned.lower().startswith(prefix):
        cleaned = cleaned[len(prefix):]

    cleaned = cleaned.rstrip("/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    cleaned = cleaned.lower()

    return cleaned


def _action_threshold(action: str) -> int:
    mapping = {"view": 1, "print": 2, "create": 3, "edit": 4}
    return mapping.get(action.lower(), 4)


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    auth_value = authorization.strip()
    if not auth_value:
        return None
    parts = auth_value.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token if token else None


def get_portal_token_payload(
    access_token: str = Cookie(None, alias="access_token"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict:
    token = access_token or _extract_bearer_token(authorization)
    if not token:
        return {"access_expired": False}
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"verify_signature": False, "verify_exp": False},
        )
        payload["access_expired"] = False
        return payload
    except Exception:
        return {"access_expired": False}


@router.get("/portal_menu_items")
async def compmenuitems(
    request: Request,
    response: Response,
    token_data: dict = Depends(get_portal_token_payload),
    tenant_session: Session = Depends(get_tenant_db),
):
    query_user_id = request.query_params.get("user_id")
    token_user_id = token_data.get("user_id")
    user_id = token_user_id or query_user_id or 1

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        user_id = 1

    logger.debug("Authorized portal menu request for user %s", user_id)

    try:
        if token_data.get("access_expired"):
            refresh_result = tenant_session.execute(
                text(
                    "SELECT refresh_token FROM user_mst "
                    "WHERE user_id = :user_id AND active = 1"
                ),
                {"user_id": user_id},
            ).fetchone()
            if not refresh_result or not refresh_result[0]:
                raise HTTPException(status_code=401, detail="No refresh token found")

            refresh_token = refresh_result[0]
            try:
                jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            except jwt.ExpiredSignatureError as exc:
                raise HTTPException(status_code=401, detail="Refresh token expired") from exc
            except jwt.InvalidTokenError as exc:
                raise HTTPException(status_code=401, detail=f"Invalid refresh token: {str(exc)}") from exc

            new_payload = {"user_id": user_id}
            if token_data.get("type"):
                new_payload["type"] = token_data.get("type")
            new_access_token = create_access_token(new_payload)
            cookie_cfg = _cookie_settings()
            response.set_cookie(
                key="access_token",
                value=new_access_token,
                httponly=True,
                secure=cookie_cfg["secure"],
                samesite=cookie_cfg["samesite"],
                path="/",
                domain=cookie_cfg["domain"],
            )

        menu_query = get_portal_user_menus(user_id=user_id)
        menu_rows = tenant_session.execute(menu_query, {"user_id": user_id}).fetchall()
        logger.debug("Found %s menu entries for user %s", len(menu_rows), user_id)
        #print(f"Found menus {menu_rows} menu entries for user {user_id}")
        companies: Dict[int, Dict[str, Dict[int, Dict[str, Dict[int, dict]]]]] = {}
        permissions_map: Dict[str, int] = {}
        parent_lookup = {
            row.menu_id: row.menu_parent_id
            for row in menu_rows
            if row.menu_id is not None
        }

        for row in menu_rows:
            menu_id = row.menu_id
            if menu_id==724:
                print("here 724")
            if menu_id==723:
                print("here 723")
            if menu_id is None:
                continue

            menu_parent_id = row.menu_parent_id
            co_id = row.co_id
            branch_id = row.branch_id
            branch_name = row.branch_name
            menu_path = row.menu_path

            raw_access_type = row.access_type_id
            try:
                access_type_id = int(raw_access_type) if raw_access_type is not None else None
            except (TypeError, ValueError):
                access_type_id = None

            normalised_path = _normalise_path(menu_path)
            if normalised_path and access_type_id is not None:
                existing = permissions_map.get(normalised_path)
                if existing is None or access_type_id > existing:
                    permissions_map[normalised_path] = access_type_id

            if _is_sub_sub_menu(menu_parent_id, parent_lookup):
                continue

            company_entry = companies.setdefault(
                co_id,
                {
                    "co_id": co_id,
                    "co_name": row.co_name,
                    "branches": {},
                },
            )
            branch_entry = company_entry["branches"].setdefault(
                branch_id,
                {
                    "branch_id": branch_id,
                    "branch_name": branch_name,
                    "menus": {},
                },
            )
            branch_entry["menus"][menu_id] = {
                "menu_id": menu_id,
                "menu_name": row.menu_name,
                "menu_path": menu_path,
                "menu_parent_id": menu_parent_id,
                "access_type_id": access_type_id,
            }

        result = []
        for company in companies.values():
            branches = []
            for branch in company["branches"].values():
                branch_data = {
                    "branch_id": branch["branch_id"],
                    "branch_name": branch["branch_name"],
                    "menus": list(branch["menus"].values()),
                }
                branches.append(branch_data)
            result.append(
                {
                    "co_id": company["co_id"],
                    "co_name": company["co_name"],
                    "branches": branches,
                }
            )

        if permissions_map:
            cookie_cfg = _cookie_settings()
            token = replace_permissions(int(user_id), permissions_map)
            response.set_cookie(
                key="portal_permission_token",
                value=token,
                httponly=True,
                secure=cookie_cfg["secure"],
                samesite=cookie_cfg["samesite"],
                path="/",
                domain=cookie_cfg["domain"],
            )
        else:
            cookie_cfg = _cookie_settings()
            response.delete_cookie(
                key="portal_permission_token",
                path="/",
                domain=cookie_cfg["domain"],
            )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error getting portal menu items for user %s", user_id)
        raise HTTPException(status_code=500, detail="Error getting portal menu items") from exc


@router.post("/portal_menu_permissions/check")
async def check_portal_permission(
    payload: PermissionCheckRequest,
    request: Request,
):
    token = request.cookies.get("portal_permission_token")
    record = get_permissions(token) if token else None
    permissions = record.permissions if record else {}

    path = _normalise_path(payload.path)
    access_type_id = None

    if path:
        segments = path.split("/")
        for idx in range(len(segments), 0, -1):
            candidate = "/".join(segments[:idx])
            candidate = candidate.lower()
            access_type_id = permissions.get(candidate)
            if access_type_id is not None:
                break
    else:
        access_type_id = permissions.get("")

    if access_type_id is None:
        return {"allowed": True, "access_type_id": None}

    required = _action_threshold(payload.action)
    allowed = access_type_id >= required
    return {"allowed": allowed, "access_type_id": access_type_id}


@router.get("/portal_menu_permissions", response_model=PermissionResponse)
async def get_portal_permissions(
    request: Request,
):
    token = request.cookies.get("portal_permission_token")
    record = get_permissions(token) if token else None
    permissions = record.permissions if record else {}
    return PermissionResponse(permissions=permissions)
