from typing import Annotated, List
import uuid
from fastapi import Depends, Query, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.auth.models import User
from app.modules.analytics.models import TrainingSession
from app.modules.scenarios.models import Scenario
from app.modules.instructor.schemas import (
    TraineeOverview, 
    TrainingSessionOut, 
    TrainingSessionCreate, 
    TrainingSessionUpdate,
    ScenarioOut,
    InstructorAnalytics
)
from app.modules.users.service import UsersService

router = APIRouter()

@router.get("/trainees", response_model=dict)
async def get_trainees_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # For now, list all trainees. In a real app, might be filtered by instructor's assigned trainees.
    svc = UsersService(db)
    users = await svc.list_users(role="trainee")
    
    # Mock some analytics data for each trainee for integration testing
    trainees = []
    for u in users:
        trainees.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "readinessScore": 85.0, # Mock
            "progress": 70.0,       # Mock
            "simulationHours": 12.5, # Mock
            "status": u.status
        })
    
    return {"data": trainees}

@router.get("/sessions", response_model=dict)
async def get_training_sessions(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingSession))
    sessions = result.scalars().all()
    return {"data": [TrainingSessionOut.model_validate(s).model_dump() for s in sessions]}

@router.post("/sessions", response_model=dict)
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
        metadata_json=body.metadata_json
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return {"data": TrainingSessionOut.model_validate(session).model_dump()}

@router.patch("/sessions/{session_id}", response_model=dict)
async def update_training_session(
    session_id: uuid.UUID,
    body: TrainingSessionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
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

@router.delete("/sessions/{session_id}", response_model=dict)
async def delete_training_session(
    session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(TrainingSession).where(TrainingSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    await db.delete(session)
    await db.commit()
    return {"data": {"message": "Session deleted successfully"}}

@router.get("/scenarios", response_model=dict)
async def get_instructor_scenarios(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    result = await db.execute(select(Scenario))
    scenarios = result.scalars().all()
    return {"data": [ScenarioOut.model_validate(s).model_dump() for s in scenarios]}

@router.post("/scenarios", response_model=dict)
async def create_scenario(
    body: dict, # Simplified for now
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # This might need a proper ScenarioCreate schema
    scenario = Scenario(
        scenario_code=body.get("scenario_code", str(uuid.uuid4())[:8]),
        name=body.get("name", "New Scenario"),
        scenario_type=body.get("scenario_type", "custom"),
        aircraft_id=body.get("aircraft_id"),
        initial_conditions=body.get("initial_conditions", {}),
        trigger_config=body.get("trigger_config", {}),
        procedure_id=body.get("procedure_id")
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return {"data": ScenarioOut.model_validate(scenario).model_dump()}

@router.get("/analytics", response_model=dict)
async def get_instructor_analytics(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
):
    # Bridge to the main analytics data structure
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
