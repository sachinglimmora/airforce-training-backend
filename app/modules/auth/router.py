from typing import Annotated

from fastapi import Depends, Request
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import get_user_permissions
from app.core.security import get_jwks
from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    RefreshRequest,
)
from app.modules.auth.service import AuthService

router = APIRouter()

_401 = {401: {"description": "Invalid or expired credentials"}}
_403 = {403: {"description": "Forbidden — insufficient permissions"}}
_429 = {429: {"description": "Too many requests / account locked"}}


@router.post(
    "/login",
    response_model=dict,
    summary="Login and receive tokens",
    description=(
        "Authenticate with email + password. Returns an **access token** (15 min, RS256 JWT) "
        "and a **refresh token** (7 days, opaque, stored hashed server-side).\n\n"
        "Include the access token as `Authorization: Bearer <token>` on every subsequent request.\n\n"
        "**Errors:**\n"
        "- `401 INVALID_CREDENTIALS` — wrong email or password\n"
        "- `423 ACCOUNT_LOCKED` — 5 consecutive failures within 15 min\n"
        "- `429 TOO_MANY_ATTEMPTS` — rate limit hit"
    ),
    responses={**_401, 423: {"description": "Account locked"}, **_429},
    operation_id="auth_login",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuthService(db)
    user_agent = request.headers.get("User-Agent")
    ip = request.client.host if request.client else None
    token = await svc.login(body.email, body.password, user_agent, ip)
    return {"data": token.model_dump()}


@router.post(
    "/refresh",
    response_model=dict,
    summary="Rotate the access / refresh token pair",
    description=(
        "Exchange a valid refresh token for a new access + refresh token pair. "
        "The old refresh token is immediately revoked (rotation). "
        "Call this before the access token expires to maintain a session.\n\n"
        "Returns the same shape as `POST /auth/login`."
    ),
    responses={**_401},
    operation_id="auth_refresh",
)
async def refresh(body: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    svc = AuthService(db)
    token = await svc.refresh(body.refresh_token)
    return {"data": token.model_dump()}


@router.post(
    "/logout",
    status_code=204,
    summary="Revoke refresh token and blacklist access token",
    description=(
        "Revokes the supplied refresh token and blacklists the current access token in Redis "
        "until its natural expiry. After this call the client must re-authenticate.\n\n"
        "Send the refresh token in the request body."
    ),
    responses={**_401},
    operation_id="auth_logout",
)
async def logout(
    body: RefreshRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuthService(db)
    await svc.logout(body.refresh_token, access_jti=current_user.jti or None)


@router.get(
    "/me",
    response_model=dict,
    summary="Get current user profile and permissions",
    description=(
        "Returns the authenticated user's profile, assigned roles, and the full set of "
        "permissions derived from those roles. Use this to bootstrap the frontend permission model."
    ),
    responses={**_401},
    operation_id="auth_me",
)
async def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuthService(db)
    user = await svc.get_user_by_id(current_user.id)
    perms = sorted(get_user_permissions(current_user.roles))
    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "roles": current_user.roles,
            "permissions": perms,
        }
    }


@router.post(
    "/change-password",
    status_code=204,
    summary="Change own password",
    description=(
        "Validates the current password then sets a new one. "
        "The new password must satisfy the policy: ≥ 12 characters, "
        "at least one uppercase, lowercase, digit, and symbol. "
        "The last 5 passwords are blocked from reuse.\n\n"
        "All active sessions remain valid — to force re-login, call `POST /auth/logout` afterwards."
    ),
    responses={**_401, 400: {"description": "Password policy violation or current password wrong"}},
    operation_id="auth_change_password",
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuthService(db)
    await svc.change_password(current_user.id, body.current_password, body.new_password)


@router.get(
    "/.well-known/jwks.json",
    summary="JWKS public key set",
    description=(
        "Returns the RS256 public key in JSON Web Key Set format. "
        "Other services can use this to verify access tokens without contacting the auth server."
    ),
    operation_id="auth_jwks",
)
async def jwks():
    return get_jwks()
