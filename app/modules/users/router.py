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

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Insufficient permissions"}}
_404 = {404: {"description": "User not found"}}


@router.get(
    "/users",
    response_model=dict,
    summary="List users",
    description=(
        "Returns a paginated list of users. Filter by `role` (trainee, instructor, evaluator, admin) "
        "and/or `status` (active, suspended, locked). Limit defaults to 50, max 200.\n\n"
        "**Required permission:** `user:read`"
    ),
    responses={**_401, **_403},
    operation_id="users_list",
)
async def list_users(
    role: str | None = Query(None, description="Filter by role name"),
    status: str | None = Query(None, description="Filter by account status: active | suspended | locked"),
    limit: int = Query(50, le=200, description="Max results to return (max 200)"),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    svc = UsersService(db)
    users = await svc.list_users(role=role, status=status, limit=limit)
    return {"data": [UserDetailOut.model_validate(u).model_dump() for u in users]}


@router.post(
    "/users",
    status_code=201,
    response_model=dict,
    summary="Create a new user (admin invite)",
    description=(
        "Creates a user account and assigns the specified roles. "
        "The temporary password must satisfy the password policy. "
        "A password-reset email is sent on first login (Phase 2 — SSO not yet wired).\n\n"
        "**Required permission:** `user:create`"
    ),
    responses={**_401, **_403, 409: {"description": "Email or employee_id already exists"}},
    operation_id="users_create",
)
async def create_user(
    body: CreateUserRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.create_user(body, current_user.id)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.get(
    "/users/{user_id}",
    response_model=dict,
    summary="Get user detail",
    description=(
        "Returns full profile for a single user including roles and status. "
        "Instructors can only read their own trainees; admins can read all.\n\n"
        "**Required permission:** `user:read`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="users_get",
)
async def get_user(
    user_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.get_user(user_id)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.patch(
    "/users/{user_id}",
    response_model=dict,
    summary="Update user profile",
    description=(
        "Partial update — only fields included in the request body are changed. "
        "Users can update their own profile; admins can update any user.\n\n"
        "**Required permission:** `user:update`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="users_update",
)
async def update_user(
    user_id: str,
    body: UpdateUserRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    user = await svc.update_user(user_id, body)
    return {"data": UserDetailOut.model_validate(user).model_dump()}


@router.delete(
    "/users/{user_id}",
    status_code=204,
    summary="Soft-delete a user",
    description=(
        "Sets `deleted_at` — the user cannot log in but their records are preserved for audit. "
        "Physical deletion is not supported.\n\n"
        "**Required permission:** `user:delete`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="users_delete",
)
async def delete_user(
    user_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.delete_user(user_id)


@router.post(
    "/users/{user_id}/roles",
    status_code=204,
    summary="Assign a role to a user",
    description=(
        "Grants the specified role to the user. If the user already has the role, the call is a no-op.\n\n"
        "**Required permission:** `user:assign_role`\n\n"
        "Body: `{ \"role\": \"instructor\" }`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="users_assign_role",
)
async def assign_role(
    user_id: str,
    body: AssignRoleRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.assign_role(user_id, body.role, current_user.id)


@router.delete(
    "/users/{user_id}/roles/{role}",
    status_code=204,
    summary="Revoke a role from a user",
    description=(
        "Removes the named role from the user. If the role is not currently assigned, the call is a no-op.\n\n"
        "**Required permission:** `user:assign_role`"
    ),
    responses={**_401, **_403, **_404},
    operation_id="users_revoke_role",
)
async def revoke_role(
    user_id: str,
    role: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    await svc.revoke_role(user_id, role)


@router.get(
    "/roles",
    response_model=dict,
    summary="List all roles and their permissions",
    description="Returns every role defined in the system with its associated permission list.",
    responses={**_401},
    operation_id="roles_list",
)
async def list_roles(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    roles = await svc.list_roles()
    return {"data": [RoleOut.model_validate(r).model_dump() for r in roles]}


@router.get(
    "/permissions",
    response_model=dict,
    summary="List all permissions",
    description=(
        "Returns the full permission catalogue. "
        "Each permission is a `resource:action` pair (e.g. `content:approve`, `scenario:delete`)."
    ),
    responses={**_401},
    operation_id="permissions_list",
)
async def list_permissions(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    svc = UsersService(db)
    perms = await svc.list_permissions()
    return {"data": [PermissionOut.model_validate(p).model_dump() for p in perms]}
