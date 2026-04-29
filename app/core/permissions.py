from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.core.exceptions import Forbidden
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

# Default Phase 1 permission matrix
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "trainee": {
        "content:read",
        "session:read:own",
        "competency:read:own",
        "evaluation:read:own",
    },
    "instructor": {
        "content:read",
        "user:read",
        "session:read",
        "session:update",
        "scenario:create",
        "scenario:read",
        "scenario:update",
        "scenario:delete",
        "evaluation:create",
        "evaluation:update",
        "rubric:read",
        "ai:complete:instructor",
        "ai:complete:trainee",
        "audit:read:own",
        "competency:read",
    },
    "evaluator": {
        "content:read",
        "user:read",
        "session:read",
        "scenario:read",
        "evaluation:create",
        "evaluation:update",
        "rubric:read",
        "rubric:create",
        "ai:complete:instructor",
        "ai:complete:trainee",
        "audit:read:own",
        "competency:read",
    },
    "admin": {
        "content:read",
        "content:create",
        "content:update",
        "content:delete",
        "content:approve",
        "user:read",
        "user:create",
        "user:update",
        "user:delete",
        "user:assign_role",
        "role:read",
        "session:read",
        "session:update",
        "scenario:create",
        "scenario:read",
        "scenario:update",
        "scenario:delete",
        "evaluation:read",
        "rubric:read",
        "rubric:create",
        "asset:read",
        "asset:create",
        "audit:read",
        "ai:complete:instructor",
        "ai:complete:trainee",
        "competency:read",
    },
}


def get_user_permissions(roles: list[str]) -> set[str]:
    perms: set[str] = set()
    for role in roles:
        perms |= ROLE_PERMISSIONS.get(role, set())
    return perms


def require_admin() -> "Depends":
    """Dependency that allows only users with the admin role."""
    from fastapi import Depends as _Depends

    async def check(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
        if "admin" not in current_user.roles:
            raise Forbidden("Admin role required")
        return current_user

    return _Depends(check)


def require_permission(resource: str, action: str) -> Callable:
    permission = f"{resource}:{action}"

    async def dependency(current_user: Annotated[CurrentUser, Depends(get_current_user)]):
        user_perms = get_user_permissions(current_user.roles)
        if permission not in user_perms and "admin" not in current_user.roles:
            raise Forbidden(f"Missing permission: {permission}")
        return current_user

    return Depends(dependency)
