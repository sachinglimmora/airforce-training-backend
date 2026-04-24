from typing import Annotated

from fastapi import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.scenarios.models import Scenario, ScenarioSession

router = APIRouter()


class TriggerRequest(BaseModel):
    event: str
    payload: dict = {}


class ActionRequest(BaseModel):
    action: str
    payload: dict = {}


@router.get("", summary="List scenarios")
async def list_scenarios(
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Scenario))
    scenarios = result.scalars().all()
    return {
        "data": [
            {
                "id": str(s.id),
                "scenario_code": s.scenario_code,
                "name": s.name,
                "scenario_type": s.scenario_type,
            }
            for s in scenarios
        ]
    }


@router.get("/{scenario_id}", summary="Get scenario config")
async def get_scenario(
    scenario_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    s = result.scalar_one_or_none()
    if not s:
        from app.core.exceptions import NotFound
        raise NotFound("Scenario")
    return {
        "data": {
            "id": str(s.id),
            "scenario_code": s.scenario_code,
            "name": s.name,
            "scenario_type": s.scenario_type,
            "initial_conditions": s.initial_conditions,
            "trigger_config": s.trigger_config,
            "procedure_id": str(s.procedure_id) if s.procedure_id else None,
        }
    }


@router.post("/{scenario_id}/sessions", status_code=201, summary="Start scenario session")
async def start_session(
    scenario_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    session = ScenarioSession(scenario_id=scenario_id, trainee_id=current_user.id)
    db.add(session)
    await db.flush()
    return {
        "data": {
            "session_id": str(session.id),
            "scenario_id": scenario_id,
            "status": "in_progress",
            "started_at": session.started_at.isoformat(),
        }
    }


@router.post("/sessions/{session_id}/trigger", summary="Fire the trigger event")
async def trigger_event(
    session_id: str,
    body: TriggerRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime
    result = await db.execute(select(ScenarioSession).where(ScenarioSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.trigger_fired_at = datetime.now(UTC)
    return {"data": {"session_id": session_id, "trigger": body.event, "fired_at": session.trigger_fired_at.isoformat() if session else None}}


@router.post("/sessions/{session_id}/action", summary="Trainee action")
async def record_action(
    session_id: str,
    body: ActionRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"session_id": session_id, "action": body.action, "recorded": True}}


@router.get("/sessions/{session_id}/result", summary="Get scored result")
async def get_result(
    session_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(ScenarioSession).where(ScenarioSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound
        raise NotFound("Scenario session")
    return {"data": {"session_id": session_id, "result": session.result, "status": session.status}}
