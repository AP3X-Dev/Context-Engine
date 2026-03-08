"""Tests for ONI Cortex MCP SSE/HTTP proxy endpoints."""

import os
import pathlib

# Set test database URL BEFORE any cortex imports
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_sse.db"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.cortex.auth import CortexAuthMiddleware
from scripts.cortex.database import create_tenant, engine, init_db
from scripts.cortex.mcp_sse_proxy import router

DB_PATH = pathlib.Path("test_cortex_sse.db")


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with auth middleware and SSE proxy router."""
    app = FastAPI()
    app.add_middleware(CortexAuthMiddleware)
    app.include_router(router)

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


async def test_mcp_endpoint_requires_auth():
    """GET /t/someid/sse without auth returns 401."""
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/t/someid/sse")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing API key"


async def test_mcp_endpoint_wrong_tenant_id():
    """Valid API key but URL tenant_id doesn't match returns 403."""
    tenant = await create_tenant(
        name="SSE Corp",
        email="sse@example.com",
        password="secret",
        plan="free",
    )

    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/t/wrong-tenant-id/sse",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant ID mismatch"


async def test_mcp_sse_upstream_unavailable():
    """Valid auth, correct tenant_id, but no upstream MCP server returns 503."""
    tenant = await create_tenant(
        name="Upstream Corp",
        email="upstream@example.com",
        password="secret",
        plan="free",
    )

    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        f"/t/{tenant.id}/sse",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
