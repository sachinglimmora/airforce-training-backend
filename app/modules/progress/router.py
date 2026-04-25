from typing import Annotated, List, Optional, Union
import uuid
from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()

@router.get("", response_model=dict)
async def get_all_progress(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # If user is admin/instructor, maybe return list of all trainees progress.
    # For now, return a mock response matching the frontend expectation.
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
                {"id": "1", "type": "module-completed", "title": "Turbine Blade Inspection", "timestamp": "2024-04-24T10:00:00Z"},
                {"id": "2", "type": "course-started", "title": "Jet Engine Systems", "timestamp": "2024-04-23T14:00:00Z"}
            ],
            "skills": [
                {"name": "System Knowledge", "level": 85, "maxLevel": 100, "category": "Technical"},
                {"name": "Procedure Adherence", "level": 92, "maxLevel": 100, "category": "Technical"},
                {"name": "Decision Making", "level": 78, "maxLevel": 100, "category": "Soft Skills"}
            ]
        }
    }

@router.get("/{trainee_id}", response_model=dict)
async def get_trainee_progress(
    trainee_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # Mock data for a specific trainee
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
            "skills": []
        }
    }

@router.patch("/{trainee_id}", response_model=dict)
async def update_trainee_progress(
    trainee_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # Implement update logic if needed
    return {"data": {"success": True}}
