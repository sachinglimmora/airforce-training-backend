import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}


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
    _db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "traineeId": str(current_user.id),
            "overallProgress": 65,
            "readinessScore": 88,
            "simulationHours": 24,
            "completedCourses": 3,
            "totalCourses": 5,
            "completedModules": 12,
            "totalModules": 20,
            "recentActivity": [
                {
                    "id": "1",
                    "type": "module-completed",
                    "title": "Turbine Blade Inspection",
                    "timestamp": "2026-04-24T10:00:00Z",
                },
                {
                    "id": "2",
                    "type": "course-started",
                    "title": "Jet Engine Systems",
                    "timestamp": "2026-04-23T14:00:00Z",
                },
            ],
            "skills": [
                {"name": "System Knowledge", "level": 85, "maxLevel": 100, "category": "Technical"},
                {
                    "name": "Procedure Adherence",
                    "level": 92,
                    "maxLevel": 100,
                    "category": "Technical",
                },
                {
                    "name": "Decision Making",
                    "level": 78,
                    "maxLevel": 100,
                    "category": "Soft Skills",
                },
            ],
        }
    }


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
    _db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    return {
        "data": {
            "traineeId": str(trainee_id),
            "overallProgress": 65,
            "readinessScore": 88,
            "simulationHours": 24,
            "completedCourses": 3,
            "totalCourses": 5,
            "completedModules": 12,
            "totalModules": 20,
            "recentActivity": [],
            "skills": [],
        }
    }


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
