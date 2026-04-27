import uuid
from unittest.mock import patch, AsyncMock

import pytest

from app.modules.rag.tasks import _embed_source_async
from app.modules.rag.retriever import _vector_search
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def test_vector_search_returns_chunks_with_scores(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    fake = {"embeddings": [[0.1] * 1536] * 50, "model": "x", "usage": {"total_tokens": 1}}
    with patch("app.modules.ai.service.AIService") as MockAI:
        MockAI.return_value.embed = AsyncMock(return_value=fake)
        await _embed_source_async(str(source.id))

    qvec = [0.1] * 1536
    rows = await _vector_search(db_session, qvec, top_k=5, aircraft_id=None)
    assert len(rows) > 0
    assert all("citation_keys" in r for r in rows)
    assert all("cosine_score" in r for r in rows)
    # all chunks have the same vector so all scores ≈ 1.0
    assert all(r["cosine_score"] > 0.99 for r in rows)
