import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.rag.embedder import EmbedDimensionMismatch, embed_and_validate


def _make_session_factory_mock(db_mock=None):
    """Build a MagicMock that, when called, returns an async-context-manager
    yielding `db_mock` (or a fresh MagicMock if not given)."""
    db = db_mock or MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=ctx)
    return factory, db


async def test_embed_and_validate_passes_when_dim_matches():
    fake_result = {
        "embeddings": [[0.1] * 1536, [0.2] * 1536],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 4},
    }
    ai_instance = MagicMock()
    ai_instance.embed = AsyncMock(return_value=fake_result)
    session_factory, _ = _make_session_factory_mock()

    with patch("app.database.AsyncSessionLocal", session_factory), \
         patch("app.modules.ai.service.AIService", return_value=ai_instance):
        out = await embed_and_validate(["foo", "bar"])
        assert len(out) == 2
        assert all(len(v) == 1536 for v in out)
        ai_instance.embed.assert_awaited_once()


async def test_embed_and_validate_raises_on_dim_mismatch():
    fake_result = {
        "embeddings": [[0.1] * 768],   # wrong dim
        "model": "text-embedding-004",
        "usage": {"total_tokens": 2},
    }
    ai_instance = MagicMock()
    ai_instance.embed = AsyncMock(return_value=fake_result)
    session_factory, _ = _make_session_factory_mock()

    with patch("app.database.AsyncSessionLocal", session_factory), \
         patch("app.modules.ai.service.AIService", return_value=ai_instance):
        with pytest.raises(EmbedDimensionMismatch):
            await embed_and_validate(["foo"])
