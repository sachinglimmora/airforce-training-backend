"""Integration tests for system dependency endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.modules.content.models import Aircraft
from app.modules.digital_twin.models import AircraftSystem, SystemDependency

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_token() -> str:
    return create_access_token(str(uuid.uuid4()), ["admin"])


def _trainee_token() -> str:
    return create_access_token(str(uuid.uuid4()), ["trainee"])


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_aircraft(db: AsyncSession) -> Aircraft:
    aircraft = Aircraft(
        id=uuid.uuid4(),
        type_code=f"LCA{uuid.uuid4().hex[:4].upper()}",
        manufacturer="HAL",
        display_name="Tejas MK1",
        active=True,
    )
    db.add(aircraft)
    await db.flush()
    return aircraft


async def _seed_system(db: AsyncSession, aircraft_id: uuid.UUID, name: str = "Hydraulics",
                       category: str = "hydraulics") -> AircraftSystem:
    system = AircraftSystem(
        id=uuid.uuid4(),
        aircraft_id=aircraft_id,
        name=name,
        category=category,
        status="operational",
        health=100.0,
    )
    db.add(system)
    await db.flush()
    return system


async def _seed_dependency(db: AsyncSession, source: AircraftSystem, target: AircraftSystem,
                           dep_type: str = "powers") -> SystemDependency:
    dep = SystemDependency(
        id=uuid.uuid4(),
        source_system_id=source.id,
        target_system_id=target.id,
        dependency_type=dep_type,
        description="test dep",
    )
    db.add(dep)
    await db.flush()
    return dep


# ---------------------------------------------------------------------------
# Tests — GET dependencies
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_dependencies_both(client: AsyncClient, db_session: AsyncSession):
    """GET /systems/{id}/dependencies returns upstream and downstream correctly."""
    aircraft = await _seed_aircraft(db_session)
    hydraulics = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    electrical = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    flight_ctrl = await _seed_system(db_session, aircraft.id, "Flight Controls", "flight-controls")

    # electrical --powers--> hydraulics (electrical is upstream of hydraulics)
    await _seed_dependency(db_session, electrical, hydraulics, "powers")
    # hydraulics --controls--> flight_ctrl (flight_ctrl is downstream of hydraulics)
    await _seed_dependency(db_session, hydraulics, flight_ctrl, "controls")
    await db_session.commit()

    token = _admin_token()
    r = await client.get(
        f"/api/v1/digital-twin/{hydraulics.id}/dependencies",
        headers=_auth_headers(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    upstream_ids = [u["id"] for u in data["upstream"]]
    downstream_ids = [d["id"] for d in data["downstream"]]
    assert str(electrical.id) in upstream_ids
    assert str(flight_ctrl.id) in downstream_ids


@pytest.mark.asyncio
async def test_get_dependencies_upstream_only(client: AsyncClient, db_session: AsyncSession):
    """direction=upstream returns only upstream systems."""
    aircraft = await _seed_aircraft(db_session)
    hydraulics = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    electrical = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    flight_ctrl = await _seed_system(db_session, aircraft.id, "Flight Controls", "flight-controls")

    await _seed_dependency(db_session, electrical, hydraulics, "powers")
    await _seed_dependency(db_session, hydraulics, flight_ctrl, "controls")
    await db_session.commit()

    token = _admin_token()
    r = await client.get(
        f"/api/v1/digital-twin/{hydraulics.id}/dependencies?direction=upstream",
        headers=_auth_headers(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["upstream"]) >= 1
    assert data["downstream"] == []


@pytest.mark.asyncio
async def test_get_dependencies_system_not_found(client: AsyncClient, db_session: AsyncSession):
    """GET dependencies for non-existent system returns 404."""
    token = _admin_token()
    r = await client.get(
        f"/api/v1/digital-twin/{uuid.uuid4()}/dependencies",
        headers=_auth_headers(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_dependencies_requires_auth(client: AsyncClient, db_session: AsyncSession):
    """Unauthenticated GET dependencies returns 401."""
    r = await client.get(f"/api/v1/digital-twin/{uuid.uuid4()}/dependencies")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tests — POST create dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_dependency_success(client: AsyncClient, db_session: AsyncSession):
    """Admin can create a dependency between two systems."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    target = await _seed_system(db_session, aircraft.id, "Avionics", "avionics")
    await db_session.commit()

    token = _admin_token()
    r = await client.post(
        f"/api/v1/digital-twin/{source.id}/dependencies",
        json={"targetSystemId": str(target.id), "dependencyType": "powers"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["sourceSystemId"] == str(source.id)
    assert data["targetSystemId"] == str(target.id)
    assert data["dependencyType"] == "powers"


@pytest.mark.asyncio
async def test_create_dependency_self_loop_400(client: AsyncClient, db_session: AsyncSession):
    """Creating a dependency where source == target returns 400."""
    aircraft = await _seed_aircraft(db_session)
    system = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    await db_session.commit()

    token = _admin_token()
    r = await client.post(
        f"/api/v1/digital-twin/{system.id}/dependencies",
        json={"targetSystemId": str(system.id), "dependencyType": "powers"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_dependency_source_not_found_404(client: AsyncClient,
                                                      db_session: AsyncSession):
    """Creating a dependency for a non-existent source system returns 404."""
    token = _admin_token()
    r = await client.post(
        f"/api/v1/digital-twin/{uuid.uuid4()}/dependencies",
        json={"targetSystemId": str(uuid.uuid4()), "dependencyType": "powers"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_dependency_target_not_found_404(client: AsyncClient,
                                                      db_session: AsyncSession):
    """Creating a dependency with non-existent target returns 404."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    await db_session.commit()

    token = _admin_token()
    r = await client.post(
        f"/api/v1/digital-twin/{source.id}/dependencies",
        json={"targetSystemId": str(uuid.uuid4()), "dependencyType": "powers"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_dependency_trainee_forbidden(client: AsyncClient, db_session: AsyncSession):
    """Trainee cannot create a dependency — returns 403."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    target = await _seed_system(db_session, aircraft.id, "Avionics", "avionics")
    await db_session.commit()

    token = _trainee_token()
    r = await client.post(
        f"/api/v1/digital-twin/{source.id}/dependencies",
        json={"targetSystemId": str(target.id), "dependencyType": "signals"},
        headers=_auth_headers(token),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tests — DELETE dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_dependency_success(client: AsyncClient, db_session: AsyncSession):
    """Admin can delete a dependency."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    target = await _seed_system(db_session, aircraft.id, "Flight Controls", "flight-controls")
    dep = await _seed_dependency(db_session, source, target, "controls")
    await db_session.commit()

    token = _admin_token()
    r = await client.delete(
        f"/api/v1/digital-twin/{source.id}/dependencies/{dep.id}",
        headers=_auth_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["data"]["message"] == "Dependency removed"


@pytest.mark.asyncio
async def test_delete_dependency_wrong_id_404(client: AsyncClient, db_session: AsyncSession):
    """Deleting a non-existent dependency returns 404."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    await db_session.commit()

    token = _admin_token()
    r = await client.delete(
        f"/api/v1/digital-twin/{source.id}/dependencies/{uuid.uuid4()}",
        headers=_auth_headers(token),
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_dependency_trainee_forbidden(client: AsyncClient, db_session: AsyncSession):
    """Trainee cannot delete a dependency — returns 403."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Hydraulics", "hydraulics")
    target = await _seed_system(db_session, aircraft.id, "Flight Controls", "flight-controls")
    dep = await _seed_dependency(db_session, source, target)
    await db_session.commit()

    token = _trainee_token()
    r = await client.delete(
        f"/api/v1/digital-twin/{source.id}/dependencies/{dep.id}",
        headers=_auth_headers(token),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tests — GET dependency-graph
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dependency_graph_returns_nodes_and_edges(client: AsyncClient,
                                                        db_session: AsyncSession):
    """GET /systems/dependency-graph returns nodes and edges."""
    aircraft = await _seed_aircraft(db_session)
    source = await _seed_system(db_session, aircraft.id, "Electrical", "electrical")
    target = await _seed_system(db_session, aircraft.id, "Avionics", "avionics")
    dep = await _seed_dependency(db_session, source, target, "powers")
    await db_session.commit()

    token = _admin_token()
    r = await client.get(
        "/api/v1/digital-twin/dependency-graph",
        headers=_auth_headers(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "nodes" in data
    assert "edges" in data

    node_ids = [n["id"] for n in data["nodes"]]
    edge_ids = [e["id"] for e in data["edges"]]
    assert str(source.id) in node_ids
    assert str(target.id) in node_ids
    assert str(dep.id) in edge_ids


@pytest.mark.asyncio
async def test_dependency_graph_filter_by_aircraft(client: AsyncClient, db_session: AsyncSession):
    """GET /systems/dependency-graph?aircraft_id=... filters to that aircraft's systems."""
    aircraft1 = await _seed_aircraft(db_session)
    aircraft2 = await _seed_aircraft(db_session)
    sys1 = await _seed_system(db_session, aircraft1.id, "Engine", "engine")
    sys2 = await _seed_system(db_session, aircraft2.id, "Avionics2", "avionics")
    await db_session.commit()

    token = _admin_token()
    r = await client.get(
        f"/api/v1/digital-twin/dependency-graph?aircraft_id={aircraft1.id}",
        headers=_auth_headers(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    node_ids = [n["id"] for n in data["nodes"]]
    assert str(sys1.id) in node_ids
    assert str(sys2.id) not in node_ids
