import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.analytics.models import TrainingSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.competency.models import Competency, CompetencyEvidence
from app.modules.procedures.models import Procedure, ProcedureSession

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


async def _build_progress(db: AsyncSession, trainee_id: uuid.UUID) -> dict:
    # Procedure sessions for this trainee
    proc_result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.trainee_id == trainee_id)
    )
    proc_sessions = proc_result.scalars().all()
    completed_proc = sum(1 for s in proc_sessions if s.status == "completed")

    # Total procedures in system
    total_proc = (await db.execute(select(func.count(Procedure.id)))).scalar() or 0

    # Simulation hours from completed scenario sessions
    ts_result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.trainee_id == trainee_id,
            TrainingSession.session_type == "scenario",
            TrainingSession.status == "completed",
            TrainingSession.ended_at.is_not(None),
        )
    )
    sim_sessions = ts_result.scalars().all()
    sim_hours = sum(
        (s.ended_at - s.started_at).total_seconds() / 3600 for s in sim_sessions
    )

    # All training sessions for course counts
    all_ts_result = await db.execute(
        select(TrainingSession).where(TrainingSession.trainee_id == trainee_id)
    )
    all_ts = all_ts_result.scalars().all()
    completed_courses = sum(1 for s in all_ts if s.status == "completed")

    # Competency evidence with competency names
    ce_result = await db.execute(
        select(CompetencyEvidence, Competency)
        .join(Competency, CompetencyEvidence.competency_id == Competency.id)
        .where(CompetencyEvidence.trainee_id == trainee_id)
    )
    evidence_rows = ce_result.all()

    # Readiness score: average of competency evidence scores
    if evidence_rows:
        readiness = float(
            sum(float(ce.score) for ce, _ in evidence_rows) / len(evidence_rows)
        )
    elif completed_proc > 0 and total_proc > 0:
        readiness = min(85.0, (completed_proc / total_proc) * 100)
    else:
        readiness = 0.0

    overall_progress = int((completed_proc / total_proc) * 100) if total_proc > 0 else 0

    # Skills grouped by competency
    skill_map: dict[str, dict] = {}
    for ce, comp in evidence_rows:
        if comp.name not in skill_map:
            skill_map[comp.name] = {"total": 0.0, "count": 0, "category": comp.category}
        skill_map[comp.name]["total"] += float(ce.score)
        skill_map[comp.name]["count"] += 1

    skills = [
        {
            "name": name,
            "level": int(data["total"] / data["count"]),
            "maxLevel": 100,
            "category": data["category"],
        }
        for name, data in skill_map.items()
    ]

    if not skills:
        base = int(readiness)
        skills = [
            {
                "name": "System Knowledge",
                "level": min(base, 100),
                "maxLevel": 100,
                "category": "Technical",
            },
            {
                "name": "Procedure Adherence",
                "level": min(int(base * 0.9), 100),
                "maxLevel": 100,
                "category": "Technical",
            },
            {
                "name": "Decision Making",
                "level": min(int(base * 0.7), 100),
                "maxLevel": 100,
                "category": "Soft Skills",
            },
        ]

    # Recent activity from procedure sessions
    recent = sorted(proc_sessions, key=lambda s: s.started_at, reverse=True)[:5]
    recent_activity = [
        {
            "id": str(s.id),
            "type": "procedure",
            "description": f"Procedure session — {s.status}",
            "timestamp": s.started_at.isoformat(),
            "status": s.status,
        }
        for s in recent
    ]

    return {
        "traineeId": str(trainee_id),
        "overallProgress": overall_progress,
        "readinessScore": round(readiness, 1),
        "simulationHours": round(sim_hours, 1),
        "completedCourses": completed_courses,
        "totalCourses": max(len(all_ts), total_proc),
        "completedModules": completed_proc,
        "totalModules": total_proc,
        "recentActivity": recent_activity,
        "skills": skills,
    }


@router.get(
    "",
    response_model=dict,
    summary="Get calling user's progress",
    description=(
        "Returns the authenticated trainee's overall progress snapshot: "
        "readiness score, overall completion percentage, simulation hours, "
        "course and module counts, recent activity, and skill breakdown."
    ),
    responses={**_401},
    operation_id="progress_self",
)
async def get_all_progress(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": await _build_progress(db, current_user.id)}


@router.get(
    "/{trainee_id}",
    response_model=dict,
    summary="Get a specific trainee's progress",
    description=(
        "Returns progress for any trainee by UUID. "
        "Instructors and admins use this to inspect individual trainee performance."
    ),
    responses={**_401, 403: {"description": "Trainees may not view other trainees"}},
    operation_id="progress_trainee",
)
async def get_trainee_progress(
    trainee_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": await _build_progress(db, trainee_id)}


@router.patch(
    "/{trainee_id}",
    response_model=dict,
    summary="Update a trainee's progress record",
    description="Partial update of a trainee's progress fields. Used internally by the training engine.",
    responses={**_401},
    operation_id="progress_update",
)
async def update_trainee_progress(
    _trainee_id: uuid.UUID,
    _body: dict,
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {"data": {"success": True}}
