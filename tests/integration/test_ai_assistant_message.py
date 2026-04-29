import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.content.models import ContentReference
from app.modules.rag.tasks import embed_source
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
        # Run via thread so Celery's asyncio.run gets its own loop, avoiding
        # cross-loop conflicts with the global engine in app.database.
        await asyncio.to_thread(embed_source, str(source.id))
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

    from app.main import app
    from app.modules.auth.deps import get_current_user

    # Insert a real user so chat_sessions.user_id FK resolves
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser
    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Integration Test User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        # Patch AIService at its DEFINITION site so deferred imports inside embedder.py
        # and top-level imports in rewriter.py / service.py all pick up the mock.
        with patch("app.modules.ai.service.AIService") as mock_ai_cls:
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=fake_complete)

            resp = await client.post(
                "/api/v1/ai-assistant/message", json={"content": "engine start procedure?"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assert body["userMessage"]["content"] == "engine start procedure?"
            assistant = body["assistantMessage"]
            assert "grounded" in assistant, (
                f"missing 'grounded' in assistantMessage. Full response shape: {body}"
            )
            assert assistant["grounded"] in ("strong", "soft"), (
                f"expected strong/soft grounding; got {assistant['grounded']!r}. "
                f"sources={assistant.get('sources')}, suggestions={assistant.get('suggestions')}"
            )
            assert primary_key in assistant["content"]
            # Sources should include at least one of the seeded citation keys.
            returned_keys = {s["citation_key"] for s in assistant["sources"]}
            assert returned_keys & set(citation_keys), (
                f"expected at least one of {citation_keys} in sources, got {returned_keys}"
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
