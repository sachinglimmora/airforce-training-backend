"""Unit tests for QuizService — parse_questions, refusal short-circuit, prompt formatting."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.rag.prompts import QUIZ_GENERATION_SYSTEM_PROMPT
from app.modules.rag.quiz_service import QuizService
from app.modules.rag.service import RetrievalConfig, decide

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(roles: list[str] | None = None, user_id: str = "user-123") -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.roles = roles or ["trainee"]
    return u


def _make_hit(citation_keys: list[str], score: float, included: bool = True) -> MagicMock:
    from app.modules.rag.service import RetrievalHit

    return RetrievalHit(citation_keys=citation_keys, score=score, included=included)


# ---------------------------------------------------------------------------
# _parse_questions
# ---------------------------------------------------------------------------


class TestParseQuestions:
    def test_valid_json_array(self):
        questions = [{"id": 1, "question": "Q?", "options": [], "correct_answer": "A"}]
        raw = json.dumps(questions)
        result = QuizService._parse_questions(raw)
        assert result == questions

    def test_json_with_questions_key(self):
        questions = [{"id": 1, "question": "Q?", "options": [], "correct_answer": "B"}]
        raw = json.dumps({"questions": questions})
        result = QuizService._parse_questions(raw)
        assert result == questions

    def test_markdown_fenced_json_array(self):
        questions = [{"id": 1, "question": "What is EGT?", "options": [], "correct_answer": "C"}]
        raw = "```json\n" + json.dumps(questions) + "\n```"
        result = QuizService._parse_questions(raw)
        assert result == questions

    def test_markdown_fenced_no_lang_tag(self):
        questions = [{"id": 1, "question": "Q?", "options": [], "correct_answer": "D"}]
        raw = "```\n" + json.dumps(questions) + "\n```"
        result = QuizService._parse_questions(raw)
        assert result == questions

    def test_invalid_json_returns_empty_list(self):
        result = QuizService._parse_questions("this is not json at all")
        assert result == []

    def test_empty_string_returns_empty_list(self):
        result = QuizService._parse_questions("")
        assert result == []

    def test_json_object_without_questions_key_returns_empty_list(self):
        raw = json.dumps({"answers": []})
        result = QuizService._parse_questions(raw)
        assert result == []


# ---------------------------------------------------------------------------
# decide() — grounding levels
# ---------------------------------------------------------------------------


class TestDecide:
    def test_no_hits_returns_low(self):
        cfg = RetrievalConfig()
        result = decide([], cfg)
        assert result["grounded"] == "low"
        assert result["citation_keys"] == []

    def test_high_score_returns_strong(self):
        hit = _make_hit(["SU30-FCOM-1.1"], score=0.85)
        cfg = RetrievalConfig(strong_threshold=0.60)
        result = decide([hit], cfg)
        assert result["grounded"] == "strong"
        assert "SU30-FCOM-1.1" in result["citation_keys"]

    def test_mid_score_returns_weak(self):
        hit = _make_hit(["QRH-2.3"], score=0.45)
        cfg = RetrievalConfig(score_threshold=0.25, strong_threshold=0.60)
        result = decide([hit], cfg)
        assert result["grounded"] == "weak"

    def test_low_score_returns_low(self):
        hit = _make_hit(["QRH-2.3"], score=0.10)
        cfg = RetrievalConfig(score_threshold=0.25)
        result = decide([hit], cfg)
        assert result["grounded"] == "low"

    def test_excluded_hits_ignored(self):
        included_hit = _make_hit(["K1"], score=0.80, included=True)
        excluded_hit = _make_hit(["K2"], score=0.90, included=False)
        cfg = RetrievalConfig(strong_threshold=0.60)
        result = decide([included_hit, excluded_hit], cfg)
        assert "K1" in result["citation_keys"]
        assert "K2" not in result["citation_keys"]

    def test_duplicate_citation_keys_deduplicated(self):
        h1 = _make_hit(["K1", "K2"], score=0.70)
        h2 = _make_hit(["K2", "K3"], score=0.80)
        cfg = RetrievalConfig(strong_threshold=0.60)
        result = decide([h1, h2], cfg)
        # K2 should appear exactly once
        assert result["citation_keys"].count("K2") == 1


# ---------------------------------------------------------------------------
# Refusal short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_quiz_refusal_short_circuit():
    """When grounder returns 'refused', return early with no questions and no AI call."""
    db = AsyncMock()
    user = _make_user()

    with (
        patch("app.modules.rag.quiz_service.retrieve", return_value=([], "query")),
        patch(
            "app.modules.rag.quiz_service.decide",
            return_value={"grounded": "refused", "citation_keys": []},
        ),
        patch("app.modules.rag.quiz_service.AIService") as mock_ai,
    ):
        svc = QuizService(db)
        result = await svc.generate_quiz(
            topic="Engine start",
            aircraft_id=None,
            module_id=None,
            difficulty="intermediate",
            num_questions=5,
            user=user,
        )

    assert result["grounded"] == "refused"
    assert result["questions"] == []
    assert result["generated_count"] == 0
    mock_ai.return_value.complete.assert_not_called()


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


class TestPromptFormatting:
    def test_difficulty_in_prompt(self):
        prompt = QUIZ_GENERATION_SYSTEM_PROMPT.format(
            topic="Engine start",
            difficulty="advanced",
            num_questions=5,
            aircraft_context="Su-30MKI",
            audience_label="instructor",
        )
        assert "advanced" in prompt

    def test_num_questions_in_prompt(self):
        prompt = QUIZ_GENERATION_SYSTEM_PROMPT.format(
            topic="Engine start",
            difficulty="beginner",
            num_questions=3,
            aircraft_context="general",
            audience_label="trainee",
        )
        assert "3" in prompt

    def test_aircraft_context_in_prompt(self):
        prompt = QUIZ_GENERATION_SYSTEM_PROMPT.format(
            topic="Engine start",
            difficulty="intermediate",
            num_questions=5,
            aircraft_context="MiG-21",
            audience_label="trainee",
        )
        assert "MiG-21" in prompt

    def test_audience_label_in_prompt(self):
        prompt = QUIZ_GENERATION_SYSTEM_PROMPT.format(
            topic="Fuel system",
            difficulty="intermediate",
            num_questions=5,
            aircraft_context="general",
            audience_label="instructor",
        )
        assert "instructor" in prompt


# ---------------------------------------------------------------------------
# Full generate_quiz happy path (AIService mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_quiz_happy_path():
    db = AsyncMock()
    user = _make_user(roles=["trainee"])

    fake_questions = [
        {
            "id": 1,
            "question": "What is EGT limit?",
            "options": ["A) 600°C", "B) 750°C", "C) 850°C", "D) 950°C"],
            "correct_answer": "B",
            "explanation": "Per SU30-FCOM-3.2.1",
            "citation_key": "SU30-FCOM-3.2.1",
        }
    ]
    ai_response = json.dumps(fake_questions)
    mock_ai_result = {
        "response": ai_response,
        "provider": "gemini",
        "model": "gemini-pro",
        "cached": False,
        "usage": {},
        "citations": [],
        "request_id": "req_abc",
    }

    with (
        patch("app.modules.rag.quiz_service.retrieve", return_value=([], "query")),
        patch(
            "app.modules.rag.quiz_service.decide",
            return_value={"grounded": "low", "citation_keys": []},
        ),
        patch(
            "app.modules.rag.quiz_service._aircraft_context_label", new_callable=AsyncMock
        ) as mock_label,
        patch(
            "app.modules.rag.quiz_service._resolve_sources", new_callable=AsyncMock
        ) as mock_sources,
        patch("app.modules.rag.quiz_service.AIService") as mock_ai,
    ):
        mock_label.return_value = "general"
        mock_sources.return_value = []
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = mock_ai_result
        mock_ai.return_value = mock_instance

        svc = QuizService(db)
        result = await svc.generate_quiz(
            topic="Engine start",
            aircraft_id=None,
            module_id=None,
            difficulty="intermediate",
            num_questions=1,
            user=user,
        )

    assert result["generated_count"] == 1
    assert result["questions"] == fake_questions
    assert result["grounded"] == "low"
    mock_instance.complete.assert_called_once()


# ---------------------------------------------------------------------------
# num_questions validation — tested via Pydantic model (not the service)
# ---------------------------------------------------------------------------


class TestQuizRequestValidation:
    def test_valid_num_questions(self):
        from app.modules.ai_assistant.router import QuizRequest

        req = QuizRequest(topic="Engine start", num_questions=5)
        assert req.num_questions == 5

    def test_num_questions_zero_raises(self):
        from pydantic import ValidationError

        from app.modules.ai_assistant.router import QuizRequest

        with pytest.raises(ValidationError):
            QuizRequest(topic="Engine start", num_questions=0)

    def test_num_questions_eleven_raises(self):
        from pydantic import ValidationError

        from app.modules.ai_assistant.router import QuizRequest

        with pytest.raises(ValidationError):
            QuizRequest(topic="Engine start", num_questions=11)

    def test_default_num_questions(self):
        from app.modules.ai_assistant.router import QuizRequest

        req = QuizRequest(topic="Engine start")
        assert req.num_questions == 5

    def test_default_difficulty(self):
        from app.modules.ai_assistant.router import QuizRequest

        req = QuizRequest(topic="Engine start")
        assert req.difficulty == "intermediate"
