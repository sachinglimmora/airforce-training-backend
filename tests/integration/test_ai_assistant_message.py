import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.content.models import ContentReference
from app.modules.rag.tasks import _embed_source_async
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def fake_embed_factory(*args, **kwargs):
    """AsyncMock side_effect — returns one 1536-dim vector per input text."""
    # signature is (texts, model) but we accept anything for safety
    texts = args[0] if args else kwargs.get("texts", [])
    return {
        "embeddings": [[0.1] * 1536 for _ in texts],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 100},
    }


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=fake_embed_factory)
        await _embed_source_async(str(source.id))
    # Return the citation_keys produced by this seed for downstream assertions.
    refs = (await db_session.execute(
        select(ContentReference).where(ContentReference.source_id == source.id)
    )).scalars().all()
    return source, [r.citation_key for r in refs]


async def test_send_message_returns_grounded_answer(client, db_session):
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]  # any seeded key — chunks all share a vector so any can match

    async def fake_complete(req, user_id):
        # Echo back a response that references the actual citation_key provided.
        return {
            "response": f"Per [{primary_key}], engine start procedure...",
            "provider": "gemini",
            "model": "gemini-1.5-pro",
            "cached": False,
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost_usd": 0.0001},
            "citations": req.context_citations,
            "request_id": "req_x",
        }

    # Patch AIService at its DEFINITION site so deferred imports inside embedder.py
    # and top-level imports in rewriter.py / service.py all pick up the mock.
    with patch("app.modules.ai.service.AIService") as mock_ai_cls, \
         patch("app.modules.auth.deps.get_current_user") as mock_user:
        instance = mock_ai_cls.return_value
        instance.embed = AsyncMock(side_effect=fake_embed_factory)
        instance.complete = AsyncMock(side_effect=fake_complete)
        from app.modules.auth.schemas import CurrentUser
        mock_user.return_value = CurrentUser(
            id=str(uuid.uuid4()), email="t@example.com", role="trainee"
        )

        resp = await client.post(
            "/api/v1/ai-assistant/message", json={"content": "engine start procedure?"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["userMessage"]["content"] == "engine start procedure?"
        assert body["assistantMessage"]["grounded"] in ("strong", "soft")
        assert primary_key in body["assistantMessage"]["content"]
        # Sources should include at least one of the seeded citation keys.
        returned_keys = {s["citation_key"] for s in body["assistantMessage"]["sources"]}
        assert returned_keys & set(citation_keys), (
            f"expected at least one of {citation_keys} in sources, got {returned_keys}"
        )
