import asyncio
import uuid
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import select

from app.modules.content.models import ContentSource
from app.modules.rag.models import ContentChunk
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def test_embed_source_creates_chunks(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()

    fake_embeddings = {"embeddings": [[0.1] * 1536] * 50, "model": "text-embedding-3-small", "usage": {"total_tokens": 100}}
    with patch("app.modules.ai.service.AIService") as MockAI:
        instance = MockAI.return_value
        instance.embed = AsyncMock(return_value=fake_embeddings)
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
