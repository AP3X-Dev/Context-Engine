"""Async database operations for ONI Cortex tenant management."""

import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql import func

from scripts.cortex import config
from scripts.cortex.models import Base, Tenant, TenantCollection, UsageRecord

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tenant(
    name: str,
    email: str,
    password: str,
    plan: str = "free",
) -> Tenant:
    """Create a new tenant with hashed password and generated API keys."""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    api_key_live = config.API_KEY_PREFIX_LIVE + secrets.token_hex(24)
    api_key_test = config.API_KEY_PREFIX_TEST + secrets.token_hex(24)

    tenant = Tenant(
        name=name,
        email=email,
        password_hash=password_hash,
        plan=plan,
        api_key_live=api_key_live,
        api_key_test=api_key_test,
    )

    async with get_session() as session:
        session.add(tenant)
        await session.flush()
        # Refresh to populate defaults
        await session.refresh(tenant)

    return tenant


async def get_tenant_by_api_key(api_key: str) -> Optional[Tenant]:
    """Look up a tenant by live OR test API key."""
    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(
                or_(Tenant.api_key_live == api_key, Tenant.api_key_test == api_key)
            )
        )
        return result.scalar_one_or_none()


async def get_tenant_by_email(email: str) -> Optional[Tenant]:
    """Look up a tenant by email."""
    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.email == email)
        )
        return result.scalar_one_or_none()


async def create_collection_for_tenant(
    tenant_id: str,
    collection_name: str,
    data_type: str = "code",
    config_json: Optional[str] = None,
) -> TenantCollection:
    """Register a new collection for a tenant."""
    collection = TenantCollection(
        tenant_id=tenant_id,
        collection_name=collection_name,
        data_type=data_type,
        config=config_json,
    )

    async with get_session() as session:
        session.add(collection)
        await session.flush()
        await session.refresh(collection)

    return collection


async def list_tenant_collections(tenant_id: str) -> list[TenantCollection]:
    """List all collections belonging to a tenant."""
    async with get_session() as session:
        result = await session.execute(
            select(TenantCollection).where(TenantCollection.tenant_id == tenant_id)
        )
        return list(result.scalars().all())


async def record_usage(tenant_id: str, metric: str, count: int) -> UsageRecord:
    """Insert a usage record."""
    record = UsageRecord(
        tenant_id=tenant_id,
        metric=metric,
        count=count,
    )

    async with get_session() as session:
        session.add(record)
        await session.flush()
        await session.refresh(record)

    return record


async def get_usage_count(
    tenant_id: str,
    metric: str,
    since: Optional[datetime] = None,
) -> int:
    """Sum usage count for a tenant/metric, optionally since a given datetime."""
    async with get_session() as session:
        stmt = select(func.coalesce(func.sum(UsageRecord.count), 0)).where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.metric == metric,
        )
        if since is not None:
            stmt = stmt.where(UsageRecord.recorded_at >= since)

        result = await session.execute(stmt)
        return result.scalar_one()
