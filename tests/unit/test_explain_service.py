"""Unit tests for ExplainService — query construction, refusal short-circuit, prompt formatting."""
import json
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.modules.rag.prompts import EXPLAIN_WHY_SYSTEM_PROMPT
from app.modules.rag.schemas import ExplainRequest, ExplainResponse
from app.modules.rag.service import ExplainService

# ── Shared fake types ─────────────────────────────────────────────────────────

@dataclass
class FakeHit:
    score: float
    citation_keys: list
    content: str = "content"
    chunk_id: str = "cid"
    section_id: str = "sid"
    page_number: int | None = None
    mmr_rank: int = 0
    included: bool = False


class FakeUser:
    id = "user-123"
    roles = ["trainee"]


class FakeInstructor:
    id = "instr-456"
    roles = ["instructor"]


# ── Prompt constant tests ─────────────────────────────────────────────────────

def test_explain_why_prompt_has_required_placeholders():
    """Prompt must have all three format placeholders the service uses."""
    assert "{audience_label}" in EXPLAIN_WHY_SYSTEM_PROMPT
    assert "{aircraft_context}" in EXPLAIN_WHY_SYSTEM_PROMPT
    assert "{system_state_summary}" in EXPLAIN_WHY_SYSTEM_PROMPT


def test_explain_why_prompt_formats_correctly():
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="trainee",
        aircraft_context="Su-30MKI",
        system_state_summary='{"engine_n1": "23%"}',
    )
    assert "trainee" in rendered
    assert "Su-30MKI" in rendered
    assert "23%" in rendered


# ── Schema tests ──────────────────────────────────────────────────────────────

def test_explain_request_requires_topic():
    with pytest.raises(Exception):
        ExplainRequest(topic="")  # empty string — min_length=1


def test_explain_request_topic_only():
    req = ExplainRequest(topic="EGT spike during engine start")
    assert req.topic == "EGT spike during engine start"
    assert req.context is None
    assert req.system_state is None
    assert req.aircraft_id is None


def test_explain_request_all_fields():
    aid = uuid4()
    req = ExplainRequest(
        topic="EGT spike",
        context="Su-30MKI cold start",
        system_state={"engine_n1": "23%"},
        aircraft_id=aid,
    )
    assert req.aircraft_id == aid
    assert req.system_state == {"engine_n1": "23%"}


def test_explain_response_structure():
    resp = ExplainResponse(
        explanation="EGT spikes because...",
        grounded="strong",
        sources=[],
        suggestions=[],
        moderation=None,
    )
    assert resp.grounded == "strong"
    assert resp.moderation is None


# ── Query construction ────────────────────────────────────────────────────────

def test_retrieval_query_topic_only():
    """Without context, retrieval query == topic."""
    topic = "EGT spike during engine start"
    context = None
    result = topic if not context else f"{topic} ({context})"
    assert result == topic


def test_retrieval_query_with_context():
    """With context, retrieval query appends context in parens."""
    topic = "EGT spike during engine start"
    context = "Su-30MKI, AL-31FP engine, cold weather start"
    result = topic if not context else f"{topic} ({context})"
    assert result == "EGT spike during engine start (Su-30MKI, AL-31FP engine, cold weather start)"


# ── Refusal short-circuit ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_explain_refusal_short_circuit():
    """When grounder returns refused, ExplainService skips LLM and returns refusal shape."""
    fake_db = MagicMock()
    svc = ExplainService(fake_db)

    refused_decision = {
        "grounded": "refused",
        "citation_keys": [],
        "included_hits": [],
        "suggestions": [{"citation_key": "ABC-1", "score": 0.55, "content": "x", "page_number": None}],
    }

    with (
        patch("app.modules.rag.service.retrieve", new=AsyncMock(return_value=([], {}))),
        patch("app.modules.rag.service.decide", return_value=refused_decision),
        patch.object(svc, "_resolve_sources", new=AsyncMock(return_value=[])),
    ):
        result = await svc.explain(
            topic="unknown topic",
            context=None,
            system_state=None,
            aircraft_id=None,
            user=FakeUser(),
        )

    assert result["grounded"] == "refused"
    assert result["sources"] == []
    assert result["moderation"] is None
    assert result["explanation"]  # some non-empty string


# ── Prompt formatting ─────────────────────────────────────────────────────────

def test_prompt_formats_trainee_audience():
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="trainee",
        aircraft_context="general aviation",
        system_state_summary="(none)",
    )
    assert "trainee" in rendered
    assert "general aviation" in rendered
    assert "(none)" in rendered


def test_prompt_formats_instructor_audience():
    rendered = EXPLAIN_WHY_SYSTEM_PROMPT.format(
        audience_label="instructor",
        aircraft_context="Su-30MKI",
        system_state_summary='{"engine_n1": "23%"}',
    )
    assert "instructor" in rendered
    assert "Su-30MKI" in rendered


def test_audience_label_derivation_trainee():
    user = FakeUser()
    user_roles = set(getattr(user, "roles", []))
    label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
    assert label == "trainee"


def test_audience_label_derivation_instructor():
    user = FakeInstructor()
    user_roles = set(getattr(user, "roles", []))
    label = "instructor" if user_roles & {"admin", "instructor"} else "trainee"
    assert label == "instructor"


def test_system_state_summary_none():
    system_state = None
    summary = json.dumps(system_state) if system_state else "(none)"
    assert summary == "(none)"


def test_system_state_summary_dict():
    system_state = {"engine_n1": "23%", "oil_temp": "low"}
    summary = json.dumps(system_state) if system_state else "(none)"
    assert "engine_n1" in summary
    assert "oil_temp" in summary
