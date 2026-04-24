from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.procedures.models import Deviation, Procedure, ProcedureSession, ProcedureStep

router = APIRouter()


class CompleteStepRequest(BaseModel):
    elapsed_ms: int | None = None
    notes: str | None = None


class BranchRequest(BaseModel):
    condition: str


@router.get("", summary="List procedures")
async def list_procedures(
    aircraft_id: str | None = Query(None),
    procedure_type: str | None = Query(None),
    phase: str | None = Query(None),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    q = select(Procedure)
    if aircraft_id:
        q = q.where(Procedure.aircraft_id == aircraft_id)
    if procedure_type:
        q = q.where(Procedure.procedure_type == procedure_type)
    if phase:
        q = q.where(Procedure.phase == phase)
    result = await db.execute(q)
    procs = result.scalars().all()
    return {
        "data": [
            {"id": str(p.id), "name": p.name, "procedure_type": p.procedure_type, "phase": p.phase}
            for p in procs
        ]
    }


@router.get("/{procedure_id}", summary="Get full procedure with steps")
async def get_procedure(
    procedure_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Procedure).where(Procedure.id == procedure_id))
    proc = result.scalar_one_or_none()
    if not proc:
        from app.core.exceptions import NotFound
        raise NotFound("Procedure")
    return {
        "data": {
            "id": str(proc.id),
            "name": proc.name,
            "procedure_type": proc.procedure_type,
            "phase": proc.phase,
            "citation_key": proc.citation_key,
            "steps": [
                {
                    "id": str(s.id),
                    "ordinal": s.ordinal,
                    "action_text": s.action_text,
                    "expected_response": s.expected_response,
                    "mode": s.mode,
                    "is_critical": s.is_critical,
                    "target_time_seconds": s.target_time_seconds,
                }
                for s in proc.steps
            ],
        }
    }


@router.get("/{procedure_id}/flow", summary="Procedure flow DAG (QRH rendering)")
async def get_procedure_flow(
    procedure_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Procedure).where(Procedure.id == procedure_id))
    proc = result.scalar_one_or_none()
    if not proc:
        from app.core.exceptions import NotFound
        raise NotFound("Procedure")

    all_steps = await db.execute(select(ProcedureStep).where(ProcedureStep.procedure_id == procedure_id))
    steps = {str(s.id): s for s in all_steps.scalars().all()}
    root_steps = [s for s in steps.values() if s.parent_step_id is None]

    flow = {}
    for step_id, step in steps.items():
        flow[step_id] = {
            "ordinal": step.ordinal,
            "action_text": step.action_text,
            "expected_response": step.expected_response,
            "mode": step.mode,
            "is_critical": step.is_critical,
            "branches": [
                {"condition": b.branch_condition, "next_step_id": str(b.id)}
                for b in step.branches
            ],
        }

    return {
        "data": {
            "procedure_id": procedure_id,
            "name": proc.name,
            "root_step_id": str(root_steps[0].id) if root_steps else None,
            "steps": flow,
            "citation_key": proc.citation_key,
        }
    }


@router.post("/{procedure_id}/sessions", status_code=201, summary="Start procedure execution")
async def start_session(
    procedure_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.models import TrainingSession
    
    # Create unified training session
    ts = TrainingSession(
        trainee_id=current_user.id,
        session_type="procedure",
        procedure_id=procedure_id,
        status="in_progress"
    )
    db.add(ts)
    await db.flush()

    session = ProcedureSession(id=ts.id, procedure_id=procedure_id, trainee_id=current_user.id)
    db.add(session)
    await db.flush()
    await db.commit()
    
    return {"data": {"session_id": str(ts.id), "status": "in_progress", "started_at": ts.started_at.isoformat()}}


@router.post("/sessions/{session_id}/steps/{step_id}/complete", summary="Mark step done")
async def complete_step(
    session_id: str,
    step_id: str,
    body: CompleteStepRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.procedures.service import ProcedureService
    svc = ProcedureService(db)
    result = await svc.complete_step(
        session_id=session_id,
        step_id=step_id,
        trainee_id=str(current_user.id),
        elapsed_ms=body.elapsed_ms,
        notes=body.notes
    )
    return {"data": result}


@router.post("/sessions/{session_id}/complete", summary="End procedure session")
async def complete_session(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime
    result = await db.execute(select(ProcedureSession).where(ProcedureSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.ended_at = datetime.now(UTC)
    return {"data": {"session_id": session_id, "status": "completed"}}


@router.get("/sessions/{session_id}/deviations", summary="Get deviations for a session")
async def get_deviations(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Deviation).where(Deviation.session_id == session_id))
    devs = result.scalars().all()
    return {
        "data": [
            {
                "id": str(d.id),
                "step_id": str(d.step_id),
                "deviation_type": d.deviation_type,
                "severity": d.severity,
                "detected_at": d.detected_at.isoformat(),
            }
            for d in devs
        ]
    }
