"""Tests for ONI Cortex tenant provisioning API."""

import os
import pathlib

# Set test database URL BEFORE any cortex imports
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_api.db"

import pytest
from fastapi.testclient import TestClient

from scripts.cortex.api import create_app
from scripts.cortex.database import engine, init_db

DB_PATH = pathlib.Path("test_cortex_api.db")


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, clean up after."""
    await init_db()
    yield
    await engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


def _make_client() -> TestClient:
    """Create a TestClient for the Cortex app."""
    return TestClient(create_app(), raise_server_exceptions=False)


def _signup(client: TestClient, email: str = "test@example.com", name: str = "Test User"):
    """Helper: sign up a tenant and return response data."""
    resp = client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": "s3cret!"},
    )
    return resp


async def test_health():
    """GET /health returns 200 with service info."""
    client = _make_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "oni-cortex"


async def test_signup():
    """POST /api/v1/auth/signup creates tenant with all expected fields."""
    client = _make_client()
    resp = _signup(client)
    assert resp.status_code == 201
    data = resp.json()
    assert "tenant_id" in data
    assert data["name"] == "Test User"
    assert data["email"] == "test@example.com"
    assert data["plan"] == "free"
    assert data["api_key_live"].startswith("oni_live_")
    assert data["api_key_test"].startswith("oni_test_")
    assert "/sse" in data["mcp_url"]


async def test_signup_duplicate_email():
    """Signing up twice with the same email returns 409."""
    client = _make_client()
    resp1 = _signup(client, email="dup@example.com")
    assert resp1.status_code == 201
    resp2 = _signup(client, email="dup@example.com")
    assert resp2.status_code == 409


async def test_list_collections_unauthenticated():
    """GET /api/v1/collections without auth returns 401."""
    client = _make_client()
    resp = client.get("/api/v1/collections")
    assert resp.status_code == 401


async def test_list_collections_authenticated():
    """Signup, create collection, then list collections returns them."""
    client = _make_client()
    # Use "pro" plan so we have room for more than 1 collection (free allows only 1)
    resp = client.post(
        "/api/v1/auth/signup",
        json={"name": "Pro User", "email": "pro@example.com", "password": "s3cret!", "plan": "pro"},
    )
    assert resp.status_code == 201
    signup_data = resp.json()
    api_key = signup_data["api_key_live"]
    headers = {"Authorization": f"Bearer {api_key}"}

    # Create an additional collection
    resp = client.post(
        "/api/v1/collections",
        json={"collection_name": "docs", "data_type": "documentation"},
        headers=headers,
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["collection_name"] == "docs"
    assert created["data_type"] == "documentation"
    assert created["vector_count"] == 0
    assert signup_data["tenant_id"] in created["qdrant_collection"]

    # List collections — should have "default" (from signup) + "docs"
    resp = client.get("/api/v1/collections", headers=headers)
    assert resp.status_code == 200
    collections = resp.json()
    names = {c["collection_name"] for c in collections}
    assert "default" in names
    assert "docs" in names


async def test_get_me():
    """GET /api/v1/me returns tenant info and usage stats."""
    client = _make_client()
    signup_data = _signup(client).json()
    api_key = signup_data["api_key_live"]
    headers = {"Authorization": f"Bearer {api_key}"}

    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == signup_data["tenant_id"]
    assert data["name"] == "Test User"
    assert data["email"] == "test@example.com"
    assert data["plan"] == "free"
    assert data["collections"] >= 1  # at least the default collection
    assert "queries_today" in data["usage"]
    assert "queries_limit" in data["usage"]
    assert "collections" in data["limits"]


async def test_rotate_key():
    """POST /api/v1/me/rotate-key returns new keys; old key stops working."""
    client = _make_client()
    signup_data = _signup(client).json()
    old_key = signup_data["api_key_live"]
    headers = {"Authorization": f"Bearer {old_key}"}

    # Rotate
    resp = client.post("/api/v1/me/rotate-key", headers=headers)
    assert resp.status_code == 200
    rotate_data = resp.json()
    assert rotate_data["api_key_live"].startswith("oni_live_")
    assert rotate_data["api_key_test"].startswith("oni_test_")
    assert rotate_data["api_key_live"] != old_key
    assert "message" in rotate_data

    # New key works
    new_headers = {"Authorization": f"Bearer {rotate_data['api_key_live']}"}
    resp = client.get("/api/v1/me", headers=new_headers)
    assert resp.status_code == 200

    # Old key no longer works
    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == 401
