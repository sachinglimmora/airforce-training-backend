"""Integration tests for Scenario Engine endpoints.

Uses the shared db_session + client fixtures from tests/conftest.py.
All DB objects are created via ORM and rolled back after each test.
JWT auth is bypassed by overriding get_current_user on the app.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.schemas import CurrentUser
from app.modules.scenarios.models import Scenario, ScenarioAction, ScenarioSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_user(roles: list[str] = None) -> CurrentUser:
    return CurrentUser(id=str(uuid.uuid4()), roles=roles or ["trainee"])


def _override_user(app, user: CurrentUser):
    from app.modules.auth.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


async def _seed_user(db: AsyncSession, roles: list[str] | None = None) -> User:
    """Insert a User row + Role + UserRole and return the User."""
    user = User(
        id=uuid.uuid4(),
        email=f"user_{uuid.uuid4().hex[:8]}@test.com",
        password_hash="hashed",
        full_name="Test User",
    )
    db.add(user)
    await db.flush()

    for role_name in (roles or ["trainee"]):
        role_result = await db.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Role).where(Role.name == role_name)
        )
        role = role_result.scalar_one_or_none()
        if not role:
            role = Role(id=uuid.uuid4(), name=role_name)
            db.add(role)
            await db.flush()

        ur = UserRole(user_id=user.id, role_id=role.id)
        db.add(ur)

    await db.flush()
    await db.refresh(user)
    return user


async def _seed_scenario(
    db: AsyncSession,
    trigger_event: str | None = None,
    procedure_id: uuid.UUID | None = None,
) -> Scenario:
    sc = Scenario(
        id=uuid.uuid4(),
        scenario_code=f"SC_{uuid.uuid4().hex[:6].upper()}",
        name="V1 Cut Test",
        scenario_type="v1_cut",
        trigger_config={"event": trigger_event} if trigger_event else None,
        procedure_id=procedure_id,
    )
    db.add(sc)
    await db.flush()
    return sc


async def _seed_session(
    db: AsyncSession,
    scenario: Scenario,
    trainee: User,
    status: str = "in_progress",
) -> ScenarioSession:
    sess = ScenarioSession(
        id=uuid.uuid4(),
        scenario_id=scenario.id,
        trainee_id=trainee.id,
        status=status,
        started_at=datetime.now(UTC),
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# Trigger tests
# ---------------------------------------------------------------------------


class TestTriggerEndpoint:
    @pytest.mark.asyncio
    async def test_trigger_correct_event_200(self, client: AsyncClient, db_session: AsyncSession):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session, trigger_event="engine_failure_at_v1")
        session = await _seed_session(db_session, scenario, trainee)

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(
            f"/api/v1/scenarios/sessions/{session.id}/trigger",
            json={"event": "engine_failure_at_v1"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["trigger"] == "engine_failure_at_v1"
        assert data["fired_at"] is not None

    @pytest.mark.asyncio
    async def test_trigger_wrong_event_400(self, client: AsyncClient, db_session: AsyncSession):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session, trigger_event="engine_failure_at_v1")
        session = await _seed_session(db_session, scenario, trainee)

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(
            f"/api/v1/scenarios/sessions/{session.id}/trigger",
            json={"event": "windshear"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_trigger_twice_400(self, client: AsyncClient, db_session: AsyncSession):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session, trigger_event="engine_failure_at_v1")
        session = await _seed_session(db_session, scenario, trainee)
        # Fire it once directly
        session.trigger_fired_at = datetime.now(UTC)
        await db_session.flush()

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(
            f"/api/v1/scenarios/sessions/{session.id}/trigger",
            json={"event": "engine_failure_at_v1"},
        )
        assert resp.status_code == 400
        assert "already fired" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Action tests
# ---------------------------------------------------------------------------


class TestActionEndpoint:
    @pytest.mark.asyncio
    async def test_action_in_progress_200(self, client: AsyncClient, db_session: AsyncSession):
        from sqlalchemy import select

        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="in_progress")

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(
            f"/api/v1/scenarios/sessions/{session.id}/action",
            json={"action": "throttle_idle", "payload": {}},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["recorded"] is True
        assert data["action"] == "throttle_idle"
        assert "recorded_at" in data

        # Verify DB row exists
        result = await db_session.execute(
            select(ScenarioAction).where(ScenarioAction.session_id == session.id)
        )
        actions = result.scalars().all()
        assert len(actions) == 1
        assert actions[0].action == "throttle_idle"

    @pytest.mark.asyncio
    async def test_action_on_completed_session_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="completed")

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(
            f"/api/v1/scenarios/sessions/{session.id}/action",
            json={"action": "throttle_idle"},
        )
        assert resp.status_code == 400
        assert "not in progress" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Complete session tests
# ---------------------------------------------------------------------------


class TestCompleteSession:
    @pytest.mark.asyncio
    async def test_complete_session_writes_result(
        self, client: AsyncClient, db_session: AsyncSession
    ):

        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)  # no procedure → manual scoring
        session = await _seed_session(db_session, scenario, trainee, status="in_progress")

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(f"/api/v1/scenarios/sessions/{session.id}/complete")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["session_id"] == str(session.id)
        assert "result" in data

        # Confirm in DB
        await db_session.refresh(session)
        assert session.status == "completed"
        assert session.result is not None

    @pytest.mark.asyncio
    async def test_complete_already_completed_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="completed")
        session.result = {"score_pct": 100.0}
        await db_session.flush()

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(f"/api/v1/scenarios/sessions/{session.id}/complete")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Instructor assignment (PATCH /sessions/{id}) tests
# ---------------------------------------------------------------------------


class TestPatchSession:
    @pytest.mark.asyncio
    async def test_instructor_self_assign_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        instructor = await _seed_user(db_session, roles=["instructor"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee)

        # Instructor self-assigning
        user = CurrentUser(id=str(instructor.id), roles=["instructor"])
        _override_user(app, user)

        resp = await client.patch(
            f"/api/v1/scenarios/sessions/{session.id}",
            json={"instructor_id": str(instructor.id)},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["instructor_id"] == str(instructor.id)

    @pytest.mark.asyncio
    async def test_trainee_assign_instructor_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        instructor = await _seed_user(db_session, roles=["instructor"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee)

        # Trainee trying to assign → forbidden
        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.patch(
            f"/api/v1/scenarios/sessions/{session.id}",
            json={"instructor_id": str(instructor.id)},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Debrief tests
# ---------------------------------------------------------------------------


class TestDebriefEndpoint:
    @pytest.mark.asyncio
    async def test_debrief_completed_session_200(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="completed")
        session.result = {
            "score_pct": 80.0,
            "correct": 4,
            "missed": 1,
            "out_of_order": 0,
            "total_steps": 5,
            "duration_seconds": 180,
        }
        await db_session.flush()

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        # Mock the AI service to avoid real API calls
        mock_ai_result = {
            "response": "Good performance. Focus on missed actions.",
            "provider": "gemini",
            "model": "gemini-pro",
            "cached": False,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.001},
            "citations": [],
            "request_id": "req_test_123",
        }

        with patch(
            "app.modules.scenarios.service.AIService.complete",
            new=AsyncMock(return_value=mock_ai_result),
        ):
            resp = await client.post(f"/api/v1/scenarios/sessions/{session.id}/debrief")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "debrief" in data
        assert data["score_pct"] == 80.0
        assert data["audience"] == "trainee"

    @pytest.mark.asyncio
    async def test_debrief_in_progress_session_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="in_progress")

        user = CurrentUser(id=str(trainee.id), roles=["trainee"])
        _override_user(app, user)

        resp = await client.post(f"/api/v1/scenarios/sessions/{session.id}/debrief")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_debrief_instructor_gets_instructor_audience(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        from app.main import app

        trainee = await _seed_user(db_session, roles=["trainee"])
        instructor = await _seed_user(db_session, roles=["instructor"])
        scenario = await _seed_scenario(db_session)
        session = await _seed_session(db_session, scenario, trainee, status="completed")
        session.result = {
            "score_pct": 75.0,
            "correct": 3,
            "missed": 1,
            "out_of_order": 0,
            "total_steps": 4,
            "duration_seconds": 200,
        }
        await db_session.flush()

        user = CurrentUser(id=str(instructor.id), roles=["instructor"])
        _override_user(app, user)

        mock_ai_result = {
            "response": "Trainee performed adequately.",
            "provider": "gemini",
            "model": "gemini-pro",
            "cached": False,
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.001},
            "citations": [],
            "request_id": "req_test_456",
        }

        with patch(
            "app.modules.scenarios.service.AIService.complete",
            new=AsyncMock(return_value=mock_ai_result),
        ):
            resp = await client.post(f"/api/v1/scenarios/sessions/{session.id}/debrief")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["audience"] == "instructor"
