from fastapi import APIRouter, Request, HTTPException, Header  # Add Header to the imports
from starlette.status import HTTP_401_UNAUTHORIZED
from fastapi.responses import JSONResponse
from sqlalchemy.sql import text
from sqlalchemy.orm import Session
import os
from src.authorization.utils import (
    decode_access_token,
    verify_access_token,
    create_access_token,
    SECRET_KEY,
    ALGORITHM
)
from src.authorization.auth import login_user, login_user_console
from src.config.db import STATIC_TENANT, default_engine, extract_subdomain_from_request
from datetime import datetime
import jwt

from src.authorization.models import LoginRequest
common_router = APIRouter()


@common_router.post("/login")
def login_route(request: Request, login_data: LoginRequest):
    """Login Route (calls login_user from auth.py)"""
    print("\n=== Starting Login Process ===")
    print(f"🔄 Received login request for user: {login_data.username}")
    print(f"🔍 Login type: {login_data.logintype}")
    print(f"🔒 Remember me: {login_data.rememberMe}")

    # Extract subdomain
    subdomain = request.headers.get("X-Subdomain", "default")
    print(f"🌐 Using subdomain: {subdomain}")
    
    # Print all headers for debugging
    print("\n📋 Request Headers:")
    for header, value in request.headers.items():
        print(f"   {header}: {value}")
    
    try:
        result = login_user(
            request,
            login_data.username,
            login_data.password,
            login_data.logintype,
            subdomain
        )
        print("✅ Login function completed successfully")
        return result
    except Exception as e:
        print(f"❌ Login error in router: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        raise

@common_router.post("/loginconsole")
def login_console_route(request: Request, login_data: LoginRequest):
    """Login Route (calls login_user_console from auth.py)"""
    print("Login User")

    # Console login is pinned to STATIC_TENANT when configured.
    subdomain = (STATIC_TENANT or "").strip().lower()
    if not subdomain:
        subdomain = extract_subdomain_from_request(request)

    print(f"DEBUG: Extracted Subdomain = {subdomain}")  # Debugging
    print('hhhsub=====',subdomain)
    return login_user_console(
        request,
        login_data.username,
        login_data.password,
        login_data.logintype,
        subdomain  # ✅ Pass extracted subdomain
    )




@common_router.get("/protected")
def protected_route(request: Request, authorization: str = Header(None)):
    """Protected Route"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.split(" ")[1]
    username = decode_access_token(token)  # Decode the token to get the username
    return {"message": f"Hello, {username}"}

@common_router.get("/validate-subdomain")
def validate_subdomain(request: Request):
    """
    Validate whether a subdomain corresponds to an active org in con_org_master.
    Returns { valid: true } if found, { valid: false } otherwise.
    """
    subdomain = request.query_params.get("subdomain", "").strip().lower()
    if not subdomain:
        return {"valid": False}

    try:
        with Session(default_engine) as session:
            result = session.execute(
                text("""
                    SELECT con_org_id
                    FROM con_org_master
                    WHERE LOWER(TRIM(con_org_shortname)) = :subdomain
                      AND active = 1
                    LIMIT 1
                """),
                {"subdomain": subdomain}
            ).fetchone()

            return {"valid": result is not None}
    except Exception:
        return {"valid": False}


@common_router.get("/verify-session")
async def verify_session(request: Request):
    """
    Verify session validity.
    Returns 200 { ok: true } if valid, 401 if not.
    Also validates that the user's org matches the current subdomain.
    """
    try:
        access_token = request.cookies.get("access_token")

        # Try to verify access token first if it exists
        if access_token:
            try:
                payload = verify_access_token(access_token)

                # --- Org/subdomain validation for console sessions ---
                token_subdomain = payload.get("subdomain")
                token_org_id = payload.get("con_org_id")
                # Only validate org if the token was issued for a console session
                # (portal tokens have "type": "portal" and no "subdomain")
                if token_subdomain is not None:
                    # Resolve current subdomain from request
                    current_subdomain = extract_subdomain_from_request(request).strip().lower()
                    # Also check X-Subdomain header (frontend sends browser hostname)
                    header_sub = (request.headers.get("X-Subdomain") or "").strip().lower()
                    resolved_current = header_sub if header_sub and header_sub != "default" else current_subdomain
                    if not resolved_current or resolved_current == "default":
                        resolved_current = "default"

                    # If the token was issued for a specific subdomain, verify it matches
                    if token_subdomain != resolved_current:
                        print(f"Session org mismatch: token={token_subdomain}, current={resolved_current}")
                        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Session not valid for this organization")

                return {"ok": True}
            except HTTPException as he:
                if he.status_code != 401:
                    raise
                
                # Access token is expired, try refresh using stored token
                try:
                    # Get user_id from expired token to look up refresh token
                    expired_payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
                    user_id = expired_payload.get("user_id")

                    if not user_id:
                        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                    # --- Validate org/subdomain even for expired tokens ---
                    token_subdomain = expired_payload.get("subdomain")
                    if token_subdomain is not None:
                        current_sub = (request.headers.get("X-Subdomain") or "").strip().lower()
                        if not current_sub or current_sub == "default":
                            current_sub = extract_subdomain_from_request(request).strip().lower()
                        if token_subdomain != current_sub:
                            print(f"Refresh org mismatch: token={token_subdomain}, current={current_sub}")
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                    # Get refresh token from database
                    with Session(default_engine) as session:
                        result = session.execute(
                            text("""
                                SELECT refresh_token 
                                FROM con_user_master 
                                WHERE con_user_id = :user_id
                                AND active = 1
                            """),
                            {"user_id": user_id}
                        ).fetchone()

                        # Verify stored refresh token exists and is valid
                        if not result or not result[0]:
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
                            
                        stored_token = result[0]
                        
                        # Verify the stored refresh token is still valid
                        try:
                            jwt.decode(stored_token, SECRET_KEY, algorithms=[ALGORITHM])
                        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
                            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

                        # Preserve org context in refreshed token
                        new_token_data = {"user_id": user_id}
                        if expired_payload.get("con_org_id") is not None:
                            new_token_data["con_org_id"] = expired_payload["con_org_id"]
                        if expired_payload.get("subdomain") is not None:
                            new_token_data["subdomain"] = expired_payload["subdomain"]
                        if expired_payload.get("type") is not None:
                            new_token_data["type"] = expired_payload["type"]

                        # Create new access token
                        new_access_token = create_access_token(new_token_data)

                        # Create response with just ok:true
                        response = JSONResponse(content={"ok": True})

                        # Set only the new access token cookie
                        ENV = os.getenv("ENV", "development")
                        COOKIE_DOMAIN = ".vowerp.co.in" if ENV == "production" else None
                        SECURE = True if ENV == "production" else False
                        SAMESITE = "None" if ENV == "production" else "Lax"

                        response.set_cookie(
                            key="access_token",
                            value=new_access_token,
                            httponly=True,
                            secure=SECURE,
                            samesite=SAMESITE,
                            path="/",
                            domain=COOKIE_DOMAIN
                        )

                        return response

                except:
                    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

    except HTTPException:
        raise
    except:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)