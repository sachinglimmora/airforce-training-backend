import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound
from app.modules.scenarios.models import ScenarioAction, ScenarioSession


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class ScenarioService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # Trigger validation
    # ------------------------------------------------------------------

    async def fire_trigger(self, session_id: str, event: str) -> ScenarioSession:
        from app.modules.scenarios.models import Scenario

        result = await self.db.execute(
            select(ScenarioSession).where(ScenarioSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Scenario session")

        sc_result = await self.db.execute(
            select(Scenario).where(Scenario.id == session.scenario_id)
        )
        scenario = sc_result.scalar_one_or_none()
        if not scenario:
            raise NotFound("Scenario")

        if session.trigger_fired_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Trigger already fired for this session",
            )

        if scenario.trigger_config and scenario.trigger_config.get("event") != event:
            expected = scenario.trigger_config.get("event")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trigger event mismatch: expected '{expected}', got '{event}'",
            )

        session.trigger_fired_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    # ------------------------------------------------------------------
    # Action recording
    # ------------------------------------------------------------------

    async def record_action(
        self, session_id: str, action: str, payload: dict | None
    ) -> dict:
        result = await self.db.execute(
            select(ScenarioSession).where(ScenarioSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Scenario session")

        if session.status != "in_progress":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session not in progress",
            )

        sa = ScenarioAction(session_id=session.id, action=action, payload=payload)
        self.db.add(sa)
        await self.db.flush()
        await self.db.refresh(sa)

        return {
            "session_id": str(session_id),
            "action": action,
            "recorded": True,
            "recorded_at": sa.recorded_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Session completion + scoring
    # ------------------------------------------------------------------

    async def complete_session(self, session_id: str) -> dict:
        from app.modules.procedures.models import ProcedureStep
        from app.modules.scenarios.models import Scenario

        result = await self.db.execute(
            select(ScenarioSession).where(ScenarioSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Scenario session")

        if session.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session already completed",
            )

        sc_result = await self.db.execute(
            select(Scenario).where(Scenario.id == session.scenario_id)
        )
        scenario = sc_result.scalar_one_or_none()
        if not scenario:
            raise NotFound("Scenario")

        # Load all actions ordered by recorded_at
        actions_result = await self.db.execute(
            select(ScenarioAction)
            .where(ScenarioAction.session_id == session.id)
            .order_by(ScenarioAction.recorded_at)
        )
        actions = list(actions_result.scalars().all())

        session.ended_at = datetime.now(UTC)
        session.status = "completed"

        if scenario.procedure_id is None:
            result_payload: dict = {
                "score_pct": None,
                "note": "no procedure linked — manual scoring required",
            }
        else:
            # Load procedure steps ordered by ordinal
            steps_result = await self.db.execute(
                select(ProcedureStep)
                .where(ProcedureStep.procedure_id == scenario.procedure_id)
                .order_by(ProcedureStep.ordinal)
            )
            procedure_steps = list(steps_result.scalars().all())

            result_payload = _score(session, actions, procedure_steps)

        session.result = result_payload
        await self.db.flush()
        await self.db.refresh(session)
        return result_payload

    # ------------------------------------------------------------------
    # Instructor assignment
    # ------------------------------------------------------------------

    async def assign_instructor(
        self,
        session_id: str,
        instructor_id: str,
        current_user_id: str,
        current_user_roles: list[str],
    ) -> ScenarioSession:
        from app.modules.auth.models import User

        result = await self.db.execute(
            select(ScenarioSession).where(ScenarioSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Scenario session")

        # Authorization: self-assign (instructor) OR admin assigns anyone
        is_self_assign = str(current_user_id) == str(instructor_id) and "instructor" in current_user_roles
        is_admin = "admin" in current_user_roles
        if not (is_self_assign or is_admin):
            raise Forbidden()

        # Validate target user has instructor/admin role
        user_result = await self.db.execute(
            select(User).where(User.id == uuid.UUID(str(instructor_id)))
        )
        target_user = user_result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Instructor user not found",
            )
        target_roles = target_user.roles
        if not (set(target_roles) & {"instructor", "admin"}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target user does not have instructor or admin role",
            )

        session.instructor_id = uuid.UUID(str(instructor_id))
        await self.db.flush()
        await self.db.refresh(session)
        return session

    # ------------------------------------------------------------------
    # AI debrief
    # ------------------------------------------------------------------

    async def generate_debrief(
        self,
        session_id: str,
        current_user_id: str,
        current_user_roles: list[str],
    ) -> dict:
        from app.modules.ai.schemas import CompletionRequest, MessageIn
        from app.modules.ai.service import AIService
        from app.modules.scenarios.models import Scenario
        from app.modules.scenarios.prompts import SCENARIO_DEBRIEF_SYSTEM_PROMPT

        result = await self.db.execute(
            select(ScenarioSession).where(ScenarioSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Scenario session")

        sc_result = await self.db.execute(
            select(Scenario).where(Scenario.id == session.scenario_id)
        )
        scenario = sc_result.scalar_one_or_none()
        if not scenario:
            raise NotFound("Scenario")

        if session.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session is not completed yet",
            )

        # Auth: session owner OR instructor/admin
        is_owner = str(current_user_id) == str(session.trainee_id)
        is_privileged = bool(set(current_user_roles) & {"admin", "instructor"})
        if not (is_owner or is_privileged):
            raise Forbidden()

        audience_label = "instructor" if is_privileged else "trainee"
        result_data = session.result or {}

        formatted_prompt = SCENARIO_DEBRIEF_SYSTEM_PROMPT.format(
            audience_label=audience_label,
            scenario_name=scenario.name,
            scenario_type=scenario.scenario_type,
            score_pct=result_data.get("score_pct", "N/A"),
            correct=result_data.get("correct", 0),
            total_steps=result_data.get("total_steps", 0),
            missed=result_data.get("missed", 0),
            out_of_order_count=result_data.get("out_of_order", 0),
            duration_seconds=result_data.get("duration_seconds", 0),
        )

        ai_svc = AIService(self.db)
        ai_result = await ai_svc.complete(
            CompletionRequest(
                messages=[
                    MessageIn(role="system", content=formatted_prompt),
                    MessageIn(role="user", content="Generate the scenario debrief now."),
                ],
                temperature=0.3,
                max_tokens=500,
                cache=False,
            ),
            user_id=str(current_user_id),
        )

        return {
            "session_id": str(session.id),
            "score_pct": result_data.get("score_pct"),
            "debrief": ai_result["response"],
            "audience": audience_label,
        }


# ------------------------------------------------------------------
# Scoring helper (module-level so unit tests can call it directly)
# ------------------------------------------------------------------


def _score(session: ScenarioSession, actions: list, procedure_steps: list) -> dict:
    steps = sorted(procedure_steps, key=lambda s: s.ordinal)
    action_slugs = [_slugify(a.action) for a in actions]
    step_slugs = [_slugify(s.action_text) for s in steps]

    correct = 0
    out_of_order_count = 0
    for i, step_slug in enumerate(step_slugs):
        if step_slug in action_slugs:
            action_pos = action_slugs.index(step_slug)
            if abs(action_pos - i) <= 1:
                correct += 1
            else:
                out_of_order_count += 1

    missed = len(steps) - correct - out_of_order_count
    score_pct = round(correct / len(steps) * 100, 1) if steps else 0.0
    duration = int((session.ended_at - session.started_at).total_seconds())
    return {
        "score_pct": score_pct,
        "correct": correct,
        "missed": missed,
        "out_of_order": out_of_order_count,
        "total_steps": len(steps),
        "duration_seconds": duration,
    }
