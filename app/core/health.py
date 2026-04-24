from app.database import engine
from app.config import get_settings
import redis.asyncio as aioredis

settings = get_settings()


async def check_readiness() -> dict:
    checks = {"database": False, "redis": False}

    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass

    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception:
        pass

    all_ok = all(checks.values())
    return {"status": "ready" if all_ok else "degraded", "checks": checks}
