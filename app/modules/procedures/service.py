import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound
from app.modules.analytics.models import SessionEvent
from app.modules.procedures.models import Deviation, Procedure, ProcedureSession, ProcedureStep

log = structlog.get_logger()


class ProcedureService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def complete_step(
        self,
        session_id: str,
        step_id: str,
        trainee_id: str,
        elapsed_ms: int | None = None,
        notes: str | None = None,
    ) -> dict:
        # 1. Validate session and step
        result = await self.db.execute(
            select(ProcedureSession).where(ProcedureSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Procedure session")

        if str(session.trainee_id) != trainee_id:
            raise Forbidden("Not your session")

        result = await self.db.execute(select(ProcedureStep).where(ProcedureStep.id == step_id))
        step = result.scalar_one_or_none()
        if not step:
            raise NotFound("Procedure step")

        # 2. Check for out-of-order deviation
        # Find the last completed step in this session
        events_result = await self.db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
            .where(SessionEvent.event_type == "step_completed")
            .order_by(SessionEvent.timestamp.desc())
            .limit(1)
        )
        last_event = events_result.scalar_one_or_none()

        expected_ordinal = 1
        if last_event:
            # This is a bit simplified; needs to handle branching logic later
            last_step_result = await self.db.execute(
                select(ProcedureStep).where(ProcedureStep.id == last_event.step_id)
            )
            last_step = last_step_result.scalar_one_or_none()
            if last_step:
                expected_ordinal = last_step.ordinal + 1

        if step.ordinal != expected_ordinal:
            # Record out-of-order deviation
            deviation = Deviation(
                session_id=session.id,
                step_id=step.id,
                deviation_type="out_of_order",
                severity="moderate" if not step.is_critical else "major",
                expected={"ordinal": expected_ordinal},
                actual={"ordinal": step.ordinal},
                notes=f"Expected step ordinal {expected_ordinal}, got {step.ordinal}",
            )
            self.db.add(deviation)
            log.warning("procedure_deviation_detected", session_id=session_id, type="out_of_order")

        # 3. Check for timing deviation
        if (
            step.target_time_seconds
            and elapsed_ms
            and (elapsed_ms / 1000) > step.target_time_seconds
        ):
            deviation = Deviation(
                session_id=session.id,
                step_id=step.id,
                deviation_type="timing",
                severity="minor",
                expected={"target_seconds": step.target_time_seconds},
                actual={"elapsed_seconds": elapsed_ms / 1000},
                notes=f"Step took {elapsed_ms / 1000}s, target was {step.target_time_seconds}s",
            )
            self.db.add(deviation)

        # 4. Record the completion event
        event = SessionEvent(
            session_id=session.id,
            event_type="step_completed",
            step_id=step.id,
            elapsed_ms=elapsed_ms,
            payload={"notes": notes},
        )
        self.db.add(event)

        await self.db.commit()
        return {"status": "completed", "step_id": step_id}

    async def take_branch(
        self,
        session_id: str,
        step_id: str,
        condition: str,
        current_user_id: str,
    ) -> dict:
        """Navigate a branch point — mark one child step as chosen, others as skipped."""
        # 1. Load step
        result = await self.db.execute(select(ProcedureStep).where(ProcedureStep.id == step_id))
        step = result.scalar_one_or_none()
        if not step:
            raise NotFound("Procedure step")

        # 2. Load session
        result = await self.db.execute(
            select(ProcedureSession).where(ProcedureSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Procedure session")
        if str(session.trainee_id) != current_user_id:
            raise Forbidden("Not your session")

        # 3. Query child steps
        children_result = await self.db.execute(
            select(ProcedureStep).where(ProcedureStep.parent_step_id == step.id)
        )
        children = children_result.scalars().all()

        # 4. Find chosen step by condition
        chosen_step = next((c for c in children if c.branch_condition == condition), None)
        if not chosen_step:
            raise HTTPException(
                status_code=400, detail=f"No branch matches condition '{condition}'"
            )

        skipped = [c for c in children if c.branch_condition != condition]

        # 5. Write branch_taken SessionEvent
        event = SessionEvent(
            session_id=session.id,
            event_type="branch_taken",
            payload={
                "condition": condition,
                "chosen_step_id": str(chosen_step.id),
                "skipped_step_ids": [str(s.id) for s in skipped],
            },
        )
        self.db.add(event)
        await self.db.commit()

        log.info(
            "procedure_branch_taken",
            session_id=session_id,
            condition=condition,
            chosen_step_id=str(chosen_step.id),
        )
        return {"chosen_step_id": str(chosen_step.id), "skipped_count": len(skipped)}

    async def detect_skips(self, session_id: str) -> None:
        """Detect skipped steps and write Deviation rows. Caller must commit."""
        # 1. Load session → procedure_id
        result = await self.db.execute(
            select(ProcedureSession).where(ProcedureSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Procedure session")

        # 2. Load all steps for procedure
        steps_result = await self.db.execute(
            select(ProcedureStep).where(ProcedureStep.procedure_id == session.procedure_id)
        )
        all_steps = steps_result.scalars().all()

        # 3. Load all step_completed events → set of completed step IDs
        completed_result = await self.db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
            .where(SessionEvent.event_type == "step_completed")
        )
        completed_events = completed_result.scalars().all()
        completed_step_ids = {
            str(e.step_id) for e in completed_events if e.step_id is not None
        }

        # 4. Load all branch_taken events → excluded step IDs (unchosen branches)
        branch_result = await self.db.execute(
            select(SessionEvent)
            .where(SessionEvent.session_id == session.id)
            .where(SessionEvent.event_type == "branch_taken")
        )
        branch_events = branch_result.scalars().all()
        excluded_step_ids: set[str] = set()
        for be in branch_events:
            if be.payload and "skipped_step_ids" in be.payload:
                excluded_step_ids.update(be.payload["skipped_step_ids"])

        # 5. Find skipped steps
        deviations = []
        for step in all_steps:
            step_id_str = str(step.id)
            if step_id_str in completed_step_ids:
                continue
            if step_id_str in excluded_step_ids:
                continue
            severity = "critical" if step.is_critical else "major"
            deviations.append(
                Deviation(
                    session_id=session.id,
                    step_id=step.id,
                    deviation_type="skip",
                    severity=severity,
                    expected={"ordinal": step.ordinal},
                    actual={"skipped": True},
                )
            )

        if deviations:
            self.db.add_all(deviations)
            log.warning(
                "procedure_skips_detected",
                session_id=session_id,
                skip_count=len(deviations),
            )

    async def generate_debrief(
        self,
        session_id: str,
        current_user_id: str,
        current_user_roles: list[str],
    ) -> dict:
        """Generate an AI debrief for a completed session."""
        # 1. Load session + procedure
        result = await self.db.execute(
            select(ProcedureSession).where(ProcedureSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise NotFound("Procedure session")

        proc_result = await self.db.execute(
            select(Procedure).where(Procedure.id == session.procedure_id)
        )
        procedure = proc_result.scalar_one_or_none()
        if not procedure:
            raise NotFound("Procedure")

        # 2. Check session is completed
        if session.status != "completed":
            raise HTTPException(status_code=400, detail="Session not yet completed")

        # 3. Auth: session owner OR instructor/admin
        is_owner = str(session.trainee_id) == current_user_id
        is_privileged = bool(set(current_user_roles) & {"instructor", "admin"})
        if not is_owner and not is_privileged:
            raise Forbidden("Access denied")

        # 4. Load deviations
        devs_result = await self.db.execute(
            select(Deviation).where(Deviation.session_id == session.id)
        )
        devs = devs_result.scalars().all()

        # 5. Audience label
        audience_label = "instructor" if is_privileged else "trainee"

        # 6. Duration
        duration_seconds = 0
        if session.ended_at and session.started_at:
            duration_seconds = int((session.ended_at - session.started_at).total_seconds())

        # 7. Deviation summary
        critical_count = sum(1 for d in devs if d.severity == "critical")
        skip_count = sum(1 for d in devs if d.deviation_type == "skip")
        deviation_summary = (
            f"{len(devs)} total ({critical_count} critical, {skip_count} skipped)"
        )

        # 8. Count total steps for this procedure
        steps_result = await self.db.execute(
            select(ProcedureStep).where(ProcedureStep.procedure_id == procedure.id)
        )
        total_steps = len(steps_result.scalars().all())

        # 9. Format prompt
        from app.modules.procedures.prompts import PROCEDURE_DEBRIEF_SYSTEM_PROMPT

        formatted_prompt = PROCEDURE_DEBRIEF_SYSTEM_PROMPT.format(
            audience_label=audience_label,
            procedure_name=procedure.name,
            procedure_type=procedure.procedure_type,
            phase=procedure.phase,
            duration_seconds=duration_seconds,
            total_steps=total_steps,
            deviation_summary=deviation_summary,
        )

        # 10. Call AIService
        from app.modules.ai.schemas import CompletionRequest, MessageIn
        from app.modules.ai.service import AIService

        ai_svc = AIService(self.db)
        ai_result = await ai_svc.complete(
            CompletionRequest(
                messages=[
                    MessageIn(role="system", content=formatted_prompt),
                    MessageIn(role="user", content="Generate the debrief now."),
                ],
                temperature=0.3,
                max_tokens=500,
                cache=False,
            ),
            user_id=current_user_id,
        )

        return {
            "session_id": str(session.id),
            "summary": deviation_summary,
            "deviation_count": len(devs),
            "critical_count": critical_count,
            "debrief": ai_result["response"],
            "audience": audience_label,
        }
