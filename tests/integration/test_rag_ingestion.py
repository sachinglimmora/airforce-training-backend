import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.content.models import ContentSource
from app.modules.rag.models import ContentChunk
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def test_embed_source_creates_chunks(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()

    async def fake_embed(texts, *args, **kwargs):
        # Return exactly as many vectors as input texts so zip(strict=True) succeeds.
        return {
            "embeddings": [[0.1] * 1536 for _ in texts],
            "model": "text-embedding-3-small",
            "usage": {"total_tokens": 100},
        }

    with patch("app.modules.ai.service.AIService") as mock_ai:
        instance = mock_ai.return_value
        instance.embed = AsyncMock(side_effect=fake_embed)
        await asyncio.to_thread(embed_source, str(source.id))

    rows = (await db_session.execute(select(ContentChunk).where(ContentChunk.source_id == source.id))).scalars().all()
    assert len(rows) >= 4  # one per non-empty section, possibly more if any over budget
    keys_seen = {k for c in rows for k in c.citation_keys}
    assert keys_seen >= {"SYN-FCOM-3.1", "SYN-FCOM-3.2", "SYN-FCOM-4"}
    assert all(c.embedding_dim == 1536 for c in rows)
    assert all(len(c.embedding) == 1536 for c in rows)

    # source status updated
    src_after = (await db_session.execute(select(ContentSource).where(ContentSource.id == source.id))).scalar_one()
    assert src_after.embedding_status == "succeeded"


async def test_approve_source_enqueues_embed_task(db_session):
    source = await seed_synthetic_fcom(db_session)
    source.status = "draft"
    await db_session.commit()

    from app.modules.content.service import ContentService
    svc = ContentService(db_session)
    with patch("app.modules.content.service.embed_source") as mock_task:
        await svc.approve_source(str(source.id), uuid.uuid4())
        mock_task.delay.assert_called_once_with(str(source.id))
