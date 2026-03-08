"""Tests for ONI Cortex tenant data model and CRUD operations."""

import os
import pathlib

# Set test database URL BEFORE any cortex imports
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex.db"

import pytest

from scripts.cortex.config import API_KEY_PREFIX_LIVE, API_KEY_PREFIX_TEST
from scripts.cortex.database import (
    create_collection_for_tenant,
    create_tenant,
    get_tenant_by_api_key,
    get_tenant_by_email,
    get_usage_count,
    init_db,
    list_tenant_collections,
    record_usage,
    engine,
)


DB_PATH = pathlib.Path("test_cortex.db")


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, clean up after."""
    await init_db()
    yield
    # Dispose engine connections so the file is released
    await engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


async def test_create_tenant():
    """Create a tenant and verify all fields are populated correctly."""
    tenant = await create_tenant(
        name="Acme Corp",
        email="admin@acme.com",
        password="supersecret",
        plan="pro",
    )

    assert tenant.id is not None
    assert len(tenant.id) == 36  # UUID format
    assert tenant.name == "Acme Corp"
    assert tenant.email == "admin@acme.com"
    assert tenant.plan == "pro"
    assert tenant.password_hash is not None
    assert tenant.password_hash != "supersecret"  # Should be hashed
    assert tenant.api_key_live.startswith(API_KEY_PREFIX_LIVE)
    assert tenant.api_key_test.startswith(API_KEY_PREFIX_TEST)
    assert tenant.created_at is not None
    assert tenant.updated_at is not None


async def test_get_tenant_by_api_key():
    """Look up a tenant by its live and test API keys."""
    tenant = await create_tenant(
        name="Lookup Co",
        email="lookup@example.com",
        password="password123",
    )

    # Look up by live key
    found = await get_tenant_by_api_key(tenant.api_key_live)
    assert found is not None
    assert found.id == tenant.id

    # Look up by test key
    found_test = await get_tenant_by_api_key(tenant.api_key_test)
    assert found_test is not None
    assert found_test.id == tenant.id


async def test_get_tenant_by_api_key_not_found():
    """Looking up a nonexistent API key returns None."""
    found = await get_tenant_by_api_key("oni_live_nonexistent_key")
    assert found is None


async def test_create_collection_for_tenant():
    """Create a collection and verify all fields."""
    tenant = await create_tenant(
        name="Collection Co",
        email="coll@example.com",
        password="password",
    )

    coll = await create_collection_for_tenant(
        tenant_id=tenant.id,
        collection_name="my_repo",
        data_type="code",
        config_json='{"language": "python"}',
    )

    assert coll.id is not None
    assert coll.tenant_id == tenant.id
    assert coll.collection_name == "my_repo"
    assert coll.data_type == "code"
    assert coll.config == '{"language": "python"}'
    assert coll.created_at is not None


async def test_list_tenant_collections():
    """Create 2 collections and verify list returns both."""
    tenant = await create_tenant(
        name="List Co",
        email="list@example.com",
        password="password",
    )

    await create_collection_for_tenant(
        tenant_id=tenant.id,
        collection_name="repo_a",
        data_type="code",
    )
    await create_collection_for_tenant(
        tenant_id=tenant.id,
        collection_name="repo_b",
        data_type="docs",
    )

    collections = await list_tenant_collections(tenant.id)
    assert len(collections) == 2
    names = {c.collection_name for c in collections}
    assert names == {"repo_a", "repo_b"}


async def test_record_and_get_usage():
    """Record usage entries and verify the sum is correct."""
    tenant = await create_tenant(
        name="Usage Co",
        email="usage@example.com",
        password="password",
    )

    await record_usage(tenant.id, "queries", 5)
    await record_usage(tenant.id, "queries", 3)

    total = await get_usage_count(tenant.id, "queries")
    assert total == 8


async def test_duplicate_email_rejected():
    """Inserting a tenant with a duplicate email should raise an exception."""
    await create_tenant(
        name="First",
        email="dupe@example.com",
        password="password",
    )

    with pytest.raises(Exception):
        await create_tenant(
            name="Second",
            email="dupe@example.com",
            password="password",
        )
