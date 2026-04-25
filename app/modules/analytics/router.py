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


@router.get("", summary="Compatibility: Get full analytics")
@router.get("/overall", summary="Compatibility: Get full analytics")
async def get_full_analytics(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {
        "data": {
            "summary": {
                "totalTrainees": 156,
                "avgReadiness": 82.5,
                "totalSimHours": 1420,
                "completedSims": 312,
                "activeSessions": 8,
                "simulationsToday": 24
            },
            "charts": {
                "trainingCompletion": [
                    {"label": "Mon", "value": 12},
                    {"label": "Tue", "value": 19},
                    {"label": "Wed", "value": 15},
                    {"label": "Thu", "value": 22},
                    {"label": "Fri", "value": 30}
                ],
                "readinessTrend": [
                    {"label": "Jan", "value": 65},
                    {"label": "Feb", "value": 72},
                    {"label": "Mar", "value": 78},
                    {"label": "Apr", "value": 82}
                ],
                "simulationUsage": [],
                "skillDistribution": []
            }
        }
    }


@router.get("/trainee", summary="Compatibility: Get trainee analytics")
async def get_trainee_analytics(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {
        "data": {
            "readinessScore": 88,
            "overallProgress": 65,
            "simulationHours": 24,
            "skills": [
                {"name": "System Knowledge", "level": 85, "maxLevel": 100, "category": "Technical"},
                {"name": "Procedure Adherence", "level": 92, "maxLevel": 100, "category": "Technical"},
                {"name": "Decision Making", "level": 78, "maxLevel": 100, "category": "Soft Skills"}
            ],
            "recentActivity": [
                {"id": "1", "type": "module-completed", "title": "Turbine Blade Inspection", "timestamp": "2024-04-24T10:00:00Z"},
                {"id": "2", "type": "course-started", "title": "Jet Engine Systems", "timestamp": "2024-04-23T14:00:00Z"}
            ]
        }
    }


@router.get("/sessions/{session_id}/deviations", summary="Step-level and timing deviations")
async def session_deviations(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get("/trainees/{trainee_id}/progression", summary="Competency progression over time")
async def trainee_progression(
    trainee_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"trainee_id": trainee_id, "progression": []}}


@router.get("/trainees/{trainee_id}/summary", summary="Aggregated performance summary")
async def trainee_summary(
    trainee_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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


@router.get("/cohorts/{cohort_id}/summary", summary="Cohort statistics")
async def cohort_summary(
    cohort_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"cohort_id": cohort_id, "summary": {}}}


@router.get("/compliance/report", summary="Procedural compliance report")
async def compliance_report(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.modules.analytics.service import AnalyticsService
    svc = AnalyticsService(db)
    report = await svc.get_compliance_report()
    return {"data": report}
