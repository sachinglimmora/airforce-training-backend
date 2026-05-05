"""Integration tests for Procedures Engine endpoints.

These tests use an in-memory SQLite-compatible test DB via conftest.py fixtures.
All auth is stubbed via dependency override on get_current_user.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.models import SessionEvent, TrainingSession
from app.modules.auth.schemas import CurrentUser
from app.modules.procedures.models import Deviation, Procedure, ProcedureSession, ProcedureStep

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trainee_user(user_id: str) -> CurrentUser:
    return CurrentUser(id=user_id, roles=["trainee"], jti="")


def _instructor_user(user_id: str) -> CurrentUser:
    return CurrentUser(id=user_id, roles=["instructor"], jti="")


async def _seed_procedure(db: AsyncSession) -> tuple[Procedure, list[ProcedureStep]]:
    """Create a minimal procedure with 3 steps (1 critical, 2 non-critical) for testing."""
    proc = Procedure(
        name="Test Engine Start",
        procedure_type="normal",
        phase="ground",
    )
    db.add(proc)
    await db.flush()

    step1 = ProcedureStep(
        procedure_id=proc.id,
        ordinal=1,
        action_text="Step 1 — non-critical",
        mode="do_verify",
        is_critical=False,
        target_time_seconds=10,
    )
    step2 = ProcedureStep(
        procedure_id=proc.id,
        ordinal=2,
        action_text="Step 2 — critical",
        mode="do_verify",
        is_critical=True,
        target_time_seconds=10,
    )
    step3 = ProcedureStep(
        procedure_id=proc.id,
        ordinal=3,
        action_text="Step 3 — branch point",
        mode="do_verify",
        is_critical=True,
        target_time_seconds=10,
    )
    db.add_all([step1, step2, step3])
    await db.flush()

    # Two branch children off step3
    branch_a = ProcedureStep(
        procedure_id=proc.id,
        ordinal=4,
        action_text="Branch A — normal",
        mode="do_verify",
        is_critical=False,
        parent_step_id=step3.id,
        branch_condition="normal",
    )
    branch_b = ProcedureStep(
        procedure_id=proc.id,
        ordinal=4,
        action_text="Branch B — abnormal",
        mode="do_verify",
        is_critical=True,
        parent_step_id=step3.id,
        branch_condition="abnormal",
    )
    db.add_all([branch_a, branch_b])
    await db.flush()

    return proc, [step1, step2, step3, branch_a, branch_b]


async def _seed_session(
    db: AsyncSession, proc: Procedure, trainee_id: str
) -> ProcedureSession:
    """Create a TrainingSession + ProcedureSession pair."""
    ts = TrainingSession(
        trainee_id=uuid.UUID(trainee_id),
        session_type="procedure",
        procedure_id=proc.id,
        status="in_progress",
    )
    db.add(ts)
    await db.flush()

    ps = ProcedureSession(id=ts.id, procedure_id=proc.id, trainee_id=uuid.UUID(trainee_id))
    db.add(ps)
    await db.flush()
    return ps


# ---------------------------------------------------------------------------
# POST /branch — as session owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_as_owner(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, steps = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)
    await db_session.commit()

    step3 = steps[2]  # branch point

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    try:
        r = await client.post(
            f"/api/v1/procedures/sessions/{session.id}/steps/{step3.id}/branch",
            json={"condition": "normal"},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert "chosen_step_id" in data
        assert data["skipped_count"] == 1

        # Verify SessionEvent was written
        event_result = await db_session.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
            .where(SessionEvent.event_type == "branch_taken")
        )
        event = event_result.scalar_one_or_none()
        assert event is not None
        assert event.payload["condition"] == "normal"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /branch — unknown condition → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_unknown_condition(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, steps = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)
    await db_session.commit()

    step3 = steps[2]

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    try:
        r = await client.post(
            f"/api/v1/procedures/sessions/{session.id}/steps/{step3.id}/branch",
            json={"condition": "nonexistent condition"},
        )
        assert r.status_code == 400, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /complete — critical step skipped → Deviation severity=critical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_session_critical_skip(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, steps = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)

    # Only complete step1 — step2 (critical) and step3 (critical) are skipped
    step1 = steps[0]
    event = SessionEvent(
        session_id=session.id,
        event_type="step_completed",
        step_id=step1.id,
        payload={},
    )
    db_session.add(event)
    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    try:
        r = await client.post(f"/api/v1/procedures/sessions/{session.id}/complete")
        assert r.status_code == 200, r.text

        # Check deviations
        devs_result = await db_session.execute(
            select(Deviation)
            .where(Deviation.session_id == session.id)
            .where(Deviation.severity == "critical")
        )
        critical_devs = devs_result.scalars().all()
        assert len(critical_devs) >= 1  # step2 and step3 are both critical
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /complete — non-critical step skipped → Deviation severity=major
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_session_major_skip(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, steps = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)

    step1, step2, step3, branch_a, branch_b = steps

    # Complete critical steps (step2, step3) and take branch A — skip step1 (non-critical)
    for s in [step2, step3]:
        event = SessionEvent(
            session_id=session.id,
            event_type="step_completed",
            step_id=s.id,
            payload={},
        )
        db_session.add(event)

    # Branch event excluding branch_b
    branch_event = SessionEvent(
        session_id=session.id,
        event_type="branch_taken",
        payload={
            "condition": "normal",
            "chosen_step_id": str(branch_a.id),
            "skipped_step_ids": [str(branch_b.id)],
        },
    )
    db_session.add(branch_event)

    # Complete branch_a
    db_session.add(
        SessionEvent(
            session_id=session.id,
            event_type="step_completed",
            step_id=branch_a.id,
            payload={},
        )
    )

    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    try:
        r = await client.post(f"/api/v1/procedures/sessions/{session.id}/complete")
        assert r.status_code == 200, r.text

        devs_result = await db_session.execute(
            select(Deviation)
            .where(Deviation.session_id == session.id)
            .where(Deviation.deviation_type == "skip")
            .where(Deviation.severity == "major")
        )
        major_devs = devs_result.scalars().all()
        # step1 is non-critical and was skipped
        assert len(major_devs) >= 1
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /debrief — completed session → 200 with debrief text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debrief_completed_session(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, steps = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)
    session.status = "completed"
    session.ended_at = datetime.now(UTC)
    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    mock_ai_result = {
        "response": "Debrief: you missed step 2.",
        "provider": "gemini",
        "model": "gemini-pro",
        "cached": False,
        "usage": {},
        "citations": [],
        "request_id": "req_test",
    }

    try:
        with patch(
            "app.modules.procedures.service.AIService"
        ) as mock_ai:
            mock_instance = AsyncMock()
            mock_instance.complete.return_value = mock_ai_result
            mock_ai.return_value = mock_instance

            r = await client.post(f"/api/v1/procedures/sessions/{session.id}/debrief")
            assert r.status_code == 200, r.text
            data = r.json()["data"]
            assert "debrief" in data
            assert len(data["debrief"]) > 0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /debrief — in-progress session → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debrief_inprogress_session(client: AsyncClient, db_session: AsyncSession):
    trainee_id = str(uuid.uuid4())
    proc, _ = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, trainee_id)
    # session is in_progress by default
    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(trainee_id)

    try:
        r = await client.post(f"/api/v1/procedures/sessions/{session.id}/debrief")
        assert r.status_code == 400, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /deviations — wrong trainee → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deviations_wrong_trainee(client: AsyncClient, db_session: AsyncSession):
    real_trainee_id = str(uuid.uuid4())
    other_trainee_id = str(uuid.uuid4())

    proc, _ = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, real_trainee_id)
    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    # different trainee attempts to access
    app.dependency_overrides[get_current_user] = lambda: _trainee_user(other_trainee_id)

    try:
        r = await client.get(f"/api/v1/procedures/sessions/{session.id}/deviations")
        assert r.status_code == 403, r.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /deviations — instructor → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deviations_instructor(client: AsyncClient, db_session: AsyncSession):
    real_trainee_id = str(uuid.uuid4())
    instructor_id = str(uuid.uuid4())

    proc, _ = await _seed_procedure(db_session)
    session = await _seed_session(db_session, proc, real_trainee_id)
    await db_session.commit()

    from app.database import get_db
    from app.main import app
    from app.modules.auth.deps import get_current_user

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: _instructor_user(instructor_id)

    try:
        r = await client.get(f"/api/v1/procedures/sessions/{session.id}/deviations")
        assert r.status_code == 200, r.text
        assert "data" in r.json()
    finally:
        app.dependency_overrides.clear()
