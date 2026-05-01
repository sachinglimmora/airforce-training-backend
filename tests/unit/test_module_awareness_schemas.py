"""Unit tests for Module Awareness (F12) — schemas and model fields."""
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.modules.ai_assistant.models import ChatSession
from app.modules.rag.schemas import ModuleContextOut, ModuleContextUpdate


def test_chat_session_has_module_fields():
    """ChatSession should accept the 4 new module-context fields."""
    sess = ChatSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        current_module_id="MODULE-7",
        current_step_id="STEP-3",
        module_context_data={"step_title": "Cold Weather Start"},
        context_updated_at=datetime.now(UTC),
    )
    assert sess.current_module_id == "MODULE-7"
    assert sess.current_step_id == "STEP-3"
    assert sess.module_context_data == {"step_title": "Cold Weather Start"}
    assert sess.context_updated_at is not None


def test_module_context_update_all_optional():
    """ModuleContextUpdate allows all fields to be omitted (partial update)."""
    m = ModuleContextUpdate()
    assert m.module_id is None
    assert m.step_id is None
    assert m.context_data is None


def test_module_context_update_populated():
    m = ModuleContextUpdate(
        module_id="MODULE-7",
        step_id="STEP-3",
        context_data={"step_title": "Cold Weather Start"},
    )
    assert m.module_id == "MODULE-7"
    assert m.step_id == "STEP-3"
    assert m.context_data == {"step_title": "Cold Weather Start"}


def test_module_context_update_module_id_max_length():
    """module_id longer than 128 chars should be rejected."""
    with pytest.raises(ValidationError):
        ModuleContextUpdate(module_id="X" * 129)


def test_module_context_update_step_id_max_length():
    """step_id longer than 128 chars should be rejected."""
    with pytest.raises(ValidationError):
        ModuleContextUpdate(step_id="Y" * 129)


def test_module_context_update_oversized_context_data_rejected():
    """context_data serializing to >10KB should raise ValidationError."""
    big_data = {"key": "v" * 11000}
    with pytest.raises(ValidationError, match="context_data"):
        ModuleContextUpdate(context_data=big_data)


def test_module_context_out_nullable_fields():
    """ModuleContextOut allows all nullable fields to be None."""
    out = ModuleContextOut(
        session_id=uuid.uuid4(),
        module_id=None,
        step_id=None,
        context_data=None,
        context_updated_at=None,
    )
    assert out.module_id is None
    assert out.step_id is None
    assert out.context_data is None
    assert out.context_updated_at is None


def test_module_context_out_populated():
    """ModuleContextOut serialises populated fields correctly."""
    sid = uuid.uuid4()
    now = datetime.now(UTC)
    out = ModuleContextOut(
        session_id=sid,
        module_id="MODULE-7",
        step_id="STEP-3",
        context_data={"step_title": "Cold Weather Start"},
        context_updated_at=now,
    )
    assert out.session_id == sid
    assert out.module_id == "MODULE-7"
    assert out.step_id == "STEP-3"
    assert out.context_data == {"step_title": "Cold Weather Start"}
    assert out.context_updated_at == now
