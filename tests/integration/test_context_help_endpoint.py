"""Integration tests for POST /api/v1/ai-assistant/context-help.

ExplainService lives in app.modules.rag.service (PR #4). If that PR has not been
merged into the current environment, the entire module is skipped gracefully.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

# Skip the whole module if PR #4 (ExplainService) is not yet merged.
pytest.importorskip("app.modules.rag.service", reason="ExplainService not yet available")

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.modules.auth.deps import get_current_user  # noqa: E402
from app.modules.auth.schemas import CurrentUser  # noqa: E402

_ENDPOINT = "/api/v1/ai-assistant/context-help"

_MOCK_RESULT = {
    "explanation": "You close the bleed valve before takeoff to prevent engine surge.",
    "grounded": "strong",
    "sources": [{"title": "AFM Section 4", "page": 12}],
    "suggestions": [],
    "moderation": None,
}


def _user() -> CurrentUser:
    return CurrentUser(id="user-test-001", roles=["trainee"], jti="")


# ---------------------------------------------------------------------------
# POST /context-help — question only → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_help_question_only(client: AsyncClient, db_session):
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with patch("app.modules.rag.service.ExplainService") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.explain = AsyncMock(return_value=_MOCK_RESULT)
            mock_cls.return_value = mock_instance

            r = await client.post(
                _ENDPOINT,
                json={"question": "Why do we close the bleed valve before takeoff?"},
            )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "explanation" in data
        assert "grounded" in data
        assert "sources" in data
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /context-help — full context → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_help_full_context(client: AsyncClient, db_session):
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        with patch("app.modules.rag.service.ExplainService") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.explain = AsyncMock(return_value=_MOCK_RESULT)
            mock_cls.return_value = mock_instance

            r = await client.post(
                _ENDPOINT,
                json={
                    "question": "Why do we close the bleed valve before takeoff?",
                    "module_id": "MODULE-7",
                    "step_id": "STEP-3",
                    "step_title": "Close bleed valve",
                    "system_state": {"engine_n1": "85%", "altitude": "ground"},
                },
            )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["explanation"] == _MOCK_RESULT["explanation"]
        assert data["grounded"] == "strong"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /context-help — empty question → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_help_empty_question(client: AsyncClient, db_session):
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = lambda: db_session

    try:
        r = await client.post(_ENDPOINT, json={"question": "   "})
        assert r.status_code == 400, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /context-help — unauthenticated → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_help_unauthenticated(client: AsyncClient):
    # No dependency override — real auth guard fires
    r = await client.post(
        _ENDPOINT,
        json={"question": "Why close the bleed valve?"},
    )
    assert r.status_code == 401, r.text
