"""Unit tests for system dependency logic (mock DB)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.digital_twin.models import AircraftSystem, SystemDependency


def _make_system(name: str = "Hydraulics", category: str = "hydraulics") -> AircraftSystem:
    system = AircraftSystem()
    system.id = uuid.uuid4()
    system.aircraft_id = uuid.uuid4()
    system.name = name
    system.category = category
    system.status = "operational"
    system.health = 100.0
    return system


def _make_dependency(source: AircraftSystem, target: AircraftSystem,
                     dep_type: str = "powers") -> SystemDependency:
    dep = SystemDependency()
    dep.id = uuid.uuid4()
    dep.source_system_id = source.id
    dep.target_system_id = target.id
    dep.dependency_type = dep_type
    dep.description = "test dependency"
    return dep


class TestSystemDependencyModel:
    def test_dependency_fields_are_set(self):
        source = _make_system("Electrical", "electrical")
        target = _make_system("Avionics", "avionics")
        dep = _make_dependency(source, target, "powers")

        assert dep.source_system_id == source.id
        assert dep.target_system_id == target.id
        assert dep.dependency_type == "powers"
        assert dep.description == "test dependency"

    def test_dependency_id_is_uuid(self):
        source = _make_system()
        target = _make_system("Avionics", "avionics")
        dep = _make_dependency(source, target)
        assert isinstance(dep.id, uuid.UUID)

    def test_self_dependency_different_ids(self):
        """Source and target should be distinct systems."""
        source = _make_system("Hydraulics", "hydraulics")
        target = _make_system("Flight Controls", "flight-controls")
        assert source.id != target.id

    def test_dependency_types(self):
        valid_types = ["powers", "controls", "signals", "feeds"]
        source = _make_system()
        target = _make_system("Avionics", "avionics")
        for dep_type in valid_types:
            dep = _make_dependency(source, target, dep_type)
            assert dep.dependency_type == dep_type


class TestDependencyRouterLogic:
    """Test the routing logic with mock database calls."""

    @pytest.mark.asyncio
    async def test_self_dependency_returns_400(self):
        """The router should reject self-dependencies (system_id == targetSystemId)."""
        from fastapi import HTTPException

        from app.modules.auth.schemas import CurrentUser
        from app.modules.digital_twin.dependency_router import create_dependency

        system_id = uuid.uuid4()
        body = {
            "targetSystemId": str(system_id),
            "dependencyType": "powers",
        }
        current_user = CurrentUser(id=str(uuid.uuid4()), roles=["admin"], jti="")

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_system()
        mock_db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await create_dependency(system_id, body, mock_db, current_user)
        assert exc_info.value.status_code == 400
        assert "itself" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_fields_returns_400(self):
        """Missing targetSystemId or dependencyType should return 400."""
        from fastapi import HTTPException

        from app.modules.auth.schemas import CurrentUser
        from app.modules.digital_twin.dependency_router import create_dependency

        system_id = uuid.uuid4()
        current_user = CurrentUser(id=str(uuid.uuid4()), roles=["admin"], jti="")
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_dependency(system_id, {}, mock_db, current_user)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        """Trainee role should be rejected when creating a dependency."""
        from fastapi import HTTPException

        from app.modules.auth.schemas import CurrentUser
        from app.modules.digital_twin.dependency_router import create_dependency

        system_id = uuid.uuid4()
        body = {
            "targetSystemId": str(uuid.uuid4()),
            "dependencyType": "powers",
        }
        current_user = CurrentUser(id=str(uuid.uuid4()), roles=["trainee"], jti="")
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await create_dependency(system_id, body, mock_db, current_user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_delete_non_admin_returns_403(self):
        """Trainee role should be rejected when deleting a dependency."""
        from fastapi import HTTPException

        from app.modules.auth.schemas import CurrentUser
        from app.modules.digital_twin.dependency_router import delete_dependency

        current_user = CurrentUser(id=str(uuid.uuid4()), roles=["trainee"], jti="")
        mock_db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await delete_dependency(uuid.uuid4(), uuid.uuid4(), mock_db, current_user)
        assert exc_info.value.status_code == 403
