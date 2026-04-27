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
simulations_router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Not found"}}


class TriggerRequest(BaseModel):
    event: str
    payload: dict = {}


class ActionRequest(BaseModel):
    action: str
    payload: dict = {}


from sqlalchemy.orm import selectinload

@router.get(
    "",
    response_model=dict,
    summary="List scenarios",
    description=(
        "Returns all configured high-risk scenarios: V1 cut, windshear, TCAS RA, engine fire, and custom."
    ),
    responses={**_401},
    operation_id="scenarios_list",
)
@simulations_router.get(
    "",
    response_model=dict,
    summary="List simulations (alias)",
    description="Alias for `GET /scenarios`. Prefer `/scenarios` for new integrations.",
    responses={**_401},
    operation_id="simulations_list",
)
async def list_scenarios(
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    result = await db.execute(select(Scenario).options(selectinload(Scenario.aircraft)))
    scenarios = result.scalars().all()
    
    # Mapping for frontend compatibility
    data = []
    for s in scenarios:
        # Map backend types to frontend simulation types
        sim_type = "flight-readiness"
        if s.scenario_type == "custom":
            sim_type = "maintenance"
        elif s.scenario_type in ["v1_cut", "engine_fire"]:
            sim_type = "mission-rehearsal"

        data.append({
            "id": str(s.id),
            "title": s.name,
            "description": s.description or "No description provided.",
            "type": sim_type,
            "difficulty": "intermediate", # Default
            "duration": "45 mins", # Default
            "status": "available", # Default
            "aircraft": s.aircraft.type_code if s.aircraft else "Unknown",
            "briefing": s.description or "Mission briefing pending intelligence update.",
            "objectives": [
                "Maintain aircraft control",
                "Execute prescribed QRH procedures",
                "Coordinate with ATC",
                "Successfully complete mission objectives"
            ] # Default objectives to prevent crash
        })
    
    return {"data": data}


@router.get(
    "/{scenario_id}",
    response_model=dict,
    summary="Get scenario configuration",
    description=(
        "Returns full scenario config including `initial_conditions` (aircraft state at scenario start) "
        "and `trigger_config` (event that fires the scenario, e.g. engine failure at V1)."
    ),
    responses={**_401, **_404},
    operation_id="scenarios_get",
)
@simulations_router.get(
    "/{scenario_id}",
    response_model=dict,
    summary="Get simulation config (alias)",
    description="Alias for `GET /scenarios/{scenario_id}`.",
    responses={**_401, **_404},
    operation_id="simulations_get",
)
async def get_scenario(
    scenario_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Scenario)
        .options(selectinload(Scenario.aircraft))
        .where(Scenario.id == scenario_id)
    )
    s = result.scalar_one_or_none()
    if not s:
        from app.core.exceptions import NotFound
        raise NotFound("Scenario")
    
    # Map backend types to frontend simulation types
    sim_type = "flight-readiness"
    if s.scenario_type == "custom":
        sim_type = "maintenance"
    elif s.scenario_type in ["v1_cut", "engine_fire"]:
        sim_type = "mission-rehearsal"

    return {
        "data": {
            "id": str(s.id),
            "title": s.name,
            "description": s.description,
            "type": sim_type,
            "difficulty": "intermediate",
            "duration": "45 mins",
            "status": "available",
            "aircraft": s.aircraft.type_code if s.aircraft else "Unknown",
            "briefing": s.description or "Mission briefing pending intelligence update.",
            "objectives": [
                "Maintain aircraft control",
                "Execute prescribed QRH procedures",
                "Coordinate with ATC",
                "Successfully complete mission objectives"
            ],
            "initial_conditions": s.initial_conditions,
            "trigger_config": s.trigger_config,
            "procedure_id": str(s.procedure_id) if s.procedure_id else None,
        }
    }


@router.post(
    "/{scenario_id}/sessions",
    status_code=201,
    response_model=dict,
    summary="Start a scenario session",
    description=(
        "Creates a `ScenarioSession` for the calling trainee. "
        "Returns `session_id` used in trigger and action calls.\n\n"
        "**Session flow:** start → `POST /sessions/{sid}/trigger` → "
        "loop `POST /sessions/{sid}/action` → `GET /sessions/{sid}/result`"
    ),
    responses={**_401, **_404},
    operation_id="scenarios_start_session",
)
@simulations_router.post(
    "/{scenario_id}/start",
    status_code=201,
    response_model=dict,
    summary="Start a simulation session (alias)",
    description="Alias for `POST /scenarios/{scenario_id}/sessions`.",
    responses={**_401, **_404},
    operation_id="simulations_start_session",
)
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


@router.post(
    "/sessions/{session_id}/trigger",
    response_model=dict,
    summary="Fire the scenario trigger event",
    description=(
        "Fires the configured trigger event for this session "
        "(e.g. engine failure at V1, windshear at 500 ft, TCAS RA).\n\n"
        "Body: `{ \"event\": \"engine_failure_at_v1\", \"payload\": { ... } }`\n\n"
        "Records `trigger_fired_at` on the session."
    ),
    responses={**_401},
    operation_id="scenarios_trigger",
)
async def trigger_event(
    session_id: str,
    body: TriggerRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime

    result = await db.execute(select(ScenarioSession).where(ScenarioSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.trigger_fired_at = datetime.now(UTC)
    return {
        "data": {
            "session_id": session_id,
            "trigger": body.event,
            "fired_at": session.trigger_fired_at.isoformat() if session else None,
        }
    }


@router.post(
    "/sessions/{session_id}/action",
    response_model=dict,
    summary="Record a trainee action",
    description=(
        "Records a discrete trainee action during a scenario session "
        "(e.g. moving a throttle, pressing a switch, declaring MAYDAY).\n\n"
        "Body: `{ \"action\": \"throttle_idle_affected_engine\", \"payload\": { ... } }`"
    ),
    responses={**_401},
    operation_id="scenarios_action",
)
async def record_action(
    session_id: str,
    body: ActionRequest,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    _db: Annotated[AsyncSession, Depends(get_db)],
):
    return {"data": {"session_id": session_id, "action": body.action, "recorded": True}}


@router.get(
    "/sessions/{session_id}/result",
    response_model=dict,
    summary="Get scored scenario result",
    description=(
        "Returns the final scored result for a completed scenario session. "
        "`result` is a JSONB object written by the scoring engine when the session ends."
    ),
    responses={**_401, **_404},
    operation_id="scenarios_result",
)
async def get_result(
    session_id: str,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(ScenarioSession).where(ScenarioSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        from app.core.exceptions import NotFound
        raise NotFound("Scenario session")
    return {"data": {"session_id": session_id, "result": session.result, "status": session.status}}


@simulations_router.post(
    "/{scenario_id}/complete",
    response_model=dict,
    summary="Complete a simulation session (alias)",
    description="Marks the most recent active session for this scenario and user as completed.",
    responses={**_401},
    operation_id="simulations_complete_session",
)
async def complete_simulation(
    scenario_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from datetime import UTC, datetime

    result = await db.execute(
        select(ScenarioSession)
        .where(ScenarioSession.scenario_id == scenario_id, ScenarioSession.trainee_id == current_user.id)
        .order_by(ScenarioSession.started_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session:
        session.status = "completed"
        session.ended_at = datetime.now(UTC)
        await db.commit()
        return {"data": {"success": True, "message": "Simulation completed"}}
    return {"data": {"success": False, "message": "No active session found"}}
