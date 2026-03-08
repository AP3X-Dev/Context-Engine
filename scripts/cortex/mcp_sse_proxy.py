"""MCP SSE/HTTP proxy endpoints for ONI Cortex.

Authenticates tenants, enforces rate limits, and forwards requests to
upstream MCP servers with tenant-scoping headers injected.
"""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from scripts.cortex.auth import get_current_tenant
from scripts.cortex.metering import meter_and_check

CORTEX_UPSTREAM_MCP_SSE = os.environ.get(
    "CORTEX_UPSTREAM_MCP_SSE", "http://localhost:8001"
)
CORTEX_UPSTREAM_MCP_HTTP = os.environ.get(
    "CORTEX_UPSTREAM_MCP_HTTP", "http://localhost:8003"
)

router = APIRouter()


def _tenant_headers(tenant_id: str, plan: str) -> dict[str, str]:
    """Build the tenant-scoping headers forwarded to upstream MCP."""
    return {
        "X-Cortex-Tenant-Id": tenant_id,
        "X-Cortex-Collection-Prefix": f"{tenant_id}_",
        "X-Cortex-Plan": plan,
    }


async def _check_tenant_and_meter(
    request: Request, tenant_id: str
) -> JSONResponse | None:
    """Validate tenant identity and enforce rate limits.

    Returns a ``JSONResponse`` error if something is wrong, or ``None`` on
    success (caller should proceed with the proxy).
    """
    tenant = get_current_tenant(request)

    # Tenant in URL must match authenticated tenant
    if tenant.id != tenant_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Tenant ID mismatch"},
        )

    # Rate-limit check
    result = await meter_and_check(tenant.id, "queries", tenant.plan)
    if not result.allowed:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "current": result.current,
                "limit": result.limit,
            },
        )

    return None


# --------------------------------------------------------------------------- #
# SSE proxy
# --------------------------------------------------------------------------- #


@router.api_route("/t/{tenant_id}/sse", methods=["GET", "POST"])
async def sse_proxy(request: Request, tenant_id: str):
    """Proxy SSE traffic to the upstream MCP SSE server."""
    error = await _check_tenant_and_meter(request, tenant_id)
    if error is not None:
        return error

    tenant = get_current_tenant(request)
    upstream_url = f"{CORTEX_UPSTREAM_MCP_SSE}/sse"
    headers = _tenant_headers(tenant.id, tenant.plan)

    try:
        client = httpx.AsyncClient(timeout=None)
        req = client.build_request("GET", upstream_url, headers=headers)
        resp = await client.send(req, stream=True)

        async def _stream():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            status_code=resp.status_code,
        )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Upstream MCP SSE server unavailable"},
        )


# --------------------------------------------------------------------------- #
# HTTP / RMCP proxy
# --------------------------------------------------------------------------- #


@router.api_route("/t/{tenant_id}/mcp", methods=["GET", "POST"])
async def mcp_proxy(request: Request, tenant_id: str):
    """Proxy HTTP/RMCP traffic to the upstream MCP HTTP server."""
    error = await _check_tenant_and_meter(request, tenant_id)
    if error is not None:
        return error

    tenant = get_current_tenant(request)
    upstream_url = f"{CORTEX_UPSTREAM_MCP_HTTP}/mcp"
    headers = _tenant_headers(tenant.id, tenant.plan)

    # Forward content-type if present
    content_type = request.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type

    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                content=body,
            )
            return JSONResponse(
                status_code=resp.status_code,
                content=resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text},
            )
    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={"detail": "Upstream MCP HTTP server unavailable"},
        )
