import redis.asyncio as aioredis

from app.config import get_settings

_settings = get_settings()

# Module-level singleton; created once on first call
_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            _settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis
