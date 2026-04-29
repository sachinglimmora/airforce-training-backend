import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.content.models import ContentReference, ContentSource
from app.modules.rag.models import ContentChunk
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _fake_embed(texts, *args, **kwargs):
    """Returns exactly len(texts) vectors so zip(strict=True) succeeds."""
    return {
        "embeddings": [[0.1] * 1536 for _ in texts],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 100},
    }


async def _make_test_user(db_session) -> User:
    """Insert a minimal user so FK constraints (e.g. content_sources.approved_by) resolve."""
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Integration Test User",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_embed_source_creates_chunks(db_session):
    source = await seed_synthetic_fcom(db_session)
    refs = (await db_session.execute(
        select(ContentReference).where(ContentReference.source_id == source.id)
    )).scalars().all()
    expected_keys = {r.citation_key for r in refs}
    await db_session.commit()

    with patch("app.modules.ai.service.AIService") as mock_ai:
        instance = mock_ai.return_value
        instance.embed = AsyncMock(side_effect=_fake_embed)
        # Run via thread (asyncio.run inside Celery task gets its own loop) to avoid
        # cross-loop conflicts with the global engine in app.database.
        await asyncio.to_thread(embed_source, str(source.id))

    rows = (await db_session.execute(
        select(ContentChunk).where(ContentChunk.source_id == source.id)
    )).scalars().all()
    assert len(rows) >= 4  # one per non-empty section, possibly more if any over budget
    keys_seen = {k for c in rows for k in c.citation_keys}
    assert keys_seen <= expected_keys, f"unexpected keys {keys_seen - expected_keys}"
    assert keys_seen >= {k for k in expected_keys if k.endswith(("3.1", "3.2", "4"))}
    assert all(c.embedding_dim == 1536 for c in rows)
    assert all(len(c.embedding) == 1536 for c in rows)

    # source status updated
    src_after = (await db_session.execute(
        select(ContentSource).where(ContentSource.id == source.id)
    )).scalar_one()
    assert src_after.embedding_status == "succeeded"


async def test_approve_source_enqueues_embed_task(db_session):
    user = await _make_test_user(db_session)
    source = await seed_synthetic_fcom(db_session)
    source.status = "draft"
    await db_session.commit()

    from app.modules.content.service import ContentService
    svc = ContentService(db_session)
    with patch("app.modules.content.service.embed_source") as mock_task:
        await svc.approve_source(str(source.id), user.id)
        mock_task.delay.assert_called_once_with(str(source.id))
