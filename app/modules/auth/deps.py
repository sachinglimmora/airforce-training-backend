from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import TokenExpired, TokenInvalid
from app.core.security import decode_access_token
from app.modules.auth.schemas import CurrentUser

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if not credentials:
        raise TokenInvalid()
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise TokenExpired()
    except jwt.PyJWTError:
        raise TokenInvalid()

    jti = payload.get("jti", "")

    # Check access-token blacklist (populated by logout)
    if jti:
        try:
            from app.redis_client import get_redis
            redis = get_redis()
            if await redis.exists(f"jti_blacklist:{jti}"):
                raise TokenInvalid()
        except TokenInvalid:
            raise
        except Exception:
            # Redis unavailable — fail open to avoid auth outage
            pass

    return CurrentUser(id=payload["sub"], roles=payload.get("roles", []), jti=jti)
