"""Unit tests for ProcedureService — skip detection, branch navigation, debrief."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procedures.service import ProcedureService

# ---------------------------------------------------------------------------
# Helpers — build lightweight mock ORM objects
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str | None = None,
    ordinal: int = 1,
    is_critical: bool = False,
    branch_condition: str | None = None,
    parent_step_id: str | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.UUID(step_id) if step_id else uuid.uuid4()
    s.ordinal = ordinal
    s.is_critical = is_critical
    s.branch_condition = branch_condition
    s.parent_step_id = uuid.UUID(parent_step_id) if parent_step_id else None
    return s


def _make_session(
    session_id: str | None = None,
    procedure_id: str | None = None,
    trainee_id: str | None = None,
    status: str = "in_progress",
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.UUID(session_id) if session_id else uuid.uuid4()
    s.procedure_id = uuid.UUID(procedure_id) if procedure_id else uuid.uuid4()
    s.trainee_id = uuid.UUID(trainee_id) if trainee_id else uuid.uuid4()
    s.status = status
    s.started_at = None
    s.ended_at = None
    return s


def _make_event(event_type: str, step_id: str | None = None, payload: dict | None = None):
    e = MagicMock()
    e.event_type = event_type
    e.step_id = uuid.UUID(step_id) if step_id else None
    e.payload = payload or {}
    return e


def _scalar_result(value):
    """Return a mock that mimics db.execute(...).scalar_one_or_none()."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _scalars_result(items: list):
    """Return a mock that mimics db.execute(...).scalars().all()."""
    r = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = items
    r.scalars.return_value = scalars
    return r


# ---------------------------------------------------------------------------
# detect_skips
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_skips_all_completed():
    """All procedure steps completed — no skip deviations should be created."""
    step_id = str(uuid.uuid4())
    session = _make_session()

    step = _make_step(step_id=step_id, ordinal=1, is_critical=False)
    completed_event = _make_event("step_completed", step_id=step_id)

    db = AsyncMock(spec=AsyncSession)
    db.add_all = MagicMock()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(session)
        if call_count == 2:
            return _scalars_result([step])
        if call_count == 3:
            return _scalars_result([completed_event])
        # branch_taken events
        return _scalars_result([])

    db.execute = _execute

    svc = ProcedureService(db)
    await svc.detect_skips(str(session.id))

    db.add_all.assert_not_called()


@pytest.mark.asyncio
async def test_detect_skips_noncritical_missed():
    """One non-critical step missed → Deviation with severity='major'."""
    session = _make_session()
    step_id = str(uuid.uuid4())
    step = _make_step(step_id=step_id, ordinal=2, is_critical=False)

    db = AsyncMock(spec=AsyncSession)
    added_deviations = []

    def _add_all(items):
        added_deviations.extend(items)

    db.add_all = _add_all

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(session)
        if call_count == 2:
            return _scalars_result([step])
        if call_count == 3:
            # no completed events
            return _scalars_result([])
        return _scalars_result([])

    db.execute = _execute

    svc = ProcedureService(db)
    await svc.detect_skips(str(session.id))

    assert len(added_deviations) == 1
    dev = added_deviations[0]
    assert dev.deviation_type == "skip"
    assert dev.severity == "major"
    assert dev.step_id == step.id


@pytest.mark.asyncio
async def test_detect_skips_critical_missed():
    """One critical step missed → Deviation with severity='critical'."""
    session = _make_session()
    step_id = str(uuid.uuid4())
    step = _make_step(step_id=step_id, ordinal=3, is_critical=True)

    db = AsyncMock(spec=AsyncSession)
    added_deviations = []
    db.add_all = lambda items: added_deviations.extend(items)

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(session)
        if call_count == 2:
            return _scalars_result([step])
        if call_count == 3:
            return _scalars_result([])
        return _scalars_result([])

    db.execute = _execute

    svc = ProcedureService(db)
    await svc.detect_skips(str(session.id))

    assert len(added_deviations) == 1
    assert added_deviations[0].severity == "critical"


@pytest.mark.asyncio
async def test_detect_skips_branch_excluded():
    """Steps listed in branch_taken skipped_step_ids are NOT flagged as skips."""
    session = _make_session()
    chosen_id = str(uuid.uuid4())
    skipped_id = str(uuid.uuid4())

    chosen_step = _make_step(step_id=chosen_id, ordinal=6, is_critical=True)
    skipped_step = _make_step(step_id=skipped_id, ordinal=6, is_critical=True)

    # completed events: both branch steps completed? No — only chosen is completed.
    completed_event = _make_event("step_completed", step_id=chosen_id)
    branch_event = _make_event(
        "branch_taken",
        payload={"skipped_step_ids": [skipped_id]},
    )

    db = AsyncMock(spec=AsyncSession)
    db.add_all = MagicMock()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(session)
        if call_count == 2:
            return _scalars_result([chosen_step, skipped_step])
        if call_count == 3:
            return _scalars_result([completed_event])
        return _scalars_result([branch_event])

    db.execute = _execute

    svc = ProcedureService(db)
    await svc.detect_skips(str(session.id))

    # skipped_step is excluded; chosen_step is completed — no deviations
    db.add_all.assert_not_called()


# ---------------------------------------------------------------------------
# take_branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_branch_unknown_condition():
    """Unknown condition raises HTTPException 400."""
    from fastapi import HTTPException

    parent_step_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    parent_step = _make_step(step_id=parent_step_id)
    session = _make_session(
        session_id=session_id,
        trainee_id=user_id,
    )

    child_a = _make_step(branch_condition="EGT normal")

    db = AsyncMock(spec=AsyncSession)
    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(parent_step)
        if call_count == 2:
            return _scalar_result(session)
        return _scalars_result([child_a])

    db.execute = _execute

    svc = ProcedureService(db)
    with pytest.raises(HTTPException) as exc_info:
        await svc.take_branch(
            session_id=session_id,
            step_id=parent_step_id,
            condition="does not exist",
            current_user_id=user_id,
        )
    assert exc_info.value.status_code == 400
    assert "does not exist" in exc_info.value.detail


@pytest.mark.asyncio
async def test_take_branch_valid_condition():
    """Valid condition returns correct chosen_step_id and skipped_count."""
    parent_step_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    parent_step = _make_step(step_id=parent_step_id)
    session = _make_session(session_id=session_id, trainee_id=user_id)

    chosen_id = str(uuid.uuid4())
    skipped_id = str(uuid.uuid4())
    child_a = _make_step(step_id=chosen_id, branch_condition="EGT normal")
    child_b = _make_step(step_id=skipped_id, branch_condition="EGT low cold weather")

    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    db.commit = AsyncMock()

    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(parent_step)
        if call_count == 2:
            return _scalar_result(session)
        return _scalars_result([child_a, child_b])

    db.execute = _execute

    svc = ProcedureService(db)
    result = await svc.take_branch(
        session_id=session_id,
        step_id=parent_step_id,
        condition="EGT normal",
        current_user_id=user_id,
    )

    assert result["chosen_step_id"] == chosen_id
    assert result["skipped_count"] == 1
    db.add.assert_called_once()
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# generate_debrief (prompt formatting + AIService mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_debrief_mocks_ai_service():
    """generate_debrief calls AIService.complete and returns structured response."""
    session_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    from datetime import UTC, datetime, timedelta

    started = datetime.now(UTC) - timedelta(seconds=300)
    ended = datetime.now(UTC)

    session = _make_session(session_id=session_id, trainee_id=user_id, status="completed")
    session.started_at = started
    session.ended_at = ended

    proc = MagicMock()
    proc.id = session.procedure_id
    proc.name = "Engine Start — Normal"
    proc.procedure_type = "normal"
    proc.phase = "ground"
    proc.aircraft_id = uuid.uuid4()

    db = AsyncMock(spec=AsyncSession)
    call_count = 0

    async def _execute(q):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _scalar_result(session)
        if call_count == 2:
            return _scalar_result(proc)
        if call_count == 3:
            # deviations
            return _scalars_result([])
        # steps count
        return _scalars_result([_make_step() for _ in range(8)])

    db.execute = _execute

    mock_ai_result = {
        "response": "Debrief text here.",
        "provider": "gemini",
        "model": "gemini-pro",
        "cached": False,
        "usage": {},
        "citations": [],
        "request_id": "req_123",
    }

    with patch(
        "app.modules.procedures.service.AIService"
    ) as mock_ai_service:
        mock_instance = AsyncMock()
        mock_instance.complete.return_value = mock_ai_result
        mock_ai_service.return_value = mock_instance

        svc = ProcedureService(db)
        result = await svc.generate_debrief(
            session_id=session_id,
            current_user_id=user_id,
            current_user_roles=["trainee"],
        )

    assert result["session_id"] == session_id
    assert result["debrief"] == "Debrief text here."
    assert result["deviation_count"] == 0
    assert result["audience"] == "trainee"
    mock_instance.complete.assert_called_once()
