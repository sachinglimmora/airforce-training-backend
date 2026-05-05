import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from fastapi.routing import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.modules.auth.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.digital_twin.models import AircraftSystem, SystemDependency

router = APIRouter()

_401 = {401: {"description": "Not authenticated"}}
_403 = {403: {"description": "Forbidden"}}
_404 = {404: {"description": "Not found"}}

_ADMIN_INSTRUCTOR_ROLES = {"admin", "instructor"}


def _require_admin_or_instructor(current_user: CurrentUser) -> None:
    if not set(current_user.roles) & _ADMIN_INSTRUCTOR_ROLES:
        raise HTTPException(status_code=403, detail="Admin or instructor role required")


def _system_to_dict(system: AircraftSystem, dependency_type: str, description: str | None,
                    direction: str) -> dict:
    return {
        "id": str(system.id),
        "name": system.name,
        "category": system.category,
        "status": system.status,
        "health": system.health,
        "dependencyType": dependency_type,
        "description": description,
        "direction": direction,
    }


@router.get(
    "/{system_id}/dependencies",
    response_model=dict,
    summary="Get system dependencies",
    description=(
        "Returns upstream and/or downstream dependencies for an aircraft system. "
        "upstream = systems this system depends ON; "
        "downstream = systems that depend ON this system."
    ),
    responses={**_401, **_404},
    operation_id="digital_twin_dependencies_get",
)
async def get_dependencies(
    system_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    direction: str = Query("both", description="upstream | downstream | both"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Verify the system exists
    result = await db.execute(select(AircraftSystem).where(AircraftSystem.id == system_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="System not found")

    upstream = []
    downstream = []

    if direction in ("upstream", "both"):
        # upstream: dependencies where target_system_id == system_id
        # (i.e. "source" depends on us, meaning we depend on source)
        # Actually upstream means systems this system depends ON:
        # source_system_id == system_id → this system (source) → target systems
        # Wait: "upstream = systems this system depends ON (source→target where target=system_id)"
        # So upstream: rows where target_system_id == system_id, source is the upstream system
        q = (
            select(SystemDependency)
            .where(SystemDependency.target_system_id == system_id)
        )
        dep_result = await db.execute(q)
        deps = dep_result.scalars().all()
        for dep in deps:
            src_result = await db.execute(
                select(AircraftSystem).where(AircraftSystem.id == dep.source_system_id)
            )
            src = src_result.scalar_one_or_none()
            if src:
                upstream.append(
                    _system_to_dict(src, dep.dependency_type, dep.description, "upstream")
                )

    if direction in ("downstream", "both"):
        # downstream: systems that depend ON this system
        # source_system_id == system_id → this system IS the source, target depends on us
        q = (
            select(SystemDependency)
            .where(SystemDependency.source_system_id == system_id)
        )
        dep_result = await db.execute(q)
        deps = dep_result.scalars().all()
        for dep in deps:
            tgt_result = await db.execute(
                select(AircraftSystem).where(AircraftSystem.id == dep.target_system_id)
            )
            tgt = tgt_result.scalar_one_or_none()
            if tgt:
                downstream.append(
                    _system_to_dict(tgt, dep.dependency_type, dep.description, "downstream")
                )

    return {"data": {"upstream": upstream, "downstream": downstream}}


@router.post(
    "/{system_id}/dependencies",
    response_model=dict,
    summary="Create a system dependency",
    description="Creates a directed dependency from system_id → targetSystemId. Admin/Instructor only.",
    responses={**_401, **_403, **_404},
    operation_id="digital_twin_dependencies_create",
    status_code=201,
)
async def create_dependency(
    system_id: uuid.UUID,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    _require_admin_or_instructor(current_user)

    target_system_id_raw = body.get("targetSystemId")
    dependency_type = body.get("dependencyType")
    description = body.get("description")

    if not target_system_id_raw or not dependency_type:
        raise HTTPException(status_code=400, detail="targetSystemId and dependencyType are required")

    try:
        target_system_id = uuid.UUID(str(target_system_id_raw))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="targetSystemId must be a valid UUID")

    if target_system_id == system_id:
        raise HTTPException(status_code=400, detail="A system cannot depend on itself")

    # Verify source system exists
    src_result = await db.execute(select(AircraftSystem).where(AircraftSystem.id == system_id))
    if not src_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Source system not found")

    # Verify target system exists
    tgt_result = await db.execute(
        select(AircraftSystem).where(AircraftSystem.id == target_system_id)
    )
    if not tgt_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Target system not found")

    dep = SystemDependency(
        source_system_id=system_id,
        target_system_id=target_system_id,
        dependency_type=dependency_type,
        description=description,
    )
    db.add(dep)
    await db.commit()
    await db.refresh(dep)

    return {
        "data": {
            "id": str(dep.id),
            "sourceSystemId": str(dep.source_system_id),
            "targetSystemId": str(dep.target_system_id),
            "dependencyType": dep.dependency_type,
            "description": dep.description,
        }
    }


@router.delete(
    "/{system_id}/dependencies/{dependency_id}",
    response_model=dict,
    summary="Delete a system dependency",
    description="Removes a dependency edge. Admin/Instructor only.",
    responses={**_401, **_403, **_404},
    operation_id="digital_twin_dependencies_delete",
)
async def delete_dependency(
    system_id: uuid.UUID,
    dependency_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    _require_admin_or_instructor(current_user)

    result = await db.execute(
        select(SystemDependency).where(
            SystemDependency.id == dependency_id,
            SystemDependency.source_system_id == system_id,
        )
    )
    dep = result.scalar_one_or_none()
    if not dep:
        raise HTTPException(status_code=404, detail="Dependency not found")

    await db.delete(dep)
    await db.commit()
    return {"data": {"message": "Dependency removed"}}


@router.get(
    "/dependency-graph",
    response_model=dict,
    summary="Get full dependency graph",
    description=(
        "Returns all aircraft systems as nodes and their dependencies as edges. "
        "Optionally filter by aircraft_id."
    ),
    responses={**_401},
    operation_id="digital_twin_dependency_graph",
)
async def get_dependency_graph(
    db: Annotated[AsyncSession, Depends(get_db)],
    aircraft_id: uuid.UUID | None = Query(None, description="Filter by aircraft UUID"),
    _current_user: Annotated[CurrentUser, Depends(get_current_user)] = None,
):
    # Fetch all systems (filtered by aircraft if requested)
    systems_q = select(AircraftSystem)
    if aircraft_id:
        systems_q = systems_q.where(AircraftSystem.aircraft_id == aircraft_id)
    systems_result = await db.execute(systems_q)
    systems = systems_result.scalars().all()

    system_ids = {s.id for s in systems}

    # Fetch all dependencies where both endpoints are in the system set
    deps_result = await db.execute(select(SystemDependency))
    all_deps = deps_result.scalars().all()

    edges = [
        {
            "id": str(dep.id),
            "source": str(dep.source_system_id),
            "target": str(dep.target_system_id),
            "dependencyType": dep.dependency_type,
            "description": dep.description,
        }
        for dep in all_deps
        if dep.source_system_id in system_ids and dep.target_system_id in system_ids
    ]

    nodes = [
        {
            "id": str(s.id),
            "name": s.name,
            "category": s.category,
            "status": s.status,
            "health": s.health,
        }
        for s in systems
    ]

    return {"data": {"nodes": nodes, "edges": edges}}
