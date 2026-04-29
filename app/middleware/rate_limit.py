import time
import uuid

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

log = structlog.get_logger()
_settings = get_settings()

_SKIP_PATHS = {"/health", "/health/ready", "/version", "/api/v1/openapi.json"}

# Requests per minute by role
_LIMITS: dict[str, int] = {
    "admin": 500,
    "instructor": _settings.AI_RATE_LIMIT_INSTRUCTOR,
    "evaluator": _settings.AI_RATE_LIMIT_INSTRUCTOR,
    "trainee": _settings.AI_RATE_LIMIT_TRAINEE,
    "anonymous": 30,
}
_WINDOW_SECONDS = 60


def _extract_subject(request: Request) -> tuple[str, str]:
    """Return (subject_key, role) from Bearer token or fall back to client IP."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            import jwt as pyjwt

            # Decode without signature verification — we only need the claims for rate limiting.
            # Full verification happens in get_current_user dep.
            payload = pyjwt.decode(token, options={"verify_signature": False})
            sub = payload.get("sub", "")
            roles: list[str] = payload.get("roles", [])
            role = "admin" if "admin" in roles else (roles[0] if roles else "anonymous")
            return f"user:{sub}", role
        except Exception:
            pass

    ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}", "anonymous"


async def _check_rate_limit(redis, key: str, limit: int) -> tuple[bool, int]:
    """
    Sliding window counter using Redis INCR + EXPIRE.
    Returns (allowed, current_count).
    """
    try:
        window_key = f"rl:{key}:{int(time.time()) // _WINDOW_SECONDS}"
        pipe = redis.pipeline()
        pipe.incr(window_key)
        pipe.expire(window_key, _WINDOW_SECONDS * 2)
        results = await pipe.execute()
        count = results[0]
        return count <= limit, count
    except Exception:
        # If Redis is unavailable, fail open (allow request) to avoid an outage cascade
        return True, 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _SKIP_PATHS:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request.headers.get(
                "X-Request-ID", str(uuid.uuid4())
            )
            return response

        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        subject_key, role = _extract_subject(request)
        limit = _LIMITS.get(role, _LIMITS["anonymous"])

        from app.redis_client import get_redis

        redis = get_redis()
        allowed, count = await _check_rate_limit(redis, subject_key, limit)

        if not allowed:
            log.warning("rate_limit_exceeded", subject=subject_key, role=role, count=count)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}},
                headers={
                    "X-Request-ID": request_id,
                    "Retry-After": str(_WINDOW_SECONDS),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response
