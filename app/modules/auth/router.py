from typing import Annotated

from fastapi import Depends, Request, Response
from fastapi.routing import APIRouter

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import (
    ChangePasswordRequest,
    CurrentUser,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.modules.auth.service import AuthService
from app.core.permissions import get_user_permissions
from app.core.security import get_jwks
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post("/login", response_model=dict, summary="Login and receive tokens")
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


@router.post("/refresh", response_model=dict, summary="Rotate token pair")
async def refresh(body: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    svc = AuthService(db)
    token = await svc.refresh(body.refresh_token)
    return {"data": token.model_dump()}


@router.post("/logout", status_code=204, summary="Revoke refresh token")
async def logout(body: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    svc = AuthService(db)
    await svc.logout(body.refresh_token)


@router.get("/me", response_model=dict, summary="Get current user profile")
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


@router.post("/change-password", status_code=204, summary="Change own password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = AuthService(db)
    await svc.change_password(current_user.id, body.current_password, body.new_password)


@router.get("/.well-known/jwks.json", summary="JWKS public key set")
async def jwks():
    return get_jwks()
