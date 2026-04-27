import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.modules.analytics.models import SessionEvent
from app.modules.procedures.models import Deviation, ProcedureSession, ProcedureStep

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
            from app.core.exceptions import Forbidden

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
            session_id=session.id,  # Note: if using separate ProcedureSession, this might need mapping
            event_type="step_completed",
            step_id=step.id,
            elapsed_ms=elapsed_ms,
            payload={"notes": notes},
        )
        self.db.add(event)

        await self.db.commit()
        return {"status": "completed", "step_id": step_id}
