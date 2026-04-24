from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.users.schemas import AssignRoleRequest, CreateUserRequest, PermissionOut, RoleOut, UpdateUserRequest, UserDetailOut
from app.modules.users.service import UsersService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get("/users", summary="List users")
async def list_users(
    role: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, le=200),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = UsersService(db)
    users = await svc.list_users(role=role, status=status, limit=limit)
    return {"data": [UserDetailOut.model_validate(u).model_dump() for u in users]}


@router.post("/users", status_code=201, summary="Create user")
async def create_user(
    body: CreateUserRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.create_user(body, current_user.id)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.get("/users/{user_id}", summary="Get user detail")
async def get_user(
    user_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.get_user(user_id)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.patch("/users/{user_id}", summary="Update user")
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.update_user(user_id, body)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.delete("/users/{user_id}", status_code=204, summary="Soft-delete user")
async def delete_user(
    user_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.delete_user(user_id)


@router.post("/users/{user_id}/roles", status_code=204, summary="Assign role to user")
async def assign_role(
    user_id: str,
    body: AssignRoleRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.assign_role(user_id, body.role, current_user.id)


@router.delete("/users/{user_id}/roles/{role}", status_code=204, summary="Revoke role from user")
async def revoke_role(
    user_id: str,
    role: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.revoke_role(user_id, role)


@router.get("/roles", summary="List roles and permissions")
async def list_roles(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    roles = await svc.list_roles()
    return {"data": [RoleOut.model_validate(r).model_dump() for r in roles]}


@router.get("/permissions", summary="List all permissions")
async def list_permissions(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    perms = await svc.list_permissions()
    return {"data": [PermissionOut.model_validate(p).model_dump() for p in perms]}
