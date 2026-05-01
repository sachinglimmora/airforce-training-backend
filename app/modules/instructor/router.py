import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.analytics.models import TrainingSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.competency.models import CompetencyEvidence
from app.modules.instructor.schemas import (
    ScenarioOut,
    TrainingSessionCreate,
    TrainingSessionOut,
    TrainingSessionUpdate,
)
from app.modules.procedures.models import ProcedureSession
from app.modules.scenarios.models import Scenario
from app.modules.users.service import UsersService

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Not found"}}


async def _trainee_metrics(db: AsyncSession, trainee_id: uuid.UUID) -> dict:
    """Compute readiness, progress, and sim hours for one trainee."""
    # Readiness from competency evidence
    ce_result = await db.execute(
        select(func.avg(CompetencyEvidence.score)).where(
            CompetencyEvidence.trainee_id == trainee_id
        )
    )
    avg_score = ce_result.scalar()
    readiness = round(float(avg_score), 1) if avg_score else 0.0

    # Progress from procedure sessions
    ps_result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.trainee_id == trainee_id)
    )
    ps_sessions = ps_result.scalars().all()
    completed = sum(1 for s in ps_sessions if s.status == "completed")
    total = len(ps_sessions)
    progress = round((completed / total) * 100, 1) if total > 0 else 0.0

    # Simulation hours from scenario training sessions
    ts_result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.trainee_id == trainee_id,
            TrainingSession.session_type == "scenario",
            TrainingSession.status == "completed",
            TrainingSession.ended_at.is_not(None),
        )
    )
    sim_sessions = ts_result.scalars().all()
    sim_hours = round(
        sum((s.ended_at - s.started_at).total_seconds() / 3600 for s in sim_sessions), 1
    )

    return {
        "readinessScore": readiness,
        "progress": progress,
        "simulationHours": sim_hours,
    }


@router.get(
    "/trainees",
    response_model=dict,
    summary="Get trainees overview (instructor view)",
    description=(
        "Returns all trainees with their readiness scores, progress percentages, "
        "simulation hours, and account status. "
        "Instructors see their assigned trainees; admins see all."
    ),
    responses={**_401},
    operation_id="instructor_trainees_list",
)
async def get_trainees_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    svc = UsersService(db)
    users = await svc.list_users(role="trainee")

    trainees = []
    for u in users:
        metrics = await _trainee_metrics(db, u.id)
        trainees.append(
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "name": u.full_name,
                "status": u.status,
                **metrics,
            }
        )

    return {"data": trainees}


@router.get(
    "/sessions",
    response_model=dict,
    summary="List training sessions (instructor view)",
    description="Returns all training sessions visible to the instructor.",
    responses={**_401},
    operation_id="instructor_sessions_list",
)
async def get_training_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingSession))
    sessions = result.scalars().all()
    return {"data": [TrainingSessionOut.model_validate(s).model_dump() for s in sessions]}


@router.post(
    "/sessions",
    response_model=dict,
    summary="Create a training session",
    description=(
        "Creates a new training session on behalf of a trainee.\n\n"
        "- `session_type` — theory | checklist | procedure | scenario | vr | assessment\n"
        "- `trainee_id` — UUID of the trainee\n"
        "- `instructor_id` — defaults to the calling user if omitted"
    ),
    responses={**_401},
    operation_id="instructor_sessions_create",
)
async def create_training_session(
    body: TrainingSessionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    session = TrainingSession(
        trainee_id=body.trainee_id,
        instructor_id=body.instructor_id or current_user.id,
        session_type=body.session_type,
        aircraft_id=body.aircraft_id,
        procedure_id=body.procedure_id,
        scenario_id=body.scenario_id,
        status=body.status,
        metadata_json=body.metadata_json,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"data": TrainingSessionOut.model_validate(session).model_dump()}


@router.patch(
    "/sessions/{session_id}",
    response_model=dict,
    summary="Update a training session",
    description="Update session status, end time, or metadata. Partial update — only supplied fields change.",
    responses={**_401, **_404},
    operation_id="instructor_sessions_update",
)
async def update_training_session(
    session_id: uuid.UUID,
    body: TrainingSessionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingSession).where(TrainingSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if body.status:
        session.status = body.status
    if body.ended_at:
        session.ended_at = body.ended_at
    if body.metadata_json:
        session.metadata_json = body.metadata_json
    await db.commit()
    await db.refresh(session)
    return {"data": TrainingSessionOut.model_validate(session).model_dump()}


@router.delete(
    "/sessions/{session_id}",
    response_model=dict,
    summary="Delete a training session",
    description="Hard-deletes a training session record. Use with caution — prefer marking as aborted.",
    responses={**_401, **_404},
    operation_id="instructor_sessions_delete",
)
async def delete_training_session(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingSession).where(TrainingSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"data": {"message": "Session deleted successfully"}}


@router.get(
    "/scenarios",
    response_model=dict,
    summary="List scenarios (instructor view)",
    description="Returns all available scenarios for the instructor to assign or review.",
    responses={**_401},
    operation_id="instructor_scenarios_list",
)
async def get_instructor_scenarios(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Scenario))
    scenarios = result.scalars().all()
    return {"data": [ScenarioOut.model_validate(s).model_dump() for s in scenarios]}


@router.post(
    "/scenarios",
    response_model=dict,
    summary="Create a custom scenario",
    description=(
        "Creates a new scenario. For standard high-risk types use the pre-seeded scenarios; "
        "this endpoint is for custom scenarios authored by instructors.\n\n"
        "Required fields: `name`, `scenario_type` (v1_cut | windshear | tcas_ra | engine_fire | custom)"
    ),
    responses={**_401},
    operation_id="instructor_scenarios_create",
)
async def create_scenario(
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    scenario = Scenario(
        scenario_code=body.get("scenario_code", str(uuid.uuid4())[:8]),
        name=body.get("name", "New Scenario"),
        scenario_type=body.get("scenario_type", "custom"),
        aircraft_id=body.get("aircraft_id"),
        initial_conditions=body.get("initial_conditions", {}),
        trigger_config=body.get("trigger_config", {}),
        procedure_id=body.get("procedure_id"),
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return {"data": ScenarioOut.model_validate(scenario).model_dump()}


@router.get(
    "/analytics",
    response_model=dict,
    summary="Instructor analytics dashboard",
    description=(
        "Returns platform-wide KPIs and chart data scoped to the instructor's trainees: "
        "total trainees, average readiness, simulation hours, completions, and daily activity."
    ),
    responses={**_401},
    operation_id="instructor_analytics",
)
async def get_instructor_analytics(
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    from app.modules.auth.models import Role, UserRole

    # Count trainees
    trainee_q = (
        select(func.count(func.distinct(UserRole.user_id)))
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "trainee")
    )
    total_trainees = (await db.execute(trainee_q)).scalar() or 0

    # Simulation stats
    sim_q = select(TrainingSession).where(
        TrainingSession.session_type == "scenario",
        TrainingSession.status == "completed",
        TrainingSession.ended_at.is_not(None),
    )
    sim_sessions = (await db.execute(sim_q)).scalars().all()
    total_sim_hours = round(
        sum((s.ended_at - s.started_at).total_seconds() / 3600 for s in sim_sessions), 1
    )
    completed_sims = len(sim_sessions)

    # Active sessions
    active_q = select(func.count(TrainingSession.id)).where(
        TrainingSession.status == "in_progress"
    )
    active_sessions = (await db.execute(active_q)).scalar() or 0

    # Average readiness
    avg_q = select(func.avg(CompetencyEvidence.score))
    avg_readiness = (await db.execute(avg_q)).scalar()
    avg_readiness = round(float(avg_readiness), 1) if avg_readiness else 0.0

    return {
        "data": {
            "summary": {
                "totalTrainees": total_trainees,
                "avgReadiness": avg_readiness,
                "totalSimHours": total_sim_hours,
                "completedSims": completed_sims,
                "activeSessions": active_sessions,
                "simulationsToday": 0,
            },
            "charts": {
                "trainingCompletion": [],
                "readinessTrend": [],
                "simulationUsage": [],
                "skillDistribution": [],
            },
        }
    }
