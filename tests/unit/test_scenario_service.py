"""Unit tests for ScenarioService helpers — no DB required."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.scenarios.service import _score, _slugify

# ---------------------------------------------------------------------------
# _slugify tests
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercase_conversion(self):
        assert _slugify("ThrottleIdle") == "throttleidle"

    def test_punctuation_to_underscore(self):
        assert _slugify("throttle-idle!affected") == "throttle_idle_affected"

    def test_mixed_case_and_spaces(self):
        assert _slugify("Set Flaps 15") == "set_flaps_15"

    def test_extra_spaces_normalized(self):
        assert _slugify("  declare   MAYDAY  ") == "declare_mayday"

    def test_multiple_special_chars(self):
        assert _slugify("Push!@#Throttle") == "push_throttle"

    def test_already_slugified(self):
        assert _slugify("throttle_idle") == "throttle_idle"

    def test_numbers_preserved(self):
        assert _slugify("Flaps 15 Degrees") == "flaps_15_degrees"


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


def _make_session(duration_seconds: int = 120) -> SimpleNamespace:
    """Create a mock session with started_at / ended_at."""
    started = datetime.now(UTC)
    ended = started + timedelta(seconds=duration_seconds)
    session = SimpleNamespace(started_at=started, ended_at=ended)
    return session


def _make_action(action: str) -> SimpleNamespace:
    return SimpleNamespace(action=action)


def _make_step(ordinal: int, action_text: str) -> SimpleNamespace:
    return SimpleNamespace(ordinal=ordinal, action_text=action_text)


class TestScoring:
    def test_all_correct_100_pct(self):
        session = _make_session()
        actions = [_make_action("Throttle Idle"), _make_action("Declare MAYDAY")]
        steps = [_make_step(0, "Throttle Idle"), _make_step(1, "Declare MAYDAY")]
        result = _score(session, actions, steps)
        assert result["score_pct"] == 100.0
        assert result["correct"] == 2
        assert result["missed"] == 0
        assert result["out_of_order"] == 0

    def test_all_missed_0_pct(self):
        session = _make_session()
        actions = []
        steps = [_make_step(0, "Throttle Idle"), _make_step(1, "Declare MAYDAY")]
        result = _score(session, actions, steps)
        assert result["score_pct"] == 0.0
        assert result["correct"] == 0
        assert result["missed"] == 2

    def test_partial_score(self):
        session = _make_session()
        # Only 1 of 2 steps done
        actions = [_make_action("Throttle Idle")]
        steps = [_make_step(0, "Throttle Idle"), _make_step(1, "Declare MAYDAY")]
        result = _score(session, actions, steps)
        assert result["score_pct"] == 50.0
        assert result["correct"] == 1
        assert result["missed"] == 1

    def test_out_of_order_counted(self):
        """Action done but at a position far from expected — out_of_order not correct."""
        session = _make_session()
        # step 0 = "throttle_idle", step 1 = "declare_mayday", step 2 = "call_atc"
        # actions: declare_mayday (pos 0), call_atc (pos 1), throttle_idle (pos 2)
        # throttle_idle expected at 0, found at 2 → |2-0|>1 → out_of_order
        actions = [
            _make_action("declare_mayday"),
            _make_action("call_atc"),
            _make_action("throttle_idle"),
        ]
        steps = [
            _make_step(0, "throttle_idle"),
            _make_step(1, "declare_mayday"),
            _make_step(2, "call_atc"),
        ]
        result = _score(session, actions, steps)
        # declare_mayday: expected 1, found 0, |0-1|=1 → correct
        # call_atc: expected 2, found 1, |1-2|=1 → correct
        # throttle_idle: expected 0, found 2, |2-0|=2 → out_of_order
        assert result["out_of_order"] == 1
        assert result["correct"] == 2

    def test_no_steps_score_zero(self):
        session = _make_session()
        result = _score(session, [], [])
        assert result["score_pct"] == 0.0
        assert result["total_steps"] == 0

    def test_duration_seconds_calculated(self):
        session = _make_session(duration_seconds=300)
        result = _score(session, [], [])
        assert result["duration_seconds"] == 300

    def test_total_steps_in_result(self):
        session = _make_session()
        steps = [_make_step(i, f"step_{i}") for i in range(5)]
        result = _score(session, [], steps)
        assert result["total_steps"] == 5


# ---------------------------------------------------------------------------
# Trigger validation tests (service layer with mocked DB)
# ---------------------------------------------------------------------------


class TestTriggerValidation:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        return db

    def _build_session(self, trigger_fired_at=None):
        session = MagicMock()
        session.trigger_fired_at = trigger_fired_at
        session.scenario_id = "scenario-uuid"
        return session

    def _build_scenario(self, trigger_event=None):
        scenario = MagicMock()
        if trigger_event is not None:
            scenario.trigger_config = {"event": trigger_event}
        else:
            scenario.trigger_config = None
        return scenario

    async def _mock_db_execute(self, mock_db, session_obj, scenario_obj):
        """Helper that sets up two sequential execute() calls."""
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = session_obj
        scenario_result = MagicMock()
        scenario_result.scalar_one_or_none.return_value = scenario_obj
        mock_db.execute = AsyncMock(side_effect=[session_result, scenario_result])
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

    @pytest.mark.asyncio
    async def test_matching_event_passes(self, mock_db):
        from app.modules.scenarios.service import ScenarioService

        session = self._build_session()
        scenario = self._build_scenario(trigger_event="engine_failure_at_v1")
        await self._mock_db_execute(mock_db, session, scenario)

        svc = ScenarioService(mock_db)
        # Should not raise
        await svc.fire_trigger("sid", "engine_failure_at_v1")

    @pytest.mark.asyncio
    async def test_mismatched_event_raises_400(self, mock_db):
        from fastapi import HTTPException

        from app.modules.scenarios.service import ScenarioService

        session = self._build_session()
        scenario = self._build_scenario(trigger_event="engine_failure_at_v1")
        await self._mock_db_execute(mock_db, session, scenario)

        svc = ScenarioService(mock_db)
        with pytest.raises(HTTPException) as exc_info:
            await svc.fire_trigger("sid", "windshear")
        assert exc_info.value.status_code == 400
        assert "mismatch" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_already_fired_raises_400(self, mock_db):
        from fastapi import HTTPException

        from app.modules.scenarios.service import ScenarioService

        session = self._build_session(trigger_fired_at=datetime.now(UTC))
        scenario = self._build_scenario(trigger_event="engine_failure_at_v1")
        await self._mock_db_execute(mock_db, session, scenario)

        svc = ScenarioService(mock_db)
        with pytest.raises(HTTPException) as exc_info:
            await svc.fire_trigger("sid", "engine_failure_at_v1")
        assert exc_info.value.status_code == 400
        assert "already fired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_no_trigger_config_always_passes(self, mock_db):
        from app.modules.scenarios.service import ScenarioService

        session = self._build_session()
        scenario = self._build_scenario(trigger_event=None)
        await self._mock_db_execute(mock_db, session, scenario)

        svc = ScenarioService(mock_db)
        # No trigger_config → any event is fine
        await svc.fire_trigger("sid", "any_random_event")


# ---------------------------------------------------------------------------
# Scoring with no procedure (score_pct = None)
# ---------------------------------------------------------------------------


class TestScoringNoProcedure:
    @pytest.mark.asyncio
    async def test_no_procedure_score_none(self):
        """complete_session with procedure_id=None returns score_pct=None."""
        from app.modules.scenarios.service import ScenarioService

        # Build mocks
        session = MagicMock()
        session.status = "in_progress"
        session.scenario_id = "sc-id"
        session.id = "sess-id"
        session.started_at = datetime.now(UTC)

        scenario = MagicMock()
        scenario.id = "sc-id"
        scenario.procedure_id = None

        db = AsyncMock()
        session_result = MagicMock()
        session_result.scalar_one_or_none.return_value = session

        scenario_result = MagicMock()
        scenario_result.scalar_one_or_none.return_value = scenario

        actions_result = MagicMock()
        actions_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[session_result, scenario_result, actions_result])
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        svc = ScenarioService(db)
        result = await svc.complete_session("sess-id")
        assert result["score_pct"] is None
        assert "manual scoring" in result["note"]
