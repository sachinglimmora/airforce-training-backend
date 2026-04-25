from typing import Annotated, List, Optional
import uuid
from fastapi import Depends, Query, HTTPException
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.digital_twin.models import AircraftSystem, Component

router = APIRouter()

@router.get("", response_model=dict)
async def list_systems(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    q = select(AircraftSystem)
    if category:
        q = q.where(AircraftSystem.category == category)
    if status:
        q = q.where(AircraftSystem.status == status)
    
    result = await db.execute(q)
    systems = result.scalars().all()
    
    return {
        "data": [
            {
                "id": str(s.id),
                "name": s.name,
                "category": s.category,
                "status": s.status,
                "health": s.health
            }
            for s in systems
        ]
    }

@router.get("/{system_id}", response_model=dict)
async def get_system(
    system_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(AircraftSystem).where(AircraftSystem.id == system_id))
    system = result.scalar_one_or_none()
    if not system:
        raise HTTPException(status_code=404, detail="System not found")
    
    return {
        "data": {
            "id": str(system.id),
            "name": system.name,
            "category": system.category,
            "status": system.status,
            "health": system.health
        }
    }

@router.get("/{system_id}/components", response_model=dict)
async def get_components(
    system_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(Component).where(Component.system_id == system_id))
    components = result.scalars().all()
    
    return {
        "data": [
            {
                "id": str(c.id),
                "name": c.name,
                "partNumber": c.part_number,
                "description": c.description,
                "status": c.status,
                "health": c.health,
                "lastMaintenance": c.last_maintenance.isoformat() if c.last_maintenance else None,
                "nextMaintenance": c.next_maintenance.isoformat() if c.next_maintenance else None,
                "specifications": c.specifications
            }
            for c in components
        ]
    }

@router.patch("/{system_id}/components/{component_id}", response_model=dict)
async def update_component(
    system_id: uuid.UUID,
    component_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(select(Component).where(Component.id == component_id, Component.system_id == system_id))
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    
    if "status" in body:
        component.status = body["status"]
    if "health" in body:
        component.health = body["health"]
        
    await db.commit()
    await db.refresh(component)
    
    # Also fetch the system to return as requested by frontend
    system_result = await db.execute(select(AircraftSystem).where(AircraftSystem.id == system_id))
    system = system_result.scalar_one()
    
    return {
        "data": {
            "system": {
                "id": str(system.id),
                "name": system.name,
                "category": system.category,
                "status": system.status,
                "health": system.health
            },
            "component": {
                "id": str(component.id),
                "name": component.name,
                "partNumber": component.part_number,
                "description": component.description,
                "status": component.status,
                "health": component.health
            }
        }
    }
