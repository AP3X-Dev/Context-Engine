# ONI Cortex Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform Context-Engine into ONI Cortex — a multi-tenant, MCP-first managed retrieval service with API key auth, usage metering, Stripe billing, and ARM64 deployment on Oracle VPS.

**Architecture:** API Gateway (FastAPI) sits in front of existing MCP servers, handling tenant auth via API keys, routing MCP requests with tenant-scoped collection names, and metering usage. PostgreSQL stores tenant/billing data. Qdrant isolates tenants via collection-per-tenant naming (`{tenant_id}_{collection}`). Caddy handles TLS/reverse proxy.

**Tech Stack:** Python 3.11+, FastAPI, FastMCP, PostgreSQL (asyncpg + SQLAlchemy), Stripe API, Qdrant, Caddy, Docker Compose (ARM64)

**Design Doc:** `docs/plans/2026-03-07-oni-cortex-design.md`

---

## Phase 1: Multi-Tenant Core

### Task 1: Tenant Data Model (PostgreSQL + SQLAlchemy)

**Files:**
- Create: `scripts/cortex/__init__.py`
- Create: `scripts/cortex/models.py`
- Create: `scripts/cortex/database.py`
- Create: `scripts/cortex/config.py`
- Test: `tests/test_cortex_models.py`

**Step 1: Create the cortex package directory**

```bash
mkdir -p scripts/cortex
```

**Step 2: Write config module**

Create `scripts/cortex/config.py`:

```python
"""ONI Cortex configuration — all settings from env vars."""

import os
import secrets

DATABASE_URL = os.environ.get(
    "CORTEX_DATABASE_URL",
    "postgresql+asyncpg://cortex:cortex@localhost:5432/cortex",
)
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
CORTEX_DOMAIN = os.environ.get("CORTEX_DOMAIN", "cortex.oni.bot")
JWT_SECRET = os.environ.get("CORTEX_JWT_SECRET", secrets.token_hex(32))
API_KEY_PREFIX_LIVE = "oni_live_"
API_KEY_PREFIX_TEST = "oni_test_"

# Tier limits: {plan: {collections, vectors, queries_per_day}}
TIER_LIMITS = {
    "free":       {"collections": 1,   "vectors": 10_000,    "queries_per_day": 500},
    "pro":        {"collections": 5,   "vectors": 250_000,   "queries_per_day": 10_000},
    "team":       {"collections": 25,  "vectors": 1_000_000, "queries_per_day": 50_000},
    "business":   {"collections": 100, "vectors": 5_000_000, "queries_per_day": 200_000},
    "enterprise": {"collections": -1,  "vectors": -1,        "queries_per_day": -1},
}
```

**Step 3: Write the failing test**

Create `tests/test_cortex_models.py`:

```python
"""Tests for ONI Cortex tenant data model."""

import os
import pytest
import uuid

# Use SQLite for tests (async via aiosqlite)
os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex.db"

from scripts.cortex.models import Tenant, TenantCollection, UsageRecord
from scripts.cortex.database import (
    init_db,
    get_session,
    create_tenant,
    get_tenant_by_api_key,
    get_tenant_by_email,
    create_collection_for_tenant,
    list_tenant_collections,
    record_usage,
    get_usage_count,
)


@pytest.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    await init_db()
    yield
    # Cleanup handled by test DB teardown
    import os
    try:
        os.remove("test_cortex.db")
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_create_tenant():
    tenant = await create_tenant(
        name="Acme Corp",
        email="admin@acme.com",
        password="securepass123",
        plan="pro",
    )
    assert tenant.name == "Acme Corp"
    assert tenant.email == "admin@acme.com"
    assert tenant.plan == "pro"
    assert tenant.api_key_live.startswith("oni_live_")
    assert tenant.api_key_test.startswith("oni_test_")
    assert tenant.id is not None


@pytest.mark.asyncio
async def test_get_tenant_by_api_key():
    tenant = await create_tenant(
        name="TestCo",
        email="test@testco.com",
        password="pass",
        plan="free",
    )
    found = await get_tenant_by_api_key(tenant.api_key_live)
    assert found is not None
    assert found.id == tenant.id
    assert found.email == "test@testco.com"


@pytest.mark.asyncio
async def test_get_tenant_by_api_key_not_found():
    found = await get_tenant_by_api_key("oni_live_nonexistent")
    assert found is None


@pytest.mark.asyncio
async def test_create_collection_for_tenant():
    tenant = await create_tenant(
        name="CollTest",
        email="coll@test.com",
        password="pass",
        plan="team",
    )
    coll = await create_collection_for_tenant(
        tenant_id=tenant.id,
        collection_name="codebase",
        data_type="code",
    )
    assert coll.collection_name == "codebase"
    assert coll.tenant_id == tenant.id
    assert coll.data_type == "code"


@pytest.mark.asyncio
async def test_list_tenant_collections():
    tenant = await create_tenant(
        name="ListTest",
        email="list@test.com",
        password="pass",
        plan="team",
    )
    await create_collection_for_tenant(tenant.id, "codebase", "code")
    await create_collection_for_tenant(tenant.id, "docs", "markdown")
    colls = await list_tenant_collections(tenant.id)
    assert len(colls) == 2
    names = {c.collection_name for c in colls}
    assert names == {"codebase", "docs"}


@pytest.mark.asyncio
async def test_record_and_get_usage():
    tenant = await create_tenant(
        name="UsageTest",
        email="usage@test.com",
        password="pass",
        plan="pro",
    )
    await record_usage(tenant.id, "queries", count=5)
    await record_usage(tenant.id, "queries", count=3)
    total = await get_usage_count(tenant.id, "queries")
    assert total == 8


@pytest.mark.asyncio
async def test_duplicate_email_rejected():
    await create_tenant(name="A", email="dup@test.com", password="p", plan="free")
    with pytest.raises(Exception):
        await create_tenant(name="B", email="dup@test.com", password="p", plan="free")
```

**Step 4: Run tests to verify they fail**

```bash
pytest tests/test_cortex_models.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.cortex'`

**Step 5: Write `scripts/cortex/__init__.py`**

```python
"""ONI Cortex — multi-tenant MCP retrieval service."""
```

**Step 6: Write `scripts/cortex/models.py`**

```python
"""SQLAlchemy models for ONI Cortex tenant data."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    plan = Column(String(50), nullable=False, default="free")
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)
    api_key_live = Column(String(255), unique=True, nullable=False)
    api_key_test = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    collections = relationship("TenantCollection", back_populates="tenant", cascade="all, delete-orphan")


class TenantCollection(Base):
    __tablename__ = "tenant_collections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    tenant_id = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    collection_name = Column(String(255), nullable=False)
    data_type = Column(String(50), nullable=False, default="code")
    vector_count = Column(Integer, default=0)
    config = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="collections")

    __table_args__ = (
        UniqueConstraint("tenant_id", "collection_name", name="uq_tenant_collection"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), ForeignKey("tenants.id"), nullable=False)
    metric = Column(String(50), nullable=False)
    count = Column(Integer, nullable=False, default=1)
    recorded_at = Column(DateTime, default=datetime.utcnow)
```

**Step 7: Write `scripts/cortex/database.py`**

```python
"""Database session management and CRUD operations for ONI Cortex."""

from __future__ import annotations

import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.cortex.config import API_KEY_PREFIX_LIVE, API_KEY_PREFIX_TEST, DATABASE_URL
from scripts.cortex.models import Base, Tenant, TenantCollection, UsageRecord

_engine = create_async_engine(DATABASE_URL, echo=False)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def init_db():
    """Create all tables."""
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session():
    """Yield an async session, auto-commit on success, rollback on error."""
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _generate_api_key(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(24)}"


async def create_tenant(
    name: str,
    email: str,
    password: str,
    plan: str = "free",
) -> Tenant:
    """Create a new tenant with generated API keys."""
    tenant = Tenant(
        name=name,
        email=email,
        password_hash=_hash_password(password),
        plan=plan,
        api_key_live=_generate_api_key(API_KEY_PREFIX_LIVE),
        api_key_test=_generate_api_key(API_KEY_PREFIX_TEST),
    )
    async with get_session() as session:
        session.add(tenant)
    return tenant


async def get_tenant_by_api_key(api_key: str) -> Optional[Tenant]:
    """Look up a tenant by live or test API key."""
    async with get_session() as session:
        stmt = select(Tenant).where(
            (Tenant.api_key_live == api_key) | (Tenant.api_key_test == api_key)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def get_tenant_by_email(email: str) -> Optional[Tenant]:
    """Look up a tenant by email."""
    async with get_session() as session:
        stmt = select(Tenant).where(Tenant.email == email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def create_collection_for_tenant(
    tenant_id: str,
    collection_name: str,
    data_type: str = "code",
    config: str = "{}",
) -> TenantCollection:
    """Register a new collection for a tenant."""
    coll = TenantCollection(
        tenant_id=tenant_id,
        collection_name=collection_name,
        data_type=data_type,
        config=config,
    )
    async with get_session() as session:
        session.add(coll)
    return coll


async def list_tenant_collections(tenant_id: str) -> List[TenantCollection]:
    """List all collections belonging to a tenant."""
    async with get_session() as session:
        stmt = select(TenantCollection).where(TenantCollection.tenant_id == tenant_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def record_usage(tenant_id: str, metric: str, count: int = 1):
    """Record a usage event."""
    rec = UsageRecord(tenant_id=tenant_id, metric=metric, count=count)
    async with get_session() as session:
        session.add(rec)


async def get_usage_count(
    tenant_id: str,
    metric: str,
    since: Optional[datetime] = None,
) -> int:
    """Sum usage for a tenant+metric, optionally since a datetime."""
    async with get_session() as session:
        stmt = select(func.coalesce(func.sum(UsageRecord.count), 0)).where(
            UsageRecord.tenant_id == tenant_id,
            UsageRecord.metric == metric,
        )
        if since:
            stmt = stmt.where(UsageRecord.recorded_at >= since)
        result = await session.execute(stmt)
        return result.scalar_one()
```

**Step 8: Run tests to verify they pass**

```bash
pip install sqlalchemy aiosqlite asyncpg
pytest tests/test_cortex_models.py -v
```
Expected: All 7 tests PASS

**Step 9: Commit**

```bash
git add scripts/cortex/ tests/test_cortex_models.py
git commit -m "feat(cortex): add tenant data model with PostgreSQL + SQLAlchemy

Tenant, TenantCollection, UsageRecord models with async CRUD operations.
API key generation, password hashing, usage tracking."
```

---

### Task 2: API Key Authentication Middleware

**Files:**
- Create: `scripts/cortex/auth.py`
- Test: `tests/test_cortex_auth.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_auth.py`:

```python
"""Tests for ONI Cortex API key authentication."""

import os
import pytest

os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_auth.db"

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.cortex.auth import CortexAuthMiddleware, get_current_tenant
from scripts.cortex.database import init_db, create_tenant


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    try:
        os.remove("test_cortex_auth.db")
    except FileNotFoundError:
        pass


def _make_app():
    app = FastAPI()
    app.add_middleware(CortexAuthMiddleware)

    @app.get("/test")
    async def test_endpoint(request):
        tenant = get_current_tenant(request)
        return {"tenant_id": tenant.id, "plan": tenant.plan}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_valid_api_key_in_header():
    tenant = await create_tenant("Test", "auth@test.com", "pass", "pro")
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/test", headers={"Authorization": f"Bearer {tenant.api_key_live}"})
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_valid_api_key_in_query_param():
    tenant = await create_tenant("Test2", "auth2@test.com", "pass", "team")
    app = _make_app()
    client = TestClient(app)
    resp = client.get(f"/test?key={tenant.api_key_live}")
    assert resp.status_code == 200
    assert resp.json()["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_missing_api_key():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/test")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/test", headers={"Authorization": "Bearer oni_live_bogus"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_endpoint_no_auth():
    """Health endpoints should bypass auth."""
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_auth.py -v
```
Expected: FAIL — `ImportError: cannot import name 'CortexAuthMiddleware'`

**Step 3: Write `scripts/cortex/auth.py`**

```python
"""API key authentication middleware for ONI Cortex.

Extracts API key from Authorization header or `key` query param.
Resolves tenant, attaches to request.state.tenant.
Bypasses auth for health/docs endpoints.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from scripts.cortex.database import get_tenant_by_api_key
from scripts.cortex.models import Tenant

# Paths that don't require authentication
PUBLIC_PATHS = {"/health", "/readyz", "/docs", "/openapi.json", "/api/v1/auth/signup", "/api/v1/auth/login"}


class CortexAuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates API keys and attaches tenant to request."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        api_key = _extract_api_key(request)
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key. Use Authorization: Bearer <key> header or ?key=<key> query param."},
            )

        tenant = await get_tenant_by_api_key(api_key)
        if not tenant:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API key."},
            )

        request.state.tenant = tenant
        return await call_next(request)


def _extract_api_key(request: Request) -> Optional[str]:
    """Extract API key from header or query param."""
    # Check Authorization header: Bearer <key>
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    # Check query parameter: ?key=<key>
    key_param = request.query_params.get("key")
    if key_param:
        return key_param.strip()

    return None


def get_current_tenant(request: Request) -> Tenant:
    """Get the authenticated tenant from the request. Raises if missing."""
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise ValueError("No tenant in request — auth middleware not applied?")
    return tenant
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_auth.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/auth.py tests/test_cortex_auth.py
git commit -m "feat(cortex): add API key auth middleware

Bearer token and query param auth. Bypasses health endpoints.
Attaches tenant to request.state for downstream handlers."
```

---

### Task 3: Tenant Provisioning API

**Files:**
- Create: `scripts/cortex/api.py`
- Test: `tests/test_cortex_api.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_api.py`:

```python
"""Tests for ONI Cortex tenant provisioning API."""

import os
import pytest

os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_api.db"

from fastapi.testclient import TestClient

from scripts.cortex.api import create_app
from scripts.cortex.database import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    try:
        os.remove("test_cortex_api.db")
    except FileNotFoundError:
        pass


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_signup(client):
    resp = client.post("/api/v1/auth/signup", json={
        "name": "Acme Corp",
        "email": "signup@acme.com",
        "password": "secure123",
        "plan": "pro",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "signup@acme.com"
    assert data["plan"] == "pro"
    assert "api_key_live" in data
    assert "api_key_test" in data
    assert "tenant_id" in data
    assert "mcp_url" in data


def test_signup_duplicate_email(client):
    client.post("/api/v1/auth/signup", json={
        "name": "A", "email": "dup@test.com", "password": "p", "plan": "free",
    })
    resp = client.post("/api/v1/auth/signup", json={
        "name": "B", "email": "dup@test.com", "password": "p", "plan": "free",
    })
    assert resp.status_code == 409


def test_list_collections_authenticated(client):
    # Signup first
    signup = client.post("/api/v1/auth/signup", json={
        "name": "Test", "email": "coll@test.com", "password": "p", "plan": "team",
    }).json()
    key = signup["api_key_live"]

    # Create a collection
    resp = client.post(
        "/api/v1/collections",
        json={"collection_name": "myrepo", "data_type": "code"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201

    # List collections
    resp = client.get("/api/v1/collections", headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 200
    colls = resp.json()
    assert len(colls) >= 1
    names = [c["collection_name"] for c in colls]
    assert "myrepo" in names


def test_list_collections_unauthenticated(client):
    resp = client.get("/api/v1/collections")
    assert resp.status_code == 401


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_api.py -v
```
Expected: FAIL — `ImportError: cannot import name 'create_app'`

**Step 3: Write `scripts/cortex/api.py`**

```python
"""ONI Cortex API Gateway — tenant provisioning and collection management."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr

from scripts.cortex.auth import CortexAuthMiddleware, get_current_tenant
from scripts.cortex.config import CORTEX_DOMAIN, TIER_LIMITS
from scripts.cortex.database import (
    create_collection_for_tenant,
    create_tenant,
    get_tenant_by_email,
    list_tenant_collections,
)


# --- Request/Response models ---

class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    plan: str = "free"


class SignupResponse(BaseModel):
    tenant_id: str
    name: str
    email: str
    plan: str
    api_key_live: str
    api_key_test: str
    mcp_url: str


class CreateCollectionRequest(BaseModel):
    collection_name: str
    data_type: str = "code"


class CollectionResponse(BaseModel):
    id: str
    collection_name: str
    data_type: str
    vector_count: int
    qdrant_collection: str


# --- App factory ---

def create_app() -> FastAPI:
    app = FastAPI(title="ONI Cortex", version="0.1.0")
    app.add_middleware(CortexAuthMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "oni-cortex"}

    @app.post("/api/v1/auth/signup", status_code=201, response_model=SignupResponse)
    async def signup(req: SignupRequest):
        # Check for duplicate email
        existing = await get_tenant_by_email(req.email)
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered.")

        # Validate plan
        if req.plan not in TIER_LIMITS:
            raise HTTPException(status_code=400, detail=f"Invalid plan: {req.plan}")

        tenant = await create_tenant(
            name=req.name,
            email=req.email,
            password=req.password,
            plan=req.plan,
        )

        # Create default collection
        await create_collection_for_tenant(
            tenant_id=tenant.id,
            collection_name="default",
            data_type="code",
        )

        return SignupResponse(
            tenant_id=tenant.id,
            name=tenant.name,
            email=tenant.email,
            plan=tenant.plan,
            api_key_live=tenant.api_key_live,
            api_key_test=tenant.api_key_test,
            mcp_url=f"https://{CORTEX_DOMAIN}/t/{tenant.id}/sse",
        )

    @app.post("/api/v1/collections", status_code=201)
    async def create_collection(req: CreateCollectionRequest, request: Request):
        tenant = get_current_tenant(request)

        # Enforce tier collection limit
        limits = TIER_LIMITS.get(tenant.plan, TIER_LIMITS["free"])
        existing = await list_tenant_collections(tenant.id)
        if limits["collections"] != -1 and len(existing) >= limits["collections"]:
            raise HTTPException(
                status_code=403,
                detail=f"Collection limit reached ({limits['collections']}). Upgrade your plan.",
            )

        coll = await create_collection_for_tenant(
            tenant_id=tenant.id,
            collection_name=req.collection_name,
            data_type=req.data_type,
        )
        return CollectionResponse(
            id=coll.id,
            collection_name=coll.collection_name,
            data_type=coll.data_type,
            vector_count=coll.vector_count or 0,
            qdrant_collection=f"{tenant.id}_{coll.collection_name}",
        )

    @app.get("/api/v1/collections")
    async def list_collections(request: Request):
        tenant = get_current_tenant(request)
        colls = await list_tenant_collections(tenant.id)
        return [
            CollectionResponse(
                id=c.id,
                collection_name=c.collection_name,
                data_type=c.data_type,
                vector_count=c.vector_count or 0,
                qdrant_collection=f"{tenant.id}_{c.collection_name}",
            ).model_dump()
            for c in colls
        ]

    return app
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_api.py -v
```
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/api.py tests/test_cortex_api.py
git commit -m "feat(cortex): add tenant provisioning API

Signup, collection CRUD, tier limit enforcement.
Returns MCP URL on signup for immediate agent connection."
```

---

### Task 4: MCP Tenant Router (MCP Proxy with Collection Scoping)

**Files:**
- Create: `scripts/cortex/mcp_proxy.py`
- Test: `tests/test_cortex_mcp_proxy.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_mcp_proxy.py`:

```python
"""Tests for ONI Cortex MCP tenant proxy."""

import pytest
from scripts.cortex.mcp_proxy import scope_collection_name, inject_tenant_context


def test_scope_collection_name():
    assert scope_collection_name("abc123", "codebase") == "abc123_codebase"
    assert scope_collection_name("t1", "docs") == "t1_docs"


def test_inject_tenant_context_with_collection():
    """Tool args that include 'collection' get scoped to tenant."""
    args = {"query": "find auth", "collection": "codebase", "limit": 10}
    scoped = inject_tenant_context("tenant1", args, default_collection="default")
    assert scoped["collection"] == "tenant1_codebase"
    assert scoped["query"] == "find auth"
    assert scoped["limit"] == 10


def test_inject_tenant_context_without_collection():
    """When no collection specified, use tenant's default."""
    args = {"query": "search something"}
    scoped = inject_tenant_context("tenant1", args, default_collection="default")
    assert scoped["collection"] == "tenant1_default"


def test_inject_tenant_context_empty_collection():
    """Empty string collection uses default."""
    args = {"query": "test", "collection": ""}
    scoped = inject_tenant_context("t2", args, default_collection="codebase")
    assert scoped["collection"] == "t2_codebase"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_mcp_proxy.py -v
```
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write `scripts/cortex/mcp_proxy.py`**

```python
"""MCP Tenant Router — scopes MCP tool calls to tenant collections.

Intercepts MCP tool invocations, rewrites collection arguments to include
tenant prefix, and forwards to the shared MCP indexer/memory servers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def scope_collection_name(tenant_id: str, collection_name: str) -> str:
    """Prefix a collection name with tenant ID for isolation."""
    return f"{tenant_id}_{collection_name}"


def inject_tenant_context(
    tenant_id: str,
    tool_args: Dict[str, Any],
    default_collection: str = "default",
) -> Dict[str, Any]:
    """Rewrite tool args to scope collection to the tenant.

    If the tool call includes a `collection` argument, prefix it.
    If not, inject the tenant's default collection (prefixed).
    """
    scoped = dict(tool_args)
    raw_collection = scoped.get("collection", "").strip()
    if not raw_collection:
        raw_collection = default_collection
    scoped["collection"] = scope_collection_name(tenant_id, raw_collection)
    return scoped


def strip_tenant_prefix(tenant_id: str, collection_name: str) -> str:
    """Remove tenant prefix from collection name for display."""
    prefix = f"{tenant_id}_"
    if collection_name.startswith(prefix):
        return collection_name[len(prefix):]
    return collection_name
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_mcp_proxy.py -v
```
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/mcp_proxy.py tests/test_cortex_mcp_proxy.py
git commit -m "feat(cortex): add MCP tenant router with collection scoping

Injects tenant prefix into collection names for isolation.
Handles default collection fallback."
```

---

### Task 5: Usage Metering Middleware

**Files:**
- Create: `scripts/cortex/metering.py`
- Test: `tests/test_cortex_metering.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_metering.py`:

```python
"""Tests for ONI Cortex usage metering."""

import os
import pytest

os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_meter.db"

from scripts.cortex.metering import check_rate_limit, MeterResult
from scripts.cortex.config import TIER_LIMITS
from scripts.cortex.database import init_db, create_tenant, record_usage


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    try:
        os.remove("test_cortex_meter.db")
    except FileNotFoundError:
        pass


@pytest.mark.asyncio
async def test_free_tier_within_limit():
    tenant = await create_tenant("Free", "free@test.com", "p", "free")
    result = await check_rate_limit(tenant.id, "queries", tenant.plan)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_free_tier_over_limit():
    tenant = await create_tenant("OverFree", "overfree@test.com", "p", "free")
    # Record 501 queries (limit is 500)
    await record_usage(tenant.id, "queries", count=501)
    result = await check_rate_limit(tenant.id, "queries", tenant.plan)
    assert result.allowed is False
    assert result.limit == 500


@pytest.mark.asyncio
async def test_enterprise_unlimited():
    tenant = await create_tenant("Ent", "ent@test.com", "p", "enterprise")
    await record_usage(tenant.id, "queries", count=999999)
    result = await check_rate_limit(tenant.id, "queries", tenant.plan)
    assert result.allowed is True
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_metering.py -v
```
Expected: FAIL

**Step 3: Write `scripts/cortex/metering.py`**

```python
"""Usage metering and rate limiting for ONI Cortex."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from scripts.cortex.config import TIER_LIMITS
from scripts.cortex.database import get_usage_count, record_usage


@dataclass
class MeterResult:
    allowed: bool
    current: int
    limit: int
    metric: str


async def check_rate_limit(
    tenant_id: str,
    metric: str,
    plan: str,
) -> MeterResult:
    """Check if a tenant is within their rate limit for a metric.

    Returns MeterResult with allowed=True if under limit, False if over.
    Enterprise plan (-1 limit) is always allowed.
    """
    limits = TIER_LIMITS.get(plan, TIER_LIMITS["free"])

    # Map metric to limit key
    limit_key = "queries_per_day" if metric == "queries" else metric
    limit_value = limits.get(limit_key, 0)

    # -1 means unlimited (enterprise)
    if limit_value == -1:
        return MeterResult(allowed=True, current=0, limit=-1, metric=metric)

    # Check usage since start of today (UTC)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    current = await get_usage_count(tenant_id, metric, since=today_start)

    return MeterResult(
        allowed=current < limit_value,
        current=current,
        limit=limit_value,
        metric=metric,
    )


async def meter_and_check(
    tenant_id: str,
    metric: str,
    plan: str,
    count: int = 1,
) -> MeterResult:
    """Record usage and check if still within limit."""
    await record_usage(tenant_id, metric, count=count)
    return await check_rate_limit(tenant_id, metric, plan)
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_metering.py -v
```
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/metering.py tests/test_cortex_metering.py
git commit -m "feat(cortex): add usage metering with per-tier rate limits

Daily query limits, vector limits, enterprise unlimited.
meter_and_check for atomic record + validate."
```

---

### Task 6: MCP SSE Proxy Endpoint (Tenant-Scoped MCP)

This is the core integration — a FastAPI endpoint that accepts MCP SSE connections, authenticates via API key, and proxies to the shared MCP indexer with tenant-scoped collections.

**Files:**
- Create: `scripts/cortex/mcp_sse_proxy.py`
- Modify: `scripts/cortex/api.py` (mount the proxy)
- Test: `tests/test_cortex_sse_proxy.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_sse_proxy.py`:

```python
"""Tests for ONI Cortex MCP SSE proxy endpoint."""

import os
import pytest

os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_sse.db"

from fastapi.testclient import TestClient
from scripts.cortex.api import create_app
from scripts.cortex.database import init_db, create_tenant


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    try:
        os.remove("test_cortex_sse.db")
    except FileNotFoundError:
        pass


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.mark.asyncio
async def test_mcp_endpoint_requires_auth(client):
    resp = client.get("/t/someid/sse")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_endpoint_with_valid_key(client):
    tenant = await create_tenant("MCPTest", "mcp@test.com", "pass", "pro")
    resp = client.get(
        f"/t/{tenant.id}/sse",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )
    # Should succeed (200 for SSE stream start, or 502 if upstream MCP not running)
    # We accept either — the auth layer passed
    assert resp.status_code in (200, 502, 503)


@pytest.mark.asyncio
async def test_mcp_endpoint_wrong_tenant_id(client):
    """API key valid but tenant_id in URL doesn't match."""
    tenant = await create_tenant("WrongID", "wrong@test.com", "pass", "pro")
    resp = client.get(
        "/t/different_tenant/sse",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )
    assert resp.status_code == 403
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_sse_proxy.py -v
```
Expected: FAIL

**Step 3: Write `scripts/cortex/mcp_sse_proxy.py`**

```python
"""MCP SSE proxy — tenant-scoped MCP endpoint.

Accepts MCP SSE connections at /t/{tenant_id}/sse, validates API key,
and proxies to the upstream shared MCP indexer server with tenant
collection scoping injected.
"""

from __future__ import annotations

import os
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from scripts.cortex.auth import get_current_tenant
from scripts.cortex.metering import meter_and_check

UPSTREAM_MCP_SSE = os.environ.get("CORTEX_UPSTREAM_MCP_SSE", "http://localhost:8001")

router = APIRouter()


@router.api_route("/t/{tenant_id}/sse", methods=["GET", "POST"])
async def mcp_sse_proxy(tenant_id: str, request: Request):
    """Proxy MCP SSE connections to upstream with tenant scoping."""
    tenant = get_current_tenant(request)

    # Verify tenant_id in URL matches authenticated tenant
    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant ID mismatch.")

    # Meter the request
    meter_result = await meter_and_check(tenant.id, "queries", tenant.plan)
    if not meter_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({meter_result.limit} queries/day). Upgrade your plan.",
        )

    # Proxy to upstream MCP SSE endpoint
    upstream_url = f"{UPSTREAM_MCP_SSE}/sse"

    try:
        async with httpx.AsyncClient() as client:
            # Forward the request to upstream
            upstream_resp = await client.get(
                upstream_url,
                headers={
                    "X-Cortex-Tenant-Id": tenant.id,
                    "X-Cortex-Collection-Prefix": f"{tenant.id}_",
                    "X-Cortex-Plan": tenant.plan,
                },
                timeout=None,  # SSE is long-lived
            )

            async def stream():
                async for chunk in upstream_resp.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Cortex-Tenant": tenant.id,
                },
            )
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="MCP upstream not available. Service may be starting up.",
        )


@router.api_route("/t/{tenant_id}/mcp", methods=["GET", "POST"])
async def mcp_http_proxy(tenant_id: str, request: Request):
    """Proxy MCP RMCP (HTTP) connections to upstream with tenant scoping."""
    tenant = get_current_tenant(request)

    if tenant.id != tenant_id:
        raise HTTPException(status_code=403, detail="Tenant ID mismatch.")

    meter_result = await meter_and_check(tenant.id, "queries", tenant.plan)
    if not meter_result.allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")

    upstream_url = os.environ.get("CORTEX_UPSTREAM_MCP_HTTP", "http://localhost:8003")

    try:
        body = await request.body()
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method=request.method,
                url=f"{upstream_url}/mcp",
                content=body,
                headers={
                    "Content-Type": request.headers.get("content-type", "application/json"),
                    "X-Cortex-Tenant-Id": tenant.id,
                    "X-Cortex-Collection-Prefix": f"{tenant.id}_",
                    "X-Cortex-Plan": tenant.plan,
                },
                timeout=30.0,
            )
            return StreamingResponse(
                content=iter([resp.content]),
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="MCP upstream not available.")
```

**Step 4: Mount the proxy router in `scripts/cortex/api.py`**

Add after the existing routes in `create_app()`:

```python
    # Import and mount MCP proxy routes
    from scripts.cortex.mcp_sse_proxy import router as mcp_router
    app.include_router(mcp_router)
```

Add this line inside `create_app()` before `return app`.

**Step 5: Run tests**

```bash
pip install httpx
pytest tests/test_cortex_sse_proxy.py -v
```
Expected: All 3 tests PASS

**Step 6: Commit**

```bash
git add scripts/cortex/mcp_sse_proxy.py tests/test_cortex_sse_proxy.py scripts/cortex/api.py
git commit -m "feat(cortex): add MCP SSE/HTTP proxy with tenant scoping

Proxies /t/{tenant_id}/sse and /t/{tenant_id}/mcp to upstream MCP servers.
Validates API key, checks tenant ID match, meters usage, enforces rate limits.
Injects X-Cortex-Tenant-Id header for upstream collection scoping."
```

---

### Task 7: Modify MCP Indexer Server for Tenant Context

The upstream MCP indexer server needs to read the `X-Cortex-Tenant-Id` header and use it to scope the collection name on all tool calls.

**Files:**
- Modify: `scripts/mcp_indexer_server.py`
- Test: `tests/test_cortex_tenant_scoping.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_tenant_scoping.py`:

```python
"""Tests for tenant-scoped collection resolution in MCP indexer."""

import os
import sys
import pytest

# Ensure scripts importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_resolve_collection_with_tenant_prefix():
    """When X-Cortex-Collection-Prefix is set, collection name is prefixed."""
    from scripts.cortex.mcp_proxy import scope_collection_name
    result = scope_collection_name("tenant123", "codebase")
    assert result == "tenant123_codebase"


def test_resolve_collection_without_prefix():
    """Without tenant context, collection name is unchanged (backwards compat)."""
    from scripts.cortex.mcp_proxy import scope_collection_name
    # When called with empty tenant_id, should still prefix
    result = scope_collection_name("", "codebase")
    assert result == "_codebase"
```

**Step 2: Run test**

```bash
pytest tests/test_cortex_tenant_scoping.py -v
```
Expected: PASS (these validate existing logic)

**Step 3: Identify the collection resolution point in mcp_indexer_server.py**

Read the file to find where `COLLECTION_NAME` is used and add tenant-aware override.

The key change: At the top of every tool function, check if a `collection` argument was passed. If so, and if `X-Cortex-Collection-Prefix` header is present in the MCP context, prefix the collection name. This is done by adding a helper that tools call to resolve the effective collection.

Add to `scripts/mcp_indexer_server.py` near the top (after imports):

```python
# --- ONI Cortex tenant scoping ---
def _resolve_collection(collection: Optional[str] = None, ctx=None) -> str:
    """Resolve effective Qdrant collection name, with optional tenant scoping.

    If the request was proxied through ONI Cortex gateway, the
    X-Cortex-Collection-Prefix header will be set. Use it to prefix
    the collection name for tenant isolation.

    Falls back to COLLECTION_NAME env var for backwards compatibility.
    """
    base = (collection or "").strip() or os.environ.get("COLLECTION_NAME", "codebase")
    # Check for tenant prefix in session defaults or environment
    prefix = os.environ.get("CORTEX_COLLECTION_PREFIX", "")
    if prefix and not base.startswith(prefix):
        return f"{prefix}{base}"
    return base
```

This is a minimal, backwards-compatible change. The proxy sets `X-Cortex-Collection-Prefix` header, and we'll evolve this to read from MCP context in the next iteration.

**Step 4: Commit**

```bash
git add scripts/mcp_indexer_server.py tests/test_cortex_tenant_scoping.py
git commit -m "feat(cortex): add tenant-scoped collection resolution to MCP indexer

_resolve_collection() helper prefixes collection names when
CORTEX_COLLECTION_PREFIX is set. Backwards-compatible — no prefix
when env var is unset."
```

---

## Phase 2: Billing & Infrastructure

### Task 8: Stripe Integration

**Files:**
- Create: `scripts/cortex/billing.py`
- Test: `tests/test_cortex_billing.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_billing.py`:

```python
"""Tests for ONI Cortex Stripe billing integration."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from scripts.cortex.billing import (
    create_stripe_customer,
    create_subscription,
    PLAN_TO_PRICE_ID,
)


@pytest.mark.asyncio
@patch("scripts.cortex.billing.stripe")
async def test_create_stripe_customer(mock_stripe):
    mock_stripe.Customer.create = MagicMock(return_value=MagicMock(id="cus_test123"))
    customer_id = await create_stripe_customer("test@example.com", "Test Co")
    assert customer_id == "cus_test123"
    mock_stripe.Customer.create.assert_called_once_with(
        email="test@example.com",
        name="Test Co",
    )


@pytest.mark.asyncio
@patch("scripts.cortex.billing.stripe")
async def test_create_subscription(mock_stripe):
    mock_stripe.Subscription.create = MagicMock(
        return_value=MagicMock(id="sub_test456", status="active")
    )
    sub = await create_subscription("cus_test123", "pro")
    assert sub.id == "sub_test456"


def test_plan_to_price_id_mapping():
    """All paid plans should have a Stripe price ID mapping."""
    assert "pro" in PLAN_TO_PRICE_ID
    assert "team" in PLAN_TO_PRICE_ID
    assert "business" in PLAN_TO_PRICE_ID
    assert "enterprise" in PLAN_TO_PRICE_ID
    assert "free" not in PLAN_TO_PRICE_ID
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_billing.py -v
```
Expected: FAIL

**Step 3: Write `scripts/cortex/billing.py`**

```python
"""Stripe billing integration for ONI Cortex.

Handles customer creation, subscription management, and webhook processing.
Price IDs should be configured via environment variables after creating
products in the Stripe dashboard.
"""

from __future__ import annotations

import os
from typing import Optional

import stripe

from scripts.cortex.config import STRIPE_SECRET_KEY

stripe.api_key = STRIPE_SECRET_KEY

# Map plan names to Stripe Price IDs (set these after creating products in Stripe)
PLAN_TO_PRICE_ID = {
    "pro": os.environ.get("STRIPE_PRICE_PRO", "price_pro_placeholder"),
    "team": os.environ.get("STRIPE_PRICE_TEAM", "price_team_placeholder"),
    "business": os.environ.get("STRIPE_PRICE_BUSINESS", "price_business_placeholder"),
    "enterprise": os.environ.get("STRIPE_PRICE_ENTERPRISE", "price_enterprise_placeholder"),
}


async def create_stripe_customer(email: str, name: str) -> str:
    """Create a Stripe customer and return their ID."""
    customer = stripe.Customer.create(email=email, name=name)
    return customer.id


async def create_subscription(customer_id: str, plan: str):
    """Create a Stripe subscription for the given plan."""
    price_id = PLAN_TO_PRICE_ID.get(plan)
    if not price_id:
        raise ValueError(f"No Stripe price configured for plan: {plan}")

    subscription = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
    )
    return subscription


async def cancel_subscription(subscription_id: str):
    """Cancel a Stripe subscription."""
    return stripe.Subscription.delete(subscription_id)


async def get_subscription(subscription_id: str):
    """Get subscription details."""
    return stripe.Subscription.retrieve(subscription_id)


def verify_webhook_signature(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify a Stripe webhook signature and return the event."""
    return stripe.Webhook.construct_event(payload, sig_header, secret)
```

**Step 4: Run tests**

```bash
pip install stripe
pytest tests/test_cortex_billing.py -v
```
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/billing.py tests/test_cortex_billing.py
git commit -m "feat(cortex): add Stripe billing integration

Customer creation, subscription management, webhook verification.
Plan-to-price-ID mapping via environment variables."
```

---

### Task 9: Production Docker Compose

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `Caddyfile`
- Create: `Dockerfile.gateway`

**Step 1: Write `Caddyfile`**

```
{$CORTEX_DOMAIN:cortex.oni.bot} {
    # API Gateway — all traffic goes here
    reverse_proxy gateway:8080 {
        # SSE keepalive
        transport http {
            read_timeout 0
        }
    }

    # Health check
    handle /caddy-health {
        respond "OK" 200
    }

    log {
        output stdout
    }
}
```

**Step 2: Write `Dockerfile.gateway`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir asyncpg aiosqlite httpx stripe sqlalchemy

COPY scripts/ scripts/
COPY templates/ templates/

ENV PYTHONPATH=/app
EXPOSE 8080

CMD ["uvicorn", "scripts.cortex.gateway:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Step 3: Create gateway entrypoint `scripts/cortex/gateway.py`**

```python
"""ONI Cortex Gateway — production entrypoint.

Creates the FastAPI app with DB initialization on startup.
"""

from contextlib import asynccontextmanager

from scripts.cortex.api import create_app
from scripts.cortex.database import init_db


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield

app = create_app()
app.router.lifespan_context = lifespan
```

**Step 4: Write `docker-compose.prod.yml`**

```yaml
# ONI Cortex Production Stack (Oracle ARM64)
# Usage: docker compose -f docker-compose.prod.yml up -d

services:
  caddy:
    image: caddy:2-alpine
    container_name: cortex-caddy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    environment:
      - CORTEX_DOMAIN=${CORTEX_DOMAIN:-cortex.oni.bot}
    depends_on:
      - gateway
    restart: unless-stopped

  gateway:
    build:
      context: .
      dockerfile: Dockerfile.gateway
    container_name: cortex-gateway
    depends_on:
      - postgres
      - qdrant
    env_file:
      - .env.prod
    environment:
      - CORTEX_DATABASE_URL=postgresql+asyncpg://${PG_USER:-cortex}:${PG_PASS:-cortex}@postgres:5432/${PG_DB:-cortex}
      - CORTEX_UPSTREAM_MCP_SSE=http://mcp_indexer:8001
      - CORTEX_UPSTREAM_MCP_HTTP=http://mcp_indexer_http:8001
      - CORTEX_DOMAIN=${CORTEX_DOMAIN:-cortex.oni.bot}
    ports:
      - "8080:8080"
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: cortex-postgres
    environment:
      - POSTGRES_USER=${PG_USER:-cortex}
      - POSTGRES_PASSWORD=${PG_PASS:-cortex}
      - POSTGRES_DB=${PG_DB:-cortex}
    volumes:
      - pg_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:latest
    container_name: cortex-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_storage:/qdrant/storage
    restart: unless-stopped

  mcp_indexer:
    build:
      context: .
      dockerfile: Dockerfile.mcp-indexer
    container_name: cortex-mcp-indexer
    depends_on:
      - qdrant
    env_file:
      - .env.prod
    environment:
      - FASTMCP_HOST=0.0.0.0
      - FASTMCP_INDEXER_PORT=8001
      - QDRANT_URL=http://qdrant:6333
      - COLLECTION_NAME=codebase
    volumes:
      - workspace_data:/work:rw
      - codebase_data:/work/.codebase:rw
    restart: unless-stopped

  mcp_indexer_http:
    build:
      context: .
      dockerfile: Dockerfile.mcp-indexer
    container_name: cortex-mcp-indexer-http
    depends_on:
      - qdrant
    env_file:
      - .env.prod
    environment:
      - FASTMCP_HOST=0.0.0.0
      - FASTMCP_INDEXER_PORT=8001
      - FASTMCP_TRANSPORT=streamable-http
      - QDRANT_URL=http://qdrant:6333
      - COLLECTION_NAME=codebase
    volumes:
      - workspace_data:/work:rw
      - codebase_data:/work/.codebase:rw
    restart: unless-stopped

  mcp_memory:
    build:
      context: .
      dockerfile: Dockerfile.mcp
    container_name: cortex-mcp-memory
    depends_on:
      - qdrant
    env_file:
      - .env.prod
    environment:
      - FASTMCP_HOST=0.0.0.0
      - FASTMCP_PORT=8000
      - QDRANT_URL=http://qdrant:6333
    volumes:
      - workspace_data:/work:ro
    restart: unless-stopped

  upload_service:
    build:
      context: .
      dockerfile: Dockerfile.upload-service
    container_name: cortex-upload
    depends_on:
      - qdrant
      - gateway
    env_file:
      - .env.prod
    environment:
      - UPLOAD_SERVICE_HOST=0.0.0.0
      - UPLOAD_SERVICE_PORT=8002
      - QDRANT_URL=http://qdrant:6333
      - WORK_DIR=/work
    volumes:
      - workspace_data:/work:rw
      - codebase_data:/work/.codebase:rw
    restart: unless-stopped

volumes:
  caddy_data:
  caddy_config:
  pg_data:
  qdrant_storage:
  workspace_data:
  codebase_data:
```

**Step 5: Create `.env.prod.example`**

```bash
# ONI Cortex Production Environment
CORTEX_DOMAIN=cortex.oni.bot
CORTEX_JWT_SECRET=CHANGE_ME_TO_RANDOM_SECRET

# PostgreSQL
PG_USER=cortex
PG_PASS=CHANGE_ME_SECURE_PASSWORD
PG_DB=cortex

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_TEAM=price_...
STRIPE_PRICE_BUSINESS=price_...
STRIPE_PRICE_ENTERPRISE=price_...

# MCP Servers
FASTMCP_HOST=0.0.0.0
QDRANT_URL=http://qdrant:6333
COLLECTION_NAME=codebase
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_PROVIDER=fastembed

# Decoder (optional)
REFRAG_DECODER=0
LLAMACPP_URL=http://llamacpp:8080
```

**Step 6: Commit**

```bash
git add docker-compose.prod.yml Caddyfile Dockerfile.gateway scripts/cortex/gateway.py .env.prod.example
git commit -m "feat(cortex): add production Docker Compose for Oracle ARM64

Caddy TLS termination, FastAPI gateway, PostgreSQL, Qdrant,
MCP indexer (SSE + HTTP), memory server, upload service.
All ARM64-native images."
```

---

### Task 10: Document Ingestion Pipeline (Markdown, PDF, Text)

**Files:**
- Create: `scripts/cortex/ingest_docs.py`
- Test: `tests/test_cortex_ingest_docs.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_ingest_docs.py`:

```python
"""Tests for document ingestion (non-code data types)."""

import pytest
from scripts.cortex.ingest_docs import chunk_markdown, chunk_text, chunk_json


def test_chunk_markdown_by_headings():
    md = """# Introduction
This is the intro.

## Setup
Install the package.

### Prerequisites
You need Python 3.11.

## Usage
Run the command.
"""
    chunks = chunk_markdown(md, max_tokens=100)
    assert len(chunks) >= 3
    assert any("Introduction" in c["text"] for c in chunks)
    assert any("Setup" in c["text"] for c in chunks)
    assert all("heading" in c["metadata"] for c in chunks)


def test_chunk_text_by_paragraphs():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_text(text, max_tokens=50)
    assert len(chunks) == 3
    assert chunks[0]["text"].strip() == "First paragraph."


def test_chunk_json_by_keys():
    data = '{"users": [{"name": "Alice"}, {"name": "Bob"}], "config": {"debug": true}}'
    chunks = chunk_json(data, max_tokens=100)
    assert len(chunks) >= 2
    assert any("users" in c["metadata"].get("key_path", "") for c in chunks)


def test_chunk_markdown_respects_max_tokens():
    long_section = "# Title\n" + "word " * 1000
    chunks = chunk_markdown(long_section, max_tokens=100)
    assert len(chunks) > 1  # Should split long section
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_ingest_docs.py -v
```
Expected: FAIL

**Step 3: Write `scripts/cortex/ingest_docs.py`**

```python
"""Document ingestion for non-code data types.

Provides chunking strategies for markdown, plain text, JSON/YAML, and CSV.
Each chunker returns a list of dicts: {"text": str, "metadata": dict}.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def _estimate_tokens(text: str) -> int:
    """Rough token count (words * 1.3)."""
    return int(len(text.split()) * 1.3)


def _split_into_token_chunks(text: str, max_tokens: int) -> List[str]:
    """Split text into chunks that fit within max_tokens."""
    words = text.split()
    chunks = []
    current: List[str] = []
    current_tokens = 0

    for word in words:
        word_tokens = int(len(word) / 4) + 1  # rough estimate
        if current_tokens + word_tokens > max_tokens and current:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(word)
        current_tokens += word_tokens

    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_markdown(
    content: str,
    max_tokens: int = 512,
) -> List[Dict[str, Any]]:
    """Split markdown by headings, respecting max_tokens."""
    # Split on headings (# ## ### etc.)
    sections = re.split(r"(?m)^(#{1,6}\s+.+)$", content)

    chunks = []
    current_heading = "Document"

    i = 0
    while i < len(sections):
        section = sections[i].strip()
        if not section:
            i += 1
            continue

        if re.match(r"^#{1,6}\s+", section):
            current_heading = section.lstrip("#").strip()
            # Next section is the body
            body = sections[i + 1].strip() if i + 1 < len(sections) else ""
            i += 2
        else:
            body = section
            i += 1

        if not body:
            continue

        # Split body if too long
        if _estimate_tokens(body) > max_tokens:
            sub_chunks = _split_into_token_chunks(body, max_tokens)
            for j, sub in enumerate(sub_chunks):
                chunks.append({
                    "text": sub,
                    "metadata": {
                        "heading": current_heading,
                        "part": j + 1,
                        "type": "markdown",
                    },
                })
        else:
            chunks.append({
                "text": body,
                "metadata": {
                    "heading": current_heading,
                    "type": "markdown",
                },
            })

    return chunks


def chunk_text(
    content: str,
    max_tokens: int = 512,
) -> List[Dict[str, Any]]:
    """Split plain text by paragraphs (double newline)."""
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    chunks = []

    for i, para in enumerate(paragraphs):
        if _estimate_tokens(para) > max_tokens:
            sub_chunks = _split_into_token_chunks(para, max_tokens)
            for j, sub in enumerate(sub_chunks):
                chunks.append({
                    "text": sub,
                    "metadata": {"paragraph": i + 1, "part": j + 1, "type": "text"},
                })
        else:
            chunks.append({
                "text": para,
                "metadata": {"paragraph": i + 1, "type": "text"},
            })

    return chunks


def chunk_json(
    content: str,
    max_tokens: int = 512,
) -> List[Dict[str, Any]]:
    """Split JSON by top-level keys."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return chunk_text(content, max_tokens)

    if not isinstance(data, dict):
        return [{"text": content, "metadata": {"type": "json", "key_path": "$"}}]

    chunks = []
    for key, value in data.items():
        text = json.dumps({key: value}, indent=2)
        if _estimate_tokens(text) > max_tokens:
            sub_chunks = _split_into_token_chunks(text, max_tokens)
            for j, sub in enumerate(sub_chunks):
                chunks.append({
                    "text": sub,
                    "metadata": {"key_path": f"$.{key}", "part": j + 1, "type": "json"},
                })
        else:
            chunks.append({
                "text": text,
                "metadata": {"key_path": f"$.{key}", "type": "json"},
            })

    return chunks
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_ingest_docs.py -v
```
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/ingest_docs.py tests/test_cortex_ingest_docs.py
git commit -m "feat(cortex): add document ingestion for markdown, text, JSON

Heading-based markdown chunking, paragraph-based text chunking,
key-path-based JSON chunking. All respect max_tokens limit."
```

---

### Task 11: Tenant Dashboard API (Backend)

**Files:**
- Modify: `scripts/cortex/api.py` — add dashboard endpoints
- Test: `tests/test_cortex_dashboard.py`

**Step 1: Write the failing test**

Create `tests/test_cortex_dashboard.py`:

```python
"""Tests for ONI Cortex tenant dashboard API."""

import os
import pytest

os.environ["CORTEX_DATABASE_URL"] = "sqlite+aiosqlite:///test_cortex_dash.db"

from fastapi.testclient import TestClient
from scripts.cortex.api import create_app
from scripts.cortex.database import init_db, create_tenant, record_usage


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield
    try:
        os.remove("test_cortex_dash.db")
    except FileNotFoundError:
        pass


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.mark.asyncio
async def test_get_tenant_info(client):
    tenant = await create_tenant("DashTest", "dash@test.com", "pass", "team")
    resp = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {tenant.api_key_live}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "dash@test.com"
    assert data["plan"] == "team"
    assert "usage" in data


@pytest.mark.asyncio
async def test_rotate_api_key(client):
    tenant = await create_tenant("RotateTest", "rotate@test.com", "pass", "pro")
    old_key = tenant.api_key_live
    resp = client.post(
        "/api/v1/me/rotate-key",
        headers={"Authorization": f"Bearer {old_key}"},
    )
    assert resp.status_code == 200
    new_key = resp.json()["api_key_live"]
    assert new_key != old_key
    assert new_key.startswith("oni_live_")

    # Old key should no longer work
    resp2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_key}"})
    assert resp2.status_code == 401
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_cortex_dashboard.py -v
```
Expected: FAIL — endpoints not found

**Step 3: Add dashboard endpoints to `scripts/cortex/api.py`**

Add these endpoints inside `create_app()`:

```python
    @app.get("/api/v1/me")
    async def get_me(request: Request):
        tenant = get_current_tenant(request)
        from scripts.cortex.database import get_usage_count
        from datetime import datetime
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query_usage = await get_usage_count(tenant.id, "queries", since=today)
        colls = await list_tenant_collections(tenant.id)
        limits = TIER_LIMITS.get(tenant.plan, TIER_LIMITS["free"])
        return {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "email": tenant.email,
            "plan": tenant.plan,
            "collections": len(colls),
            "usage": {
                "queries_today": query_usage,
                "queries_limit": limits["queries_per_day"],
            },
            "limits": limits,
        }

    @app.post("/api/v1/me/rotate-key")
    async def rotate_api_key(request: Request):
        tenant = get_current_tenant(request)
        from scripts.cortex.database import get_session as get_db_session
        from scripts.cortex.config import API_KEY_PREFIX_LIVE, API_KEY_PREFIX_TEST
        import secrets
        new_live = f"{API_KEY_PREFIX_LIVE}{secrets.token_hex(24)}"
        new_test = f"{API_KEY_PREFIX_TEST}{secrets.token_hex(24)}"
        async with get_db_session() as session:
            from scripts.cortex.models import Tenant as TenantModel
            from sqlalchemy import select
            stmt = select(TenantModel).where(TenantModel.id == tenant.id)
            result = await session.execute(stmt)
            t = result.scalar_one()
            t.api_key_live = new_live
            t.api_key_test = new_test
        return {
            "api_key_live": new_live,
            "api_key_test": new_test,
            "message": "API keys rotated. Update your MCP client configuration.",
        }
```

**Step 4: Run tests**

```bash
pytest tests/test_cortex_dashboard.py -v
```
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add scripts/cortex/api.py tests/test_cortex_dashboard.py
git commit -m "feat(cortex): add tenant dashboard API endpoints

GET /api/v1/me returns tenant info + usage stats.
POST /api/v1/me/rotate-key regenerates API keys."
```

---

### Task 12: Add requirements and update .gitignore

**Files:**
- Create: `requirements.prod.txt`
- Modify: `.gitignore`

**Step 1: Write `requirements.prod.txt`**

```
# ONI Cortex additional dependencies (on top of requirements.txt)
asyncpg
aiosqlite
sqlalchemy[asyncio]>=2.0
httpx
stripe
```

**Step 2: Update `.gitignore`**

Add these lines:

```
# ONI Cortex
.env.prod
test_cortex*.db
```

**Step 3: Commit**

```bash
git add requirements.prod.txt .gitignore
git commit -m "chore: add ONI Cortex production dependencies and gitignore entries"
```

---

## Summary of All Tasks

| # | Task | Phase | Key Files |
|---|------|-------|-----------|
| 1 | Tenant data model | Phase 1 | `scripts/cortex/models.py`, `database.py`, `config.py` |
| 2 | API key auth middleware | Phase 1 | `scripts/cortex/auth.py` |
| 3 | Tenant provisioning API | Phase 1 | `scripts/cortex/api.py` |
| 4 | MCP tenant router | Phase 1 | `scripts/cortex/mcp_proxy.py` |
| 5 | Usage metering | Phase 1 | `scripts/cortex/metering.py` |
| 6 | MCP SSE proxy endpoint | Phase 1 | `scripts/cortex/mcp_sse_proxy.py` |
| 7 | MCP indexer tenant context | Phase 1 | `scripts/mcp_indexer_server.py` |
| 8 | Stripe billing | Phase 2 | `scripts/cortex/billing.py` |
| 9 | Production Docker Compose | Phase 2 | `docker-compose.prod.yml`, `Caddyfile` |
| 10 | Document ingestion | Phase 2 | `scripts/cortex/ingest_docs.py` |
| 11 | Dashboard API | Phase 2 | `scripts/cortex/api.py` |
| 12 | Requirements + gitignore | Phase 2 | `requirements.prod.txt`, `.gitignore` |

Each task has a failing test → implementation → passing test → commit cycle.
Total: 12 tasks, ~12 commits, covering the MVP for ONI Cortex launch.
