import asyncio
from unittest.mock import AsyncMock, patch

from app.modules.rag.retriever import _vector_search
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _fake_embed(texts, *args, **kwargs):
    return {"embeddings": [[0.1] * 1536 for _ in texts], "model": "x", "usage": {"total_tokens": 1}}


async def test_vector_search_returns_chunks_with_scores(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()

    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=_fake_embed)
        # Run ingestion in a thread so Celery's asyncio.run gets its own loop.
        await asyncio.to_thread(embed_source, str(source.id))

    qvec = [0.1] * 1536
    rows = await _vector_search(db_session, qvec, top_k=5, aircraft_id=None)
    assert len(rows) > 0
    assert all("citation_keys" in r for r in rows)
    assert all("cosine_score" in r for r in rows)
    # all chunks have the same vector so all scores ≈ 1.0
    assert all(r["cosine_score"] > 0.99 for r in rows)
