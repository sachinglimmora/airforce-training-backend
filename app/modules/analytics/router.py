from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.analytics.models import TrainingSession
from app.modules.auth.deps import get_current_user
from app.modules.auth.models import Role, UserRole
from app.modules.auth.schemas import CurrentUser
from app.modules.competency.models import Competency, CompetencyEvidence
from app.modules.procedures.models import Deviation, ProcedureSession

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


async def _count_trainees(db: AsyncSession) -> int:
    q = (
        select(func.count(func.distinct(UserRole.user_id)))
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "trainee")
    )
    return (await db.execute(q)).scalar() or 0


async def _sim_stats(db: AsyncSession) -> tuple[float, int]:
    q = select(TrainingSession).where(
        TrainingSession.session_type == "scenario",
        TrainingSession.status == "completed",
        TrainingSession.ended_at.is_not(None),
    )
    sessions = (await db.execute(q)).scalars().all()
    hours = sum((s.ended_at - s.started_at).total_seconds() / 3600 for s in sessions)
    return round(hours, 1), len(sessions)


async def _active_session_count(db: AsyncSession) -> int:
    q = select(func.count(TrainingSession.id)).where(TrainingSession.status == "in_progress")
    return (await db.execute(q)).scalar() or 0


async def _sims_today(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    day_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    q = select(func.count(TrainingSession.id)).where(
        TrainingSession.session_type == "scenario",
        TrainingSession.started_at >= day_start,
    )
    return (await db.execute(q)).scalar() or 0


async def _avg_readiness(db: AsyncSession) -> float:
    result = (await db.execute(select(func.avg(CompetencyEvidence.score)))).scalar()
    return round(float(result), 1) if result else 0.0


async def _weekly_chart(db: AsyncSession) -> list[dict]:
    now = datetime.now(UTC)
    today = now.date()
    chart = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        day_end = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)
        q = select(func.count(TrainingSession.id)).where(
            TrainingSession.status == "completed",
            TrainingSession.ended_at >= day_start,
            TrainingSession.ended_at <= day_end,
        )
        count = (await db.execute(q)).scalar() or 0
        chart.append({"label": day.strftime("%a"), "value": count})
    return chart


@router.get(
    "",
    response_model=dict,
    summary="Full analytics overview",
    description="Returns platform-wide KPIs and chart data for the instructor/admin dashboard.",
    responses={**_401},
    operation_id="analytics_overview",
)
@router.get(
    "/overall",
    response_model=dict,
    summary="Full analytics overview (alias)",
    description="Alias for `GET /analytics`.",
    responses={**_401},
    operation_id="analytics_overview_alias",
    include_in_schema=False,
)
async def get_full_analytics(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    total_trainees = await _count_trainees(db)
    total_sim_hours, completed_sims = await _sim_stats(db)
    active_sessions = await _active_session_count(db)
    sims_today = await _sims_today(db)
    avg_readiness = await _avg_readiness(db)
    weekly_chart = await _weekly_chart(db)

    return {
        "data": {
            "summary": {
                "totalTrainees": total_trainees,
                "avgReadiness": avg_readiness,
                "totalSimHours": total_sim_hours,
                "completedSims": completed_sims,
                "activeSessions": active_sessions,
                "simulationsToday": sims_today,
            },
            "charts": {
                "trainingCompletion": weekly_chart,
                "readinessTrend": [],
                "simulationUsage": [],
                "skillDistribution": [],
            },
        }
    }


@router.get(
    "/trainee",
    response_model=dict,
    summary="Trainee analytics (self view)",
    description=(
        "Returns the calling trainee's readiness score, overall progress, "
        "simulation hours, skill breakdown, and recent activity feed."
    ),
    responses={**_401},
    operation_id="analytics_trainee_self",
)
async def get_trainee_analytics(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    trainee_id = current_user.id

    # Procedure sessions
    proc_result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.trainee_id == trainee_id)
    )
    proc_sessions = proc_result.scalars().all()
    completed_proc = sum(1 for s in proc_sessions if s.status == "completed")

    # Simulation hours
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

    # Competency evidence
    ce_result = await db.execute(
        select(CompetencyEvidence, Competency)
        .join(Competency, CompetencyEvidence.competency_id == Competency.id)
        .where(CompetencyEvidence.trainee_id == trainee_id)
    )
    evidence_rows = ce_result.all()

    readiness = 0.0
    if evidence_rows:
        readiness = float(
            sum(float(ce.score) for ce, _ in evidence_rows) / len(evidence_rows)
        )
    elif completed_proc > 0:
        readiness = min(85.0, completed_proc * 10)

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
            {"name": "System Knowledge", "level": min(base, 100), "maxLevel": 100, "category": "Technical"},
            {"name": "Procedure Adherence", "level": min(int(base * 0.9), 100), "maxLevel": 100, "category": "Technical"},
            {"name": "Decision Making", "level": min(int(base * 0.7), 100), "maxLevel": 100, "category": "Soft Skills"},
        ]

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
        "data": {
            "readinessScore": round(readiness, 1),
            "overallProgress": min(100, completed_proc * 10),
            "simulationHours": round(sim_hours, 1),
            "skills": skills,
            "recentActivity": recent_activity,
        }
    }


@router.get(
    "/sessions/{session_id}/deviations",
    response_model=dict,
    summary="Step-level and timing deviations for a session",
    description=(
        "Returns every deviation recorded in the session with type, severity, "
        "expected vs actual values, and a summary of compliance percentage.\n\n"
        "Deviation types: `skip` | `out_of_order` | `timing` | `wrong_action` | `incomplete`\n\n"
        "Severity: `minor` | `moderate` | `major` | `critical`"
    ),
    responses={**_401},
    operation_id="analytics_session_deviations",
)
async def session_deviations(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Deviation).where(Deviation.session_id == session_id))
    devs = result.scalars().all()

    total = len(devs)
    critical = sum(1 for d in devs if d.severity == "critical")
    timing_violations = sum(1 for d in devs if d.deviation_type == "timing")

    return {
        "data": {
            "session_id": session_id,
            "deviations": [
                {
                    "id": str(d.id),
                    "step_id": str(d.step_id),
                    "deviation_type": d.deviation_type,
                    "severity": d.severity,
                    "expected": d.expected,
                    "actual": d.actual,
                    "detected_at": d.detected_at.isoformat(),
                }
                for d in devs
            ],
            "summary": {
                "total_deviations": total,
                "critical_misses": critical,
                "timing_violations": timing_violations,
            },
        }
    }


@router.get(
    "/trainees/{trainee_id}/progression",
    response_model=dict,
    summary="Competency progression over time",
    description=(
        "Returns a time-series of competency evidence scores for the trainee, "
        "allowing instructors to track improvement across sessions."
    ),
    responses={**_401},
    operation_id="analytics_trainee_progression",
)
async def trainee_progression(
    trainee_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(CompetencyEvidence, Competency)
        .join(Competency, CompetencyEvidence.competency_id == Competency.id)
        .where(CompetencyEvidence.trainee_id == trainee_id)
        .order_by(CompetencyEvidence.recorded_at)
    )
    rows = result.all()
    progression = [
        {
            "competency": comp.name,
            "score": float(ce.score),
            "recorded_at": ce.recorded_at.isoformat(),
        }
        for ce, comp in rows
    ]
    return {"data": {"trainee_id": trainee_id, "progression": progression}}


@router.get(
    "/trainees/{trainee_id}/summary",
    response_model=dict,
    summary="Aggregated trainee performance summary",
    description=(
        "Returns total sessions, completed sessions, and high-level performance metrics "
        "for the specified trainee."
    ),
    responses={**_401},
    operation_id="analytics_trainee_summary",
)
async def trainee_summary(
    trainee_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(ProcedureSession).where(ProcedureSession.trainee_id == trainee_id)
    )
    sessions = result.scalars().all()
    completed = [s for s in sessions if s.status == "completed"]

    ce_result = await db.execute(
        select(func.avg(CompetencyEvidence.score)).where(
            CompetencyEvidence.trainee_id == trainee_id
        )
    )
    avg_score = ce_result.scalar()

    return {
        "data": {
            "trainee_id": trainee_id,
            "total_sessions": len(sessions),
            "completed_sessions": len(completed),
            "avg_competency_score": round(float(avg_score), 1) if avg_score else 0.0,
        }
    }


@router.get(
    "/cohorts/{cohort_id}/summary",
    response_model=dict,
    summary="Cohort statistics (instructor view)",
    description=(
        "Returns aggregated performance statistics for a cohort of trainees — "
        "useful for instructor dashboards showing group readiness."
    ),
    responses={**_401},
    operation_id="analytics_cohort_summary",
)
async def cohort_summary(
    cohort_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    _db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"cohort_id": cohort_id, "summary": {}}}


@router.get(
    "/compliance/report",
    response_model=dict,
    summary="Procedural compliance report",
    description=(
        "Organisation-wide compliance report — aggregates deviation data across all sessions "
        "to produce overall compliance percentages per procedure and per trainee cohort."
    ),
    responses={**_401},
    operation_id="analytics_compliance_report",
)
async def compliance_report(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.service import AnalyticsService

    svc = AnalyticsService(db)
    report = await svc.get_compliance_report()
    return {"data": report}
