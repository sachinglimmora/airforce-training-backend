import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.digital_twin.models import AircraftSystem, Component

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_404 = {404: {"description": "Not found"}}


@router.get(
    "",
    response_model=dict,
    summary="List aircraft systems",
    description=(
        "Returns all aircraft systems in the digital twin. "
        "Filter by `category` (engine | hydraulics | electrical | avionics | landing-gear | fuel-system | weapons-integration) "
        "and/or `status` (operational | maintenance | faulty)."
    ),
    responses={**_401},
    operation_id="digital_twin_systems_list",
)
async def list_systems(
    db: Annotated[AsyncSession, Depends(get_db)],
    category: str | None = Query(None, description="System category"),
    status: str | None = Query(None, description="operational | maintenance | faulty"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
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
                "health": s.health,
            }
            for s in systems
        ]
    }


@router.get(
    "/{system_id}",
    response_model=dict,
    summary="Get a system's detail",
    description="Returns full metadata for a single aircraft system including health percentage and status.",
    responses={**_401, **_404},
    operation_id="digital_twin_systems_get",
)
async def get_system(
    system_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
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
            "health": system.health,
        }
    }


@router.get(
    "/{system_id}/components",
    response_model=dict,
    summary="Get components of a system",
    description=(
        "Returns all components belonging to a system with part numbers, "
        "health scores, status, and maintenance schedule."
    ),
    responses={**_401, **_404},
    operation_id="digital_twin_components_list",
)
async def get_components(
    system_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
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
                "specifications": c.specifications,
            }
            for c in components
        ]
    }


@router.patch(
    "/{system_id}/components/{component_id}",
    response_model=dict,
    summary="Update a component's status or health",
    description=(
        "Partial update of a component. Updatable fields: `status`, `health`.\n\n"
        "Returns both the updated component and its parent system."
    ),
    responses={**_401, **_404},
    operation_id="digital_twin_components_update",
)
async def update_component(
    system_id: uuid.UUID,
    component_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    result = await db.execute(
        select(Component).where(Component.id == component_id, Component.system_id == system_id)
    )
    component = result.scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")

    if "status" in body:
        component.status = body["status"]
    if "health" in body:
        component.health = body["health"]
    await db.commit()
    await db.refresh(component)

    system_result = await db.execute(select(AircraftSystem).where(AircraftSystem.id == system_id))
    system = system_result.scalar_one()

    return {
        "data": {
            "system": {
                "id": str(system.id),
                "name": system.name,
                "category": system.category,
                "status": system.status,
                "health": system.health,
            },
            "component": {
                "id": str(component.id),
                "name": component.name,
                "partNumber": component.part_number,
                "description": component.description,
                "status": component.status,
                "health": component.health,
            },
        }
    }
