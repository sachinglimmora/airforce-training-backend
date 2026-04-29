import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.modules.auth.models import User
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom


async def _fake_embed(texts, *args, **kwargs):
    return {"embeddings": [[0.1] * 1536 for _ in texts], "model": "x", "usage": {"total_tokens": 1}}


async def _ingest(db_session):
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=_fake_embed)
        await asyncio.to_thread(embed_source, str(source.id))
    return source


async def _make_test_user(db_session, role="trainee"):
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_moderation_blocks_classification_marker_in_response(client, db_session):
    """End-to-end: AI emits a classification marker; moderator blocks; response shape reflects it."""
    await _ingest(db_session)
    real_user = await _make_test_user(db_session)

    # AI completion that emits a classification marker
    async def fake_complete(req, user_id):
        return {
            "response": "Per [SYN-FCOM-3.1], details marked SECRET//NOFORN about engine.",
            "provider": "gemini", "model": "gemini-1.5-pro", "cached": False,
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0},
            "citations": req.context_citations, "request_id": "req_x",
        }

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.rewriter.AIService", new=mock_ai_cls),
        ):
            inst = mock_ai_cls.return_value
            inst.embed = AsyncMock(side_effect=_fake_embed)
            inst.complete = AsyncMock(side_effect=fake_complete)
            resp = await client.post(
                "/api/v1/ai-assistant/message", json={"content": "engine details?"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assistant = body["assistantMessage"]
            assert assistant["grounded"] == "blocked"
            assert "blocked by the content moderation layer" in assistant["content"]
            assert assistant["moderation"]["violation_type"] == "classification"
            assert assistant["moderation"]["severity"] == "critical"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_moderation_admin_create_rule_invalidates_cache_and_blocks_next_message(client, db_session):
    """Admin POSTs a banned-phrase rule; the next AI response containing that phrase gets blocked."""
    await _ingest(db_session)
    real_user = await _make_test_user(db_session)

    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    instructor_user = CurrentUser(id=str(real_user.id), roles=["instructor"], jti="")
    app.dependency_overrides[get_current_user] = lambda: instructor_user

    try:
        # Add a rule that bans the literal phrase 'WIDGET-X42'
        rule_body = {
            "category": "banned_phrase",
            "pattern": "WIDGET-X42",
            "pattern_type": "literal",
            "action": "block",
            "severity": "high",
            "description": "Test banned phrase",
            "active": True,
        }
        resp = await client.post("/api/v1/rag/moderation/rules", json=rule_body)
        assert resp.status_code == 201, resp.text

        # Now have the AI emit a response containing that phrase
        async def fake_complete(req, user_id):
            return {
                "response": "Per [SYN-FCOM-3.1], the WIDGET-X42 specification details ...",
                "provider": "gemini", "model": "gemini-1.5-pro", "cached": False,
                "usage": {}, "citations": req.context_citations, "request_id": "req_y",
            }

        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.rewriter.AIService", new=mock_ai_cls),
        ):
            inst = mock_ai_cls.return_value
            inst.embed = AsyncMock(side_effect=_fake_embed)
            inst.complete = AsyncMock(side_effect=fake_complete)
            resp = await client.post(
                "/api/v1/ai-assistant/message", json={"content": "describe widget"}
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assistant = body["assistantMessage"]
            assert assistant["grounded"] == "blocked"
            assert assistant["moderation"]["violation_type"] == "banned_phrase"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_moderation_admin_endpoints_require_role(client, db_session):
    """Trainee gets 403 on POST /moderation/rules."""
    real_user = await _make_test_user(db_session)
    from app.main import app
    from app.modules.auth.deps import get_current_user
    from app.modules.auth.schemas import CurrentUser
    trainee = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    app.dependency_overrides[get_current_user] = lambda: trainee
    try:
        resp = await client.post(
            "/api/v1/rag/moderation/rules",
            json={"category": "casual", "pattern": "yolo", "action": "log", "severity": "low"},
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)
