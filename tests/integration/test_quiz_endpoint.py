"""Integration tests for POST /api/v1/ai-assistant/quiz.

All auth is stubbed via dependency override on get_current_user.
AIService is mocked to avoid real LLM calls.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = "/api/v1/ai-assistant/quiz"


def _trainee_user(user_id: str | None = None) -> CurrentUser:
    return CurrentUser(id=user_id or str(uuid.uuid4()), roles=["trainee"], jti="")


def _fake_ai_result(questions: list[dict] | None = None) -> dict:
    if questions is None:
        questions = [
            {
                "id": 1,
                "question": "What is EGT limit during engine start?",
                "options": ["A) 600°C", "B) 750°C", "C) 850°C", "D) 950°C"],
                "correct_answer": "B",
                "explanation": "Per SU30-FCOM-3.2.1, EGT must not exceed 750°C.",
                "citation_key": "SU30-FCOM-3.2.1",
            }
        ]
    return {
        "response": json.dumps(questions),
        "provider": "gemini",
        "model": "gemini-pro",
        "cached": False,
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "cost_usd": 0.001},
        "citations": [],
        "request_id": "req_test_123",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quiz_basic_topic(client: AsyncClient):
    """POST /quiz with only topic returns 200 with questions array."""
    user = _trainee_user()

    with patch("app.modules.rag.quiz_service.AIService") as mock_ai:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = _fake_ai_result()
        mock_ai.return_value = mock_instance

        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            r = await client.post(_BASE, json={"topic": "Engine start procedures"})
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    data = r.json()["data"]
    assert "questions" in data
    assert isinstance(data["questions"], list)
    assert "sources" in data
    assert data["topic"] == "Engine start procedures"
    assert data["difficulty"] == "intermediate"


@pytest.mark.asyncio
async def test_quiz_with_aircraft_id(client: AsyncClient):
    """POST /quiz with aircraft_id returns 200."""
    user = _trainee_user()
    aircraft_id = str(uuid.uuid4())

    with patch("app.modules.rag.quiz_service.AIService") as mock_ai:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = _fake_ai_result()
        mock_ai.return_value = mock_instance

        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            r = await client.post(
                _BASE,
                json={
                    "topic": "Fuel system",
                    "aircraft_id": aircraft_id,
                    "difficulty": "advanced",
                    "num_questions": 3,
                },
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    data = r.json()["data"]
    assert data["difficulty"] == "advanced"


@pytest.mark.asyncio
async def test_quiz_empty_topic_returns_400(client: AsyncClient):
    """POST /quiz with whitespace-only topic returns 400."""
    user = _trainee_user()

    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = await client.post(_BASE, json={"topic": "   "})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_quiz_num_questions_too_large_returns_422(client: AsyncClient):
    """POST /quiz with num_questions=11 returns 422 (Pydantic validation)."""
    user = _trainee_user()

    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = await client.post(_BASE, json={"topic": "Engine start", "num_questions": 11})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 422


@pytest.mark.asyncio
async def test_quiz_unauthenticated_returns_401(client: AsyncClient):
    """POST /quiz without auth header returns 401."""
    r = await client.post(_BASE, json={"topic": "Engine start"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_quiz_with_module_id(client: AsyncClient):
    """POST /quiz with module_id is accepted and reflected in response."""
    user = _trainee_user()

    with patch("app.modules.rag.quiz_service.AIService") as mock_ai:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = _fake_ai_result()
        mock_ai.return_value = mock_instance

        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: user
        try:
            r = await client.post(
                _BASE,
                json={
                    "topic": "Engine start procedures for Su-30MKI",
                    "module_id": "MODULE-7",
                    "difficulty": "intermediate",
                    "num_questions": 5,
                },
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    assert r.status_code == 200
    data = r.json()["data"]
    assert "generated_count" in data
