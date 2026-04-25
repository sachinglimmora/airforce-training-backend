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

_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Not found"}}


class CompleteStepRequest(BaseModel):
    elapsed_ms: int | None = None
    notes: str | None = None


class BranchRequest(BaseModel):
    condition: str


@router.get(
    "",
    response_model=dict,
    summary="List procedures",
    description=(
        "Returns all procedures. Filter by `aircraft_id`, `procedure_type` "
        "(normal | abnormal | emergency), or `phase` "
        "(pre-flight | taxi | takeoff | cruise | approach | landing | shutdown)."
    ),
    responses={**_401},
    operation_id="procedures_list",
)
async def list_procedures(
    aircraft_id: str | None = Query(None, description="Filter by aircraft UUID"),
    procedure_type: str | None = Query(None, description="normal | abnormal | emergency"),
    phase: str | None = Query(None, description="pre-flight | taxi | takeoff | cruise | approach | landing | shutdown"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
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


@router.get(
    "/{procedure_id}",
    response_model=dict,
    summary="Get full procedure with all steps",
    description=(
        "Returns the procedure definition including every step's action text, "
        "expected response, execution mode, target time, and criticality flag."
    ),
    responses={**_401, **_404},
    operation_id="procedures_get",
)
async def get_procedure(
    procedure_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get(
    "/{procedure_id}/flow",
    response_model=dict,
    summary="Get procedure flow DAG (QRH rendering engine)",
    description=(
        "Returns the procedure as a directed acyclic graph for frontend rendering. "
        "Each step includes a `branches` array — non-empty for emergency decision points.\n\n"
        "Branch structure: `{ \"condition\": \"fire persists\", \"next_step_id\": \"uuid\" }`\n\n"
        "Use `root_step_id` as the starting node and follow `branches` or `ordinal` to traverse."
    ),
    responses={**_401, **_404},
    operation_id="procedures_flow",
)
async def get_procedure_flow(
    procedure_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.post(
    "/{procedure_id}/sessions",
    status_code=201,
    response_model=dict,
    summary="Start a procedure execution session",
    description=(
        "Creates a `ProcedureSession` linked to a unified `TrainingSession`. "
        "Returns `session_id` used in all subsequent step calls."
    ),
    responses={**_401, **_404},
    operation_id="procedures_start_session",
)
async def start_session(
    procedure_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.models import TrainingSession

    ts = TrainingSession(
        trainee_id=current_user.id,
        session_type="procedure",
        procedure_id=procedure_id,
        status="in_progress",
    )
    db.add(ts)
    await db.flush()

    session = ProcedureSession(id=ts.id, procedure_id=procedure_id, trainee_id=current_user.id)
    db.add(session)
    await db.flush()
    await db.commit()

    return {"data": {"session_id": str(ts.id), "status": "in_progress", "started_at": ts.started_at.isoformat()}}


@router.post(
    "/sessions/{session_id}/steps/{step_id}/complete",
    response_model=dict,
    summary="Mark a procedure step as completed",
    description=(
        "Records a step completion event. "
        "The deviation engine checks `elapsed_ms` against `target_time_seconds` "
        "and logs a timing deviation if the threshold is exceeded.\n\n"
        "Body fields (all optional):\n"
        "- `elapsed_ms` — milliseconds since session start (used for timing analysis)\n"
        "- `notes` — free-text instructor annotation"
    ),
    responses={**_401},
    operation_id="procedures_complete_step",
)
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
        notes=body.notes,
    )
    return {"data": result}


@router.post(
    "/sessions/{session_id}/complete",
    response_model=dict,
    summary="End a procedure session",
    description=(
        "Marks the session as `completed` and records `ended_at`. "
        "Call after all required steps have been completed."
    ),
    responses={**_401},
    operation_id="procedures_complete_session",
)
async def complete_session(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime

    result = await db.execute(select(ProcedureSession).where(ProcedureSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.ended_at = datetime.now(UTC)
    return {"data": {"session_id": session_id, "status": "completed"}}


@router.get(
    "/sessions/{session_id}/deviations",
    response_model=dict,
    summary="Get deviations detected in a session",
    description=(
        "Returns all deviations recorded for the session — skip, out-of-order, timing, "
        "wrong-action, and incomplete step events — with severity ratings."
    ),
    responses={**_401},
    operation_id="procedures_deviations",
)
async def get_deviations(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
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
