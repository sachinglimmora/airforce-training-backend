from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

# In test runs the same engine instance gets reused across multiple asyncio
# event loops (pytest-asyncio creates a fresh loop per test, while Celery's
# `asyncio.run(...)` wrapper inside `embed_source` creates yet another). A
# pooled connection opened in one loop cannot be safely awaited in another,
# so we disable pooling under ENV=test. Production keeps the normal pool.
_engine_kwargs: dict = {"echo": settings.ENV == "local"}
if settings.ENV == "test":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True})

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias used by the Celery worker
async_session_factory = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
