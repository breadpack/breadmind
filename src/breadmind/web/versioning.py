"""API versioning support for BreadMind web application.

Provides version-prefixed routing (/api/v1/...) with backward compatibility
for legacy /api/... paths via automatic redirection.
"""
from __future__ import annotations

import re
from enum import Enum

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse


class APIVersion(str, Enum):
    """Supported API versions."""

    V1 = "v1"
    V2 = "v2"


# Versions currently active and accepting traffic.
ACTIVE_VERSIONS: list[APIVersion] = [APIVersion.V1]

# The default version that legacy (un-versioned) requests are redirected to.
DEFAULT_VERSION: APIVersion = APIVersion.V1

# Path prefixes that must NOT be rewritten or redirected.
_PASSTHROUGH_PREFIXES = (
    "/health",
    "/metrics",
    "/ws/",
    "/static/",
    "/credential-input/",
    "/docs",
    "/openapi.json",
    "/redoc",
)

# Matches /api/v<N>/... to extract the version tag.
_VERSIONED_API_RE = re.compile(r"^/api/(v\d+)(/.*)?$")

# Matches bare /api/... that is NOT already versioned and NOT /api/versions.
_LEGACY_API_RE = re.compile(r"^/api/(?!v\d+/)(?!versions(?:/|$))(.*)$")


def create_versioned_router(version: APIVersion) -> APIRouter:
    """Create an APIRouter scoped to a specific API version.

    The returned router carries the version prefix ``/api/{version}``.
    """
    return APIRouter(prefix=f"/api/{version.value}")


def setup_versioning(app: FastAPI) -> None:
    """Install the versioning middleware and ``/api/versions`` endpoint.

    This should be called **after** all route modules have been registered so
    that the rewrite middleware can forward versioned paths to the existing
    ``/api/...`` handlers.
    """

    # --- /api/versions discovery endpoint (not versioned itself) ---
    @app.get("/api/versions", tags=["versioning"])
    async def list_api_versions():
        """Return the list of available API versions."""
        return JSONResponse(content={
            "versions": [v.value for v in ACTIVE_VERSIONS],
            "default": DEFAULT_VERSION.value,
        })

    # --- Versioning middleware ---

    @app.middleware("http")
    async def api_versioning_middleware(request: Request, call_next):
        path = request.scope["path"]

        # 1. Pass-through paths that should never be touched.
        for prefix in _PASSTHROUGH_PREFIXES:
            if path == prefix or path.startswith(prefix):
                return await call_next(request)

        # 2. /api/versions is served directly (registered above).
        if path == "/api/versions" or path == "/api/versions/":
            return await call_next(request)

        # 3. Versioned request  /api/v1/...  -> rewrite scope to /api/...
        m = _VERSIONED_API_RE.match(path)
        if m:
            version_tag = m.group(1)
            # Validate version is active.
            if version_tag not in {v.value for v in ACTIVE_VERSIONS}:
                return JSONResponse(
                    status_code=404,
                    content={"error": f"API version '{version_tag}' is not available."},
                )
            rest = m.group(2) or ""
            # Rewrite the path so existing /api/... handlers match.
            request.scope["path"] = f"/api{rest}"
            return await call_next(request)

        # 4. Legacy un-versioned /api/... -> redirect to /api/v1/...
        m = _LEGACY_API_RE.match(path)
        if m:
            rest = m.group(1)
            query = request.scope.get("query_string", b"")
            new_path = f"/api/{DEFAULT_VERSION.value}/{rest}"
            if query:
                new_path += f"?{query.decode('latin-1')}"
            return RedirectResponse(url=new_path, status_code=307)

        # 5. Everything else (/, /static, /ws, etc.) passes through.
        return await call_next(request)
