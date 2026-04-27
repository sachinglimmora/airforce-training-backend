import hashlib
import json

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

log = structlog.get_logger()
settings = get_settings()


def _make_cache_key(
    provider: str, model: str, messages: list, temperature: float, citations: list
) -> str:
    payload = json.dumps(
        {
            "provider": provider,
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "citations": sorted(citations),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_cached(key: str) -> dict | None:
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        raw = await r.get(f"ai_cache:{key}")
        await r.aclose()
        if raw:
            return json.loads(raw)
    except Exception as e:
        log.warning("cache_read_error", error=str(e))
    return None


async def set_cached(key: str, value: dict) -> None:
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.setex(f"ai_cache:{key}", settings.AI_CACHE_TTL_SECONDS, json.dumps(value))
        await r.aclose()
    except Exception as e:
        log.warning("cache_write_error", error=str(e))
