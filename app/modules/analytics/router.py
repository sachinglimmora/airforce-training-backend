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
