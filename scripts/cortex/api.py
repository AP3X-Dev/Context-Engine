"""FastAPI application for ONI Cortex tenant provisioning and collection management."""

import secrets
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from scripts.cortex import config
from scripts.cortex.auth import CortexAuthMiddleware, get_current_tenant
from scripts.cortex.database import (
    create_collection_for_tenant,
    create_tenant,
    get_session,
    get_tenant_by_email,
    get_usage_count,
    list_tenant_collections,
)
from scripts.cortex.models import Tenant


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
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
    data_type: str | None
    vector_count: int
    qdrant_collection: str


class MeResponse(BaseModel):
    tenant_id: str
    name: str
    email: str
    plan: str
    collections: int
    usage: dict
    limits: dict


class RotateKeyResponse(BaseModel):
    api_key_live: str
    api_key_test: str
    message: str


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Create and configure the ONI Cortex FastAPI application."""
    app = FastAPI(title="ONI Cortex", version="0.1.0")
    app.add_middleware(CortexAuthMiddleware)

    # ----- Health -----

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "oni-cortex"}

    # ----- Signup -----

    @app.post("/api/v1/auth/signup", status_code=201, response_model=SignupResponse)
    async def signup(body: SignupRequest):
        # Validate plan
        if body.plan not in config.TIER_LIMITS:
            raise HTTPException(status_code=400, detail=f"Invalid plan: {body.plan}")

        # Check duplicate email
        existing = await get_tenant_by_email(body.email)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")

        # Create tenant
        tenant = await create_tenant(
            name=body.name,
            email=body.email,
            password=body.password,
            plan=body.plan,
        )

        # Create default collection
        await create_collection_for_tenant(
            tenant_id=tenant.id,
            collection_name="default",
            data_type="code",
        )

        mcp_url = f"https://{config.CORTEX_DOMAIN}/t/{tenant.id}/sse"

        return SignupResponse(
            tenant_id=tenant.id,
            name=tenant.name,
            email=tenant.email,
            plan=tenant.plan,
            api_key_live=tenant.api_key_live,
            api_key_test=tenant.api_key_test,
            mcp_url=mcp_url,
        )

    # ----- Collections -----

    @app.post("/api/v1/collections", status_code=201, response_model=CollectionResponse)
    async def create_collection(body: CreateCollectionRequest, request: Request):
        tenant = get_current_tenant(request)

        # Check tier collection limit
        existing_collections = await list_tenant_collections(tenant.id)
        tier_limit = config.TIER_LIMITS[tenant.plan]["collections"]
        if tier_limit != -1 and len(existing_collections) >= tier_limit:
            raise HTTPException(
                status_code=403,
                detail="Collection limit reached for your plan",
            )

        collection = await create_collection_for_tenant(
            tenant_id=tenant.id,
            collection_name=body.collection_name,
            data_type=body.data_type,
        )

        return CollectionResponse(
            id=collection.id,
            collection_name=collection.collection_name,
            data_type=collection.data_type,
            vector_count=collection.vector_count,
            qdrant_collection=f"{tenant.id}_{collection.collection_name}",
        )

    @app.get("/api/v1/collections", response_model=list[CollectionResponse])
    async def list_collections(request: Request):
        tenant = get_current_tenant(request)
        collections = await list_tenant_collections(tenant.id)
        return [
            CollectionResponse(
                id=c.id,
                collection_name=c.collection_name,
                data_type=c.data_type,
                vector_count=c.vector_count,
                qdrant_collection=f"{tenant.id}_{c.collection_name}",
            )
            for c in collections
        ]

    # ----- Me -----

    @app.get("/api/v1/me", response_model=MeResponse)
    async def get_me(request: Request):
        tenant = get_current_tenant(request)
        collections = await list_tenant_collections(tenant.id)

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        queries_today = await get_usage_count(
            tenant_id=tenant.id, metric="query", since=today_start
        )

        limits = config.TIER_LIMITS[tenant.plan]

        return MeResponse(
            tenant_id=tenant.id,
            name=tenant.name,
            email=tenant.email,
            plan=tenant.plan,
            collections=len(collections),
            usage={
                "queries_today": queries_today,
                "queries_limit": limits["queries_per_day"],
            },
            limits=limits,
        )

    # ----- Rotate key -----

    @app.post("/api/v1/me/rotate-key", response_model=RotateKeyResponse)
    async def rotate_key(request: Request):
        tenant = get_current_tenant(request)

        new_live = config.API_KEY_PREFIX_LIVE + secrets.token_hex(24)
        new_test = config.API_KEY_PREFIX_TEST + secrets.token_hex(24)

        async with get_session() as session:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant.id)
            )
            db_tenant = result.scalar_one()
            db_tenant.api_key_live = new_live
            db_tenant.api_key_test = new_test

        return RotateKeyResponse(
            api_key_live=new_live,
            api_key_test=new_test,
            message="API keys rotated successfully",
        )

    return app
