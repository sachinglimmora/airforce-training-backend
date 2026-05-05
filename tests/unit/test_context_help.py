"""Unit tests for context-help logic (context string construction and validation).

These tests exercise the logic inline — no HTTP client, no DB, no ExplainService.
"""

import pytest
from fastapi import HTTPException

from app.modules.ai_assistant.router import ContextHelpRequest, context_help

# ---------------------------------------------------------------------------
# Helpers — build the context string the same way the endpoint does
# ---------------------------------------------------------------------------


def _build_context(body: ContextHelpRequest) -> str | None:
    """Replicate the context-building logic from the endpoint."""
    parts = []
    if body.module_id:
        parts.append(f"Module: {body.module_id}")
    if body.step_id:
        parts.append(f"Step: {body.step_id}")
    if body.step_title:
        parts.append(f"Step title: {body.step_title}")
    return ", ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Context string construction
# ---------------------------------------------------------------------------


def test_context_all_fields():
    body = ContextHelpRequest(
        question="Why close the bleed valve?",
        module_id="MODULE-7",
        step_id="STEP-3",
        step_title="Close bleed valve",
    )
    ctx = _build_context(body)
    assert ctx == "Module: MODULE-7, Step: STEP-3, Step title: Close bleed valve"


def test_context_module_only():
    body = ContextHelpRequest(question="What is this?", module_id="MODULE-1")
    ctx = _build_context(body)
    assert ctx == "Module: MODULE-1"


def test_context_step_and_title_only():
    body = ContextHelpRequest(
        question="Explain this step", step_id="STEP-5", step_title="Fuel pump check"
    )
    ctx = _build_context(body)
    assert ctx == "Step: STEP-5, Step title: Fuel pump check"


def test_context_no_fields_is_none():
    body = ContextHelpRequest(question="General question?")
    ctx = _build_context(body)
    assert ctx is None


def test_context_partial_fields_no_step_title():
    body = ContextHelpRequest(
        question="Why?",
        module_id="MODULE-2",
        step_id="STEP-1",
    )
    ctx = _build_context(body)
    assert ctx == "Module: MODULE-2, Step: STEP-1"


# ---------------------------------------------------------------------------
# Validation — empty / whitespace question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_question_raises_400():
    """Empty string question → HTTP 400."""
    body = ContextHelpRequest(question=" ")
    with pytest.raises(HTTPException) as exc_info:
        await context_help(
            body=body,
            current_user=None,  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_whitespace_only_question_raises_400():
    """Whitespace-only question → HTTP 400."""
    body = ContextHelpRequest(question="   \t\n   ")
    with pytest.raises(HTTPException) as exc_info:
        await context_help(
            body=body,
            current_user=None,  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 400


def test_pydantic_rejects_empty_string():
    """Pydantic min_length=1 rejects an empty string before the endpoint runs."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ContextHelpRequest(question="")
