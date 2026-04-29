"""Integration tests for F12 Module Awareness — PUT/GET context endpoints + RAG injection."""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.modules.ai_assistant.models import ChatSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import User
from app.modules.auth.schemas import CurrentUser

settings = get_settings()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(settings.DATABASE_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_user(db: AsyncSession, roles: list[str] | None = None) -> tuple[User, CurrentUser]:
    roles = roles or ["trainee"]
    user = User(
        id=uuid.uuid4(),
        email=f"test-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        full_name="Test User",
    )
    db.add(user)
    await db.commit()
    current = CurrentUser(id=str(user.id), roles=roles, jti="")
    return user, current


async def _make_session(db: AsyncSession, user_id: uuid.UUID) -> ChatSession:
    sess = ChatSession(id=uuid.uuid4(), user_id=user_id)
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


async def test_put_context_as_owner_returns_200(client, db_session):
    """Session owner can set module context."""
    owner, fake_user = await _make_user(db_session)
    sess = await _make_session(db_session, owner.id)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        resp = await client.put(
            f"/api/v1/ai-assistant/sessions/{sess.id}/context",
            json={
                "module_id": "MODULE-7",
                "step_id": "STEP-3",
                "context_data": {"step_title": "Cold Weather Start"},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["module_id"] == "MODULE-7"
        assert body["step_id"] == "STEP-3"
        assert body["context_data"] == {"step_title": "Cold Weather Start"}
        assert body["context_updated_at"] is not None
        assert body["session_id"] == str(sess.id)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_put_context_as_instructor_on_other_session_returns_200(client, db_session):
    """Instructor can update any session's context."""
    owner, _ = await _make_user(db_session)
    sess = await _make_session(db_session, owner.id)
    _, instructor = await _make_user(db_session, roles=["instructor"])

    app.dependency_overrides[get_current_user] = lambda: instructor
    try:
        resp = await client.put(
            f"/api/v1/ai-assistant/sessions/{sess.id}/context",
            json={"module_id": "MODULE-2"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["module_id"] == "MODULE-2"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_put_context_as_different_trainee_returns_403(client, db_session):
    """A different trainee cannot update someone else's session context."""
    owner, _ = await _make_user(db_session)
    sess = await _make_session(db_session, owner.id)
    _, other_trainee = await _make_user(db_session, roles=["trainee"])

    app.dependency_overrides[get_current_user] = lambda: other_trainee
    try:
        resp = await client.put(
            f"/api/v1/ai-assistant/sessions/{sess.id}/context",
            json={"module_id": "HACK"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_get_context_returns_current_state(client, db_session):
    """GET returns what was previously PUT."""
    owner, fake_user = await _make_user(db_session)
    sess = await _make_session(db_session, owner.id)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        await client.put(
            f"/api/v1/ai-assistant/sessions/{sess.id}/context",
            json={"module_id": "MODULE-5", "step_id": "STEP-1"},
        )
        resp = await client.get(f"/api/v1/ai-assistant/sessions/{sess.id}/context")
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["module_id"] == "MODULE-5"
        assert body["step_id"] == "STEP-1"
        assert body["session_id"] == str(sess.id)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_get_context_nonexistent_session_returns_404(client, db_session):
    """GET for a session that does not exist returns 404."""
    _, fake_user = await _make_user(db_session)
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        resp = await client.get(f"/api/v1/ai-assistant/sessions/{uuid.uuid4()}/context")
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_rag_answer_injects_module_context(client, db_session):
    """After PUT /context, RAGService.answer() includes the module block in system prompt."""
    from app.modules.rag.tasks import embed_source
    from tests.fixtures.synthetic_fcom import seed_synthetic_fcom

    async def fake_embed_factory(*args, **kwargs):
        texts = args[0] if args else kwargs.get("texts", [])
        return {
            "embeddings": [[0.1] * 1536 for _ in texts],
            "model": "text-embedding-3-small",
            "usage": {"total_tokens": 100},
        }

    source = await seed_synthetic_fcom(db_session)
    await db_session.commit()
    with patch("app.modules.ai.service.AIService") as mock_ai:
        mock_ai.return_value.embed = AsyncMock(side_effect=fake_embed_factory)
        await asyncio.to_thread(embed_source, str(source.id))

    owner, fake_user = await _make_user(db_session)
    sess = await _make_session(db_session, owner.id)

    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        put_resp = await client.put(
            f"/api/v1/ai-assistant/sessions/{sess.id}/context",
            json={
                "module_id": "MODULE-7",
                "step_id": "STEP-3",
                "context_data": {"step_title": "Cold Weather Start"},
            },
        )
        assert put_resp.status_code == 200, put_resp.text

        captured_messages: list[dict] = []

        async def fake_complete(req, user_id):
            captured_messages.extend(req.messages)
            return {
                "response": "Module context answer",
                "provider": "gemini",
                "model": "gemini-1.5-pro",
                "cached": False,
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "cost_usd": 0.0001},
                "citations": req.context_citations,
                "request_id": "req_ctx",
            }

        with (
            patch("app.modules.ai.service.AIService") as mock_ai_cls,
            patch("app.modules.rag.service.AIService", new=mock_ai_cls),
            patch("app.modules.rag.rewriter.AIService", new=mock_ai_cls),
        ):
            instance = mock_ai_cls.return_value
            instance.embed = AsyncMock(side_effect=fake_embed_factory)
            instance.complete = AsyncMock(side_effect=fake_complete)

            msg_resp = await client.post(
                "/api/v1/ai-assistant/message",
                json={"content": "why cold weather?", "session_id": str(sess.id)},
            )
            assert msg_resp.status_code == 200, msg_resp.text

        # messages may be MessageIn Pydantic objects or plain dicts depending on serialisation
        def _role(m) -> str:
            return m.role if hasattr(m, "role") else m["role"]

        def _content(m) -> str:
            return m.content if hasattr(m, "content") else m["content"]

        system_msgs = [m for m in captured_messages if _role(m) == "system"]
        assert system_msgs, "No system message captured in AIService.complete call"
        sys_content = _content(system_msgs[0])
        assert "MODULE-7" in sys_content, (
            f"Module ID not in system prompt. Prompt start: {sys_content[:400]}"
        )
        assert "STEP-3" in sys_content, (
            f"Step ID not in system prompt. Prompt start: {sys_content[:400]}"
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
