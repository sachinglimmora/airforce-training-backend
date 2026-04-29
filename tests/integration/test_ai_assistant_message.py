import uuid
from unittest.mock import AsyncMock, patch

from app.modules.rag.tasks import _embed_source_async
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    fake = {"embeddings": [[0.1] * 1536] * 50, "model": "x", "usage": {"total_tokens": 1}}
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(return_value=fake)
        await _embed_source_async(str(source.id))


async def test_send_message_returns_grounded_answer(client, db_session):
    await _ingest(db_session)

    fake_complete = {
        "response": "Per [SYN-FCOM-3.1], engine start procedure...",
        "provider": "gemini", "model": "gemini-1.5-pro",
        "cached": False, "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost_usd": 0.0001},
        "citations": ["SYN-FCOM-3.1"], "request_id": "req_x",
    }
    fake_embed = {"embeddings": [[0.1] * 1536], "model": "x", "usage": {"total_tokens": 1}}

    with patch("app.modules.rag.embedder.AIService") as mock_emb, \
         patch("app.modules.rag.service.AIService") as mock_complete, \
         patch("app.modules.auth.deps.get_current_user") as mock_user:
        mock_emb.return_value.embed = AsyncMock(return_value=fake_embed)
        mock_complete.return_value.complete = AsyncMock(return_value=fake_complete)
        from app.modules.auth.schemas import CurrentUser
        mock_user.return_value = CurrentUser(id=str(uuid.uuid4()), email="t@example.com", role="trainee")

        resp = await client.post("/api/v1/ai-assistant/message", json={"content": "engine start procedure?"})
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["userMessage"]["content"] == "engine start procedure?"
        assert body["assistantMessage"]["grounded"] in ("strong", "soft")
        assert body["assistantMessage"]["content"].startswith("Per [SYN-FCOM-3.1]")
        assert any(s["citation_key"] == "SYN-FCOM-3.1" for s in body["assistantMessage"]["sources"])
