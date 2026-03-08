"""Tests for ONI Cortex API key authentication middleware."""

import os
import pathlib

# Set test database URL BEFORE any cortex imports
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_auth.db"

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from scripts.cortex.auth import CortexAuthMiddleware, get_current_tenant
from scripts.cortex.database import create_tenant, engine, init_db

DB_PATH = pathlib.Path("test_cortex_auth.db")


def _build_app() -> FastAPI:
    """Create a minimal FastAPI app with auth middleware for testing."""
    app = FastAPI()
    app.add_middleware(CortexAuthMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request):
        tenant = get_current_tenant(request)
        return {"tenant_id": tenant.id, "name": tenant.name}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, clean up after."""
    await init_db()
    yield
    await engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


async def test_valid_api_key_in_header():
    """Authenticated request via Bearer header returns 200 with tenant info."""
    tenant = await create_tenant(
        name="Auth Corp",
        email="auth@example.com",
        password="secret",
    )

    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/test",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant.id
    assert data["name"] == "Auth Corp"


async def test_valid_api_key_in_query_param():
    """Authenticated request via query parameter returns 200."""
    tenant = await create_tenant(
        name="Query Corp",
        email="query@example.com",
        password="secret",
    )

    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(f"/test?key={tenant.api_key_test}")

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant.id


async def test_missing_api_key():
    """Request with no API key returns 401."""
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


async def test_invalid_api_key():
    """Request with a bogus API key returns 401."""
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/test",
        headers={"Authorization": "Bearer oni_live_bogus_key_that_does_not_exist"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


async def test_health_endpoint_no_auth():
    """Health endpoint bypasses auth and returns 200."""
    app = _build_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
