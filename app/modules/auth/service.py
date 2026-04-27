from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AccountLocked, InvalidCredentials, NotFound, TokenRevoked
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.schemas import TokenResponse, UserOut

log = structlog.get_logger()
settings = get_settings()

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, email: str, password: str, user_agent: str | None, ip: str | None) -> TokenResponse:
        result = await self.db.execute(
            select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.password_hash):
            if user:
                await self._record_failed_login(user)
            raise InvalidCredentials()

        if user.status == "locked":
            raise AccountLocked()

        await self._reset_failed_login(user)

        access_token = create_access_token(str(user.id), user.roles)
        refresh_token_raw = generate_refresh_token()
        await self._store_refresh_token(user.id, refresh_token_raw, user_agent, ip)

        log.info("user_logged_in", user_id=str(user.id))
        return self._build_token_response(access_token, refresh_token_raw, user)

    async def refresh(self, refresh_token_raw: str) -> TokenResponse:
        token_hash = hash_token(refresh_token_raw)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(UTC),
            )
        )
        token_obj = result.scalar_one_or_none()
        if not token_obj:
            raise TokenRevoked()

        # Rotate: revoke old, issue new
        token_obj.revoked_at = datetime.now(UTC)

        user_result = await self.db.execute(select(User).where(User.id == token_obj.user_id))
        user = user_result.scalar_one()

        new_access = create_access_token(str(user.id), user.roles)
        new_refresh_raw = generate_refresh_token()
        await self._store_refresh_token(user.id, new_refresh_raw, token_obj.user_agent, token_obj.ip_address)

        return self._build_token_response(new_access, new_refresh_raw, user)

    async def logout(self, refresh_token_raw: str, access_jti: str | None = None) -> None:
        token_hash = hash_token(refresh_token_raw)
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        token_obj = result.scalar_one_or_none()
        if token_obj:
            token_obj.revoked_at = datetime.now(UTC)

        if access_jti:
            await self.blacklist_token(access_jti)

    async def blacklist_token(self, jti: str) -> None:
        """Store the jti in Redis until the access-token TTL expires."""
        try:
            from app.redis_client import get_redis
            redis = get_redis()
            await redis.setex(f"jti_blacklist:{jti}", settings.JWT_ACCESS_TTL_SECONDS, "1")
        except Exception:
            log.warning("jti_blacklist_failed", jti=jti)

    async def change_password(self, user_id: str, current_password: str, new_password: str) -> None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFound("User")
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentials()
        user.password_hash = hash_password(new_password)

    async def get_user_by_id(self, user_id: str) -> User:
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise NotFound("User")
        return user

    # -- private helpers --

    async def _store_refresh_token(self, user_id, raw: str, user_agent, ip) -> None:
        token = RefreshToken(
            user_id=user_id,
            token_hash=hash_token(raw),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.JWT_REFRESH_TTL_SECONDS),
            user_agent=user_agent,
            ip_address=ip,
        )
        self.db.add(token)

    async def _record_failed_login(self, user: User) -> None:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user.status = "locked"
            log.warning("account_locked", user_id=str(user.id))

    async def _reset_failed_login(self, user: User) -> None:
        user.failed_login_count = 0
        user.last_login_at = datetime.now(UTC)

    def _build_token_response(self, access: str, refresh: str, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=settings.JWT_ACCESS_TTL_SECONDS,
            user=UserOut(id=user.id, email=user.email, full_name=user.full_name, roles=user.roles),
        )
