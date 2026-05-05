from typing import Annotated

from fastapi import Depends, HTTPException, Query
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
_403 = {403: {"description": "Forbidden"}}
_404 = {404: {"description": "Not found"}}


class CompleteStepRequest(BaseModel):
    elapsed_ms: int | None = None
    notes: str | None = None


class BranchRequest(BaseModel):
    condition: str


class ExplainRequest(BaseModel):
    context: str | None = None


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
    phase: str | None = Query(
        None, description="pre-flight | taxi | takeoff | cruise | approach | landing | shutdown"
    ),
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
        'Branch structure: `{ "condition": "fire persists", "next_step_id": "uuid" }`\n\n'
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

    all_steps = await db.execute(
        select(ProcedureStep).where(ProcedureStep.procedure_id == procedure_id)
    )
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
                {"condition": b.branch_condition, "next_step_id": str(b.id)} for b in step.branches
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

    return {
        "data": {
            "session_id": str(ts.id),
            "status": "in_progress",
            "started_at": ts.started_at.isoformat(),
        }
    }


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
    "/sessions/{session_id}/steps/{step_id}/branch",
    response_model=dict,
    summary="Navigate a branch point in a procedure",
    description=(
        "Records a branch navigation event. "
        "The chosen child step is returned; unchosen siblings are excluded from skip detection."
    ),
    responses={**_401, **_403, **_404},
    operation_id="procedures_take_branch",
)
async def take_branch(
    session_id: str,
    step_id: str,
    body: BranchRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.procedures.service import ProcedureService

    svc = ProcedureService(db)
    result = await svc.take_branch(
        session_id=session_id,
        step_id=step_id,
        condition=body.condition,
        current_user_id=str(current_user.id),
    )
    return {"data": result}


@router.post(
    "/sessions/{session_id}/steps/{step_id}/explain",
    response_model=dict,
    summary="Get an AI explanation of a procedure step",
    description=(
        "Returns an AI-generated explanation of a step in context. "
        "Requires the RAG ExplainService (PR #4) — returns 503 until that PR merges."
    ),
    responses={**_401, **_403, **_404},
    operation_id="procedures_explain_step",
)
async def explain_step(
    session_id: str,
    step_id: str,
    body: ExplainRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # 1. Load step + procedure
    step_result = await db.execute(select(ProcedureStep).where(ProcedureStep.id == step_id))
    step = step_result.scalar_one_or_none()
    if not step:
        from app.core.exceptions import NotFound

        raise NotFound("Procedure step")

    proc_result = await db.execute(select(Procedure).where(Procedure.id == step.procedure_id))
    procedure = proc_result.scalar_one_or_none()
    if not procedure:
        from app.core.exceptions import NotFound

        raise NotFound("Procedure")

    # 2. Auth: session owner OR instructor/admin
    session_result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound

        raise NotFound("Procedure session")

    is_owner = str(session.trainee_id) == str(current_user.id)
    is_privileged = bool(set(current_user.roles) & {"instructor", "admin"})
    if not is_owner and not is_privileged:
        from app.core.exceptions import Forbidden

        raise Forbidden("Access denied")

    # 3. Deferred import — ExplainService ships in PR #4
    try:
        from app.modules.rag.service import ExplainService
    except ImportError:
        raise HTTPException(status_code=503, detail="Explain service not yet available")

    svc = ExplainService(db)
    result = await svc.explain(
        topic=f"{step.action_text} (step {step.ordinal} of {procedure.name})",
        context=body.context or f"Phase: {procedure.phase}, type: {procedure.procedure_type}",
        system_state=None,
        aircraft_id=procedure.aircraft_id,
        user=current_user,
    )
    return {"data": result}


@router.post(
    "/sessions/{session_id}/complete",
    response_model=dict,
    summary="End a procedure session",
    description=(
        "Marks the session as `completed` and records `ended_at`. "
        "Runs skip detection before finalising — any unexecuted, non-excluded steps "
        "are recorded as Deviation rows."
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

    from app.modules.procedures.service import ProcedureService

    svc = ProcedureService(db)

    # Detect skips before marking complete
    await svc.detect_skips(session_id)

    result = await db.execute(select(ProcedureSession).where(ProcedureSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.ended_at = datetime.now(UTC)

    await db.commit()
    return {"data": {"session_id": session_id, "status": "completed"}}


@router.post(
    "/sessions/{session_id}/debrief",
    response_model=dict,
    summary="Generate an AI post-session debrief",
    description=(
        "Generates a concise AI debrief for a completed procedure session. "
        "Covers skips, out-of-order steps, and timing deviations with severity context. "
        "Tone is adjusted for instructor vs. trainee audience."
    ),
    responses={**_401, **_403, **_404},
    operation_id="procedures_debrief",
)
async def debrief_session(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.procedures.service import ProcedureService

    svc = ProcedureService(db)
    result = await svc.generate_debrief(
        session_id=session_id,
        current_user_id=str(current_user.id),
        current_user_roles=current_user.roles,
    )
    return {"data": result}


@router.get(
    "/sessions/{session_id}/deviations",
    response_model=dict,
    summary="Get deviations detected in a session",
    description=(
        "Returns all deviations recorded for the session — skip, out-of-order, timing, "
        "wrong-action, and incomplete step events — with severity ratings. "
        "Access: session owner, instructors, and admins."
    ),
    responses={**_401, **_403},
    operation_id="procedures_deviations",
)
async def get_deviations(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Load session for ownership check
    session_result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound

        raise NotFound("Procedure session")

    is_owner = str(session.trainee_id) == str(current_user.id)
    is_privileged = bool(set(current_user.roles) & {"instructor", "admin"})
    if not is_owner and not is_privileged:
        from app.core.exceptions import Forbidden

        raise Forbidden("Access denied")

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
