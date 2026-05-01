import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound
from app.core.security import hash_password
from app.modules.auth.models import Permission, Role, User, UserRole

log = structlog.get_logger()


class UsersService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_users(
        self,
        role: str | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> list[User]:
        q = select(User).where(User.deleted_at.is_(None))
        if status:
            q = q.where(User.status == status)
        q = q.limit(limit)
        result = await self.db.execute(q)
        users = result.scalars().all()
        if role:
            users = [u for u in users if role in u.roles]
        return list(users)

    async def get_user(self, user_id: str) -> User:
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFound("User")
        return user

    async def create_user(self, data, assigned_by_id: str) -> User:
        existing = await self.db.execute(select(User).where(User.email == data.email.lower()))
        if existing.scalar_one_or_none():
            raise Conflict("A user with this email already exists")

        user = User(
            email=data.email.lower(),
            full_name=data.full_name,
            employee_id=data.employee_id,
            password_hash=hash_password(data.temporary_password),
        )
        self.db.add(user)
        await self.db.flush()

        for role_name in data.roles:
            await self._assign_role_by_name(user, role_name, assigned_by_id)

        await self.db.flush()
        await self.db.refresh(user, attribute_names=["user_roles"])

        log.info("user_created", user_id=str(user.id), by=assigned_by_id)
        return user

    async def update_user(self, user_id: str, data) -> User:
        user = await self.get_user(user_id)
        if data.full_name is not None:
            user.full_name = data.full_name
        if data.employee_id is not None:
            user.employee_id = data.employee_id
        if data.status is not None:
            user.status = data.status
        return user

    async def delete_user(self, user_id: str) -> None:
        from datetime import UTC, datetime

        user = await self.get_user(user_id)
        user.deleted_at = datetime.now(UTC)

    async def assign_role(self, user_id: str, role_name: str, assigned_by_id: str) -> None:
        user = await self.get_user(user_id)
        await self._assign_role_by_name(user, role_name, assigned_by_id)

    async def revoke_role(self, user_id: str, role_name: str) -> None:
        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if not role:
            raise NotFound("Role")

        ur_result = await self.db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        )
        ur = ur_result.scalar_one_or_none()
        if ur:
            await self.db.delete(ur)

    async def list_roles(self) -> list[Role]:
        result = await self.db.execute(select(Role))
        return list(result.scalars().all())

    async def list_permissions(self) -> list[Permission]:
        result = await self.db.execute(select(Permission))
        return list(result.scalars().all())

    async def _assign_role_by_name(self, user: User, role_name: str, assigned_by_id: str) -> None:
        role_result = await self.db.execute(select(Role).where(Role.name == role_name))
        role = role_result.scalar_one_or_none()
        if not role:
            raise NotFound(f"Role '{role_name}'")

        existing = await self.db.execute(
            select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
        )
        if not existing.scalar_one_or_none():
            self.db.add(UserRole(user_id=user.id, role_id=role.id, assigned_by=assigned_by_id))
