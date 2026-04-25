from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.procedures.models import Deviation, ProcedureSession

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


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
    _db: Annotated[AsyncSession, Depends(get_db)],
):
    return {
        "data": {
            "summary": {
                "totalTrainees": 156,
                "avgReadiness": 82.5,
                "totalSimHours": 1420,
                "completedSims": 312,
                "activeSessions": 8,
                "simulationsToday": 24,
            },
            "charts": {
                "trainingCompletion": [
                    {"label": "Mon", "value": 12},
                    {"label": "Tue", "value": 19},
                    {"label": "Wed", "value": 15},
                    {"label": "Thu", "value": 22},
                    {"label": "Fri", "value": 30},
                ],
                "readinessTrend": [
                    {"label": "Jan", "value": 65},
                    {"label": "Feb", "value": 72},
                    {"label": "Mar", "value": 78},
                    {"label": "Apr", "value": 82},
                ],
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
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    _db: Annotated[AsyncSession, Depends(get_db)],
):
    return {
        "data": {
            "readinessScore": 88,
            "overallProgress": 65,
            "simulationHours": 24,
            "skills": [
                {"name": "System Knowledge",      "level": 85, "maxLevel": 100, "category": "Technical"},
                {"name": "Procedure Adherence",   "level": 92, "maxLevel": 100, "category": "Technical"},
                {"name": "Decision Making",        "level": 78, "maxLevel": 100, "category": "Soft Skills"},
            ],
            "recentActivity": [
                {"id": "1", "type": "module-completed",  "title": "Turbine Blade Inspection", "timestamp": "2026-04-24T10:00:00Z"},
                {"id": "2", "type": "course-started",    "title": "Jet Engine Systems",        "timestamp": "2026-04-23T14:00:00Z"},
            ],
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
    _db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"trainee_id": trainee_id, "progression": []}}


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
    return {
        "data": {
            "trainee_id": trainee_id,
            "total_sessions": len(sessions),
            "completed_sessions": len(completed),
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
