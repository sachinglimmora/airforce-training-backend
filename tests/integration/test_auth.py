import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client: AsyncClient):
    r = await client.get("/api/v1/users")
    assert r.status_code == 401
