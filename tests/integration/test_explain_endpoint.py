"""Integration tests for POST /api/v1/ai-assistant/explain (F3)."""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.content.models import ContentReference
from app.modules.rag.tasks import embed_source
from tests.fixtures.synthetic_fcom import seed_synthetic_fcom

# ── Helpers ───────────────────────────────────────────────────────────────────

async def fake_embed_factory(*args, **kwargs):
    """AsyncMock side_effect — returns one 1536-dim vector per input text."""
    texts = args[0] if args else kwargs.get("texts", [])
    return {
        "embeddings": [[0.1] * 1536 for _ in texts],
        "model": "text-embedding-3-small",
        "usage": {"total_tokens": 100},
    }


async def _ingest(db_session):
    """Seed content + embed so the retriever has indexed chunks to hit."""
    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=fake_embed_factory)
        await asyncio.to_thread(embed_source, str(source.id))
    refs = (await db_session.execute(
        select(ContentReference).where(ContentReference.source_id == source.id)
    )).scalars().all()
    return source, [r.citation_key for r in refs]


def _fake_complete_factory(primary_key: str):
    async def fake_complete(req, user_id):
        return {
            "response": f"EGT spikes because of fuel introduction. [{primary_key}]",
            "provider": "gemini",
            "model": "gemini-1.5-pro",
            "cached": False,
            "usage": {"prompt_tokens": 10, "completion_tokens": 30, "cost_usd": 0.0001},
            "citations": req.context_citations,
            "request_id": "req_explain_1",
        }
    return fake_complete


async def _seed_user(db_session):
    """Insert a real user row and return (User, CurrentUser) pair."""
    from app.modules.auth.models import User
    from app.modules.auth.schemas import CurrentUser

    real_user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Explain Test User",
    )
    db_session.add(real_user)
    await db_session.commit()
    fake_user = CurrentUser(id=str(real_user.id), roles=["trainee"], jti="")
    return real_user, fake_user


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_explain_returns_grounded_explanation(client, db_session):
    """Happy path: grounded explanation with sources returned."""
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]

    from app.main import app
    from app.modules.auth.deps import get_current_user

    _real_user, fake_user = await _seed_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
        ):
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=_fake_complete_factory(primary_key))

            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "EGT spike during engine start"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert "explanation" in data
            assert data["grounded"] in ("strong", "soft")
            assert primary_key in data["explanation"]
            returned_keys = {s["citation_key"] for s in data["sources"]}
            assert returned_keys & set(citation_keys), (
                f"expected at least one of {citation_keys} in sources, got {returned_keys}"
            )
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_no_aircraft_searches_general(client, db_session):
    """Without aircraft_id, retrieval proceeds with no scope filter."""
    _source, citation_keys = await _ingest(db_session)
    primary_key = citation_keys[0]

    from app.main import app
    from app.modules.auth.deps import get_current_user

    _real_user, fake_user = await _seed_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
        ):
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=_fake_complete_factory(primary_key))

            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "bleed valve before takeoff"},
                # no aircraft_id — general scope
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            # Retriever may or may not match — both outcomes are valid
            assert data["grounded"] in ("strong", "soft", "refused")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_empty_topic_returns_400(client, db_session):
    """Whitespace-only topic must return 400 before hitting RAG."""
    from app.main import app
    from app.modules.auth.deps import get_current_user

    _real_user, fake_user = await _seed_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    try:
        resp = await client.post(
            "/api/v1/ai-assistant/explain",
            json={"topic": "   "},  # whitespace only — Pydantic passes (len>0), endpoint rejects
        )
        assert resp.status_code == 400, resp.text
        assert "topic" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_explain_unauthenticated_returns_401(client, db_session):
    """No auth dependency override → 401 from get_current_user."""
    # Remove any override that may have leaked from another test
    from app.main import app
    from app.modules.auth.deps import get_current_user
    app.dependency_overrides.pop(get_current_user, None)

    resp = await client.post(
        "/api/v1/ai-assistant/explain",
        json={"topic": "EGT spike"},
    )
    assert resp.status_code == 401, resp.text


async def test_explain_blocked_by_moderator_returns_blocked_shape(client, db_session):
    """When ExplainService.explain returns grounded=blocked, endpoint returns blocked shape."""
    from app.main import app
    from app.modules.auth.deps import get_current_user

    _real_user, fake_user = await _seed_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: fake_user

    blocked_result = {
        "explanation": "This response was blocked by the content moderation layer.",
        "grounded": "blocked",
        "sources": [],
        "suggestions": [],
        "moderation": {"violation_type": "classification", "severity": "critical"},
    }

    try:
        # Patch the ExplainService.explain method so we test the router shape handling
        with patch(
            "app.modules.ai_assistant.router.ExplainService.explain",
            new=AsyncMock(return_value=blocked_result),
        ):
            resp = await client.post(
                "/api/v1/ai-assistant/explain",
                json={"topic": "explain classified weapon specs"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["grounded"] == "blocked"
            assert data["moderation"] is not None
            assert data["moderation"]["violation_type"] == "classification"
            assert data["sources"] == []
    finally:
        app.dependency_overrides.pop(get_current_user, None)
