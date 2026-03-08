"""Tests for ONI Cortex usage metering and per-tier rate limits."""

import os
import pathlib

# Set test database URL BEFORE any cortex imports
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_meter.db"

import pytest

from scripts.cortex.database import (
    create_tenant,
    get_usage_count,
    init_db,
    record_usage,
    engine,
)
from scripts.cortex.metering import MeterResult, check_rate_limit, meter_and_check

DB_PATH = pathlib.Path("test_cortex_meter.db")


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, clean up after."""
    await init_db()
    yield
    # Dispose engine connections so the file is released
    await engine.dispose()
    if DB_PATH.exists():
        DB_PATH.unlink()


async def test_free_tier_within_limit():
    """A fresh tenant on the free plan should be well within the query limit."""
    tenant = await create_tenant(
        name="Free Co",
        email="free@example.com",
        password="password",
        plan="free",
    )

    result = await check_rate_limit(tenant.id, "queries", "free")

    assert isinstance(result, MeterResult)
    assert result.allowed is True
    assert result.current == 0
    assert result.limit == 500
    assert result.metric == "queries"


async def test_free_tier_over_limit():
    """After exceeding the free-tier query limit the check should deny access."""
    tenant = await create_tenant(
        name="Over Co",
        email="over@example.com",
        password="password",
        plan="free",
    )

    # Record 501 queries (limit is 500)
    await record_usage(tenant.id, "queries", 501)

    result = await check_rate_limit(tenant.id, "queries", "free")

    assert result.allowed is False
    assert result.current == 501
    assert result.limit == 500
    assert result.metric == "queries"


async def test_enterprise_unlimited():
    """Enterprise tenants should never be rate-limited (limit=-1)."""
    tenant = await create_tenant(
        name="Enterprise Co",
        email="enterprise@example.com",
        password="password",
        plan="enterprise",
    )

    # Record a very large number of queries
    await record_usage(tenant.id, "queries", 999_999)

    result = await check_rate_limit(tenant.id, "queries", "enterprise")

    assert result.allowed is True
    assert result.current == 999_999
    assert result.limit == -1
    assert result.metric == "queries"


async def test_meter_and_check_records_usage():
    """meter_and_check should record usage and then return the check result."""
    tenant = await create_tenant(
        name="Meter Co",
        email="meter@example.com",
        password="password",
        plan="free",
    )

    result = await meter_and_check(tenant.id, "queries", "free", count=3)

    assert isinstance(result, MeterResult)
    assert result.allowed is True
    assert result.current == 3
    assert result.metric == "queries"

    # Verify the usage was actually persisted
    total = await get_usage_count(tenant.id, "queries")
    assert total == 3
