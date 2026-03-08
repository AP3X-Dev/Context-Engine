"""API key authentication middleware for ONI Cortex."""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from scripts.cortex.database import get_tenant_by_api_key
from scripts.cortex.models import Tenant

# Paths that bypass authentication
PUBLIC_PATHS = {
    "/health",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/api/v1/auth/signup",
    "/api/v1/auth/login",
}


class CortexAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that authenticates requests via API key.

    The API key can be provided in two ways:
    1. Authorization header: ``Authorization: Bearer <key>``
    2. Query parameter: ``?key=<key>``

    On success the looked-up :class:`Tenant` is attached to
    ``request.state.tenant``.  Public paths listed in :data:`PUBLIC_PATHS`
    are allowed through without authentication.
    """

    async def dispatch(self, request: Request, call_next):
        # Allow public paths through without auth
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract API key from header or query param
        api_key = _extract_api_key(request)
        if api_key is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing API key"},
            )

        # Look up tenant
        tenant = await get_tenant_by_api_key(api_key)
        if tenant is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API key"},
            )

        # Attach tenant to request state
        request.state.tenant = tenant
        return await call_next(request)


def _extract_api_key(request: Request) -> str | None:
    """Return the API key from the Authorization header or ``key`` query param."""
    # Try Authorization header first
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    # Fall back to query parameter
    key_param = request.query_params.get("key")
    if key_param:
        return key_param

    return None


def get_current_tenant(request: Request) -> Tenant:
    """Retrieve the authenticated tenant from ``request.state``.

    Raises :class:`AttributeError` if the middleware has not run or the
    request was not authenticated.
    """
    return request.state.tenant
