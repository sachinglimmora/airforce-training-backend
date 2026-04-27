from typing import Annotated

from fastapi import Depends, Query
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser

router = APIRouter()


# Simulations Compatibility
@router.get("/simulations", response_model=dict)
async def list_simulations(
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    # Mock data for now
    return {
        "data": [
            {
                "id": "sim-1",
                "title": "Maintenance Readiness",
                "type": "maintenance",
                "description": "Routine check of engine turbine blades.",
                "duration": "1 hour",
                "difficulty": "intermediate",
                "aircraft": "B737-800",
                "objectives": ["Identify cracks", "Measure tolerances"],
                "briefing": "Complete the checklist before engine start.",
                "status": "available",
            }
        ]
    }


@router.get("/simulations/{id}", response_model=dict)
async def get_simulation(id: str):
    return {
        "data": {
            "id": id,
            "title": "Maintenance Readiness",
            "type": "maintenance",
            "description": "Routine check of engine turbine blades.",
            "duration": "1 hour",
            "difficulty": "intermediate",
            "aircraft": "B737-800",
            "objectives": ["Identify cracks", "Measure tolerances"],
            "briefing": "Complete the checklist before engine start.",
            "status": "available",
        }
    }


@router.post("/simulations/{id}/start", response_model=dict)
async def start_simulation(id: str):
    return {"data": {"success": True, "message": "Simulation started"}}


@router.post("/simulations/{id}/complete", response_model=dict)
async def complete_simulation(id: str):
    return {"data": {"success": True, "message": "Simulation completed"}}


# Digital Twin Compatibility
@router.get("/digital-twin", response_model=dict)
async def list_digital_twin(category: str | None = Query(None), status: str | None = Query(None)):
    return {
        "data": [
            {
                "id": "sys-1",
                "name": "Engine 1",
                "category": "engine",
                "components": [],
                "status": "operational",
                "health": 95,
            }
        ]
    }


@router.get("/digital-twin/{id}", response_model=dict)
async def get_digital_twin(id: str):
    return {
        "data": {
            "id": id,
            "name": "Engine 1",
            "category": "engine",
            "components": [
                {
                    "id": "comp-1",
                    "name": "HPT Blade",
                    "partNumber": "P123-45",
                    "description": "High Pressure Turbine Blade",
                    "status": "operational",
                    "health": 98,
                    "lastMaintenance": "2024-01-01",
                    "nextMaintenance": "2024-12-01",
                    "specifications": {},
                }
            ],
            "status": "operational",
            "health": 95,
        }
    }


# AI Assistant Compatibility
@router.get("/ai-assistant/history", response_model=dict)
async def get_ai_history():
    return {"data": []}


@router.post("/ai-assistant/message", response_model=dict)
async def send_ai_message(body: dict):
    return {
        "data": {
            "userMessage": {
                "id": "m1",
                "role": "user",
                "content": body.get("content", ""),
                "timestamp": "2024-04-25T12:00:00Z",
            },
            "assistantMessage": {
                "id": "m2",
                "role": "assistant",
                "content": "I am the Aegis AI Assistant. How can I help you with your training today?",
                "timestamp": "2024-04-25T12:00:01Z",
            },
        }
    }


# Alerts Compatibility
@router.get("/alerts", response_model=dict)
async def list_alerts():
    return {"data": []}
