import asyncio
import json
import logging
import time
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Callable

from breadmind.core.metrics import get_metrics_registry, normalize_path

from breadmind.web.context import AppContext
from breadmind.web.idempotency import setup_idempotency
from breadmind.web.rate_limiter import RateLimiter
from breadmind.web.versioning import setup_versioning
from breadmind.web.routes import (
    setup_chat_routes,
    setup_config_routes,
    setup_container_routes,
    setup_tools_routes,
    setup_mcp_routes,
    setup_monitoring_routes,
    setup_scheduler_routes,
    setup_subagent_routes,
    setup_swarm_routes,
    setup_system_routes,
)
from breadmind.web.routes.messenger import setup_messenger_routes
from breadmind.web.routes.settings import setup_settings_routes
from breadmind.web.routes.integrations import router as integrations_router
from breadmind.web.routes.oauth import router as oauth_router
from breadmind.web.routes.infrastructure import router as infra_router
from breadmind.web.routes.personal import router as personal_router
from breadmind.web.routes.workers import setup_worker_routes
from breadmind.web.routes.credential_input import setup_credential_input_routes
from breadmind.web.routes.bg_jobs import setup_bg_job_routes
from breadmind.web.routes.coding_jobs import register_coding_job_routes
from breadmind.web.routes.plugins import router as plugins_router
from breadmind.web.routes.upload import router as upload_router
from breadmind.web.routes.export import setup_export_routes
from breadmind.web.routes.backup import setup_backup_routes

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, ctx: AppContext | None = None, **kwargs):
        # Support both new (ctx) and legacy (kwargs) initialization
        if ctx is None:
            ctx = AppContext(**kwargs)
        self.ctx = ctx

        try:
            from importlib.metadata import version as _pkg_ver
            _version = _pkg_ver("breadmind")
        except Exception:
            _version = "0.0.0"
        self.app = FastAPI(title="BreadMind", version=_version)
        # Expose self via FastAPI state so Depends() helpers can reach it
        self.app.state.app_state = self
        self._marketplace = None

        # CORS middleware
        config = self._config
        if config and hasattr(config, 'security'):
            origins = config.security.cors_origins
        else:
            origins = ["http://localhost:8080", "http://127.0.0.1:8080"]
        # Support BREADMIND_CORS_ORIGINS env var override
        import os as _os
        env_cors = _os.environ.get("BREADMIND_CORS_ORIGINS")
        if env_cors:
            origins = [o.strip() for o in env_cors.split(",") if o.strip()]
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        )

        self._connections: list[WebSocket] = []
        self._events: list[dict] = []
        self._lock = asyncio.Lock()
        self._setup_routes()

        # Wire BehaviorTracker broadcast to push updates to Settings UI
        if self._agent and hasattr(self._agent, '_behavior_tracker'):
            tracker = self._agent._behavior_tracker
            if tracker is not None:
                tracker._on_prompt_updated = self._on_behavior_prompt_updated

        # Restore swarm roles from DB on startup
        @self.app.on_event("startup")
        async def _restore_swarm_roles():
            if self._swarm_manager and self._db:
                try:
                    roles_data = await self._db.get_setting("swarm_roles")
                    if roles_data:
                        self._swarm_manager.import_roles(roles_data)
                except Exception:
                    pass

    # ── Backward-compatible attribute proxy to self.ctx ─────────────────
    # Routes and dependency helpers access ``app_state._field``; this
    # mapping keeps that contract intact while the real data lives in ctx.
    _CTX_ATTR_MAP: dict[str, str] = {
        "_message_handler": "message_handler",
        "_tool_registry": "tool_registry",
        "_mcp_manager": "mcp_manager",
        "_config": "config",
        "_monitoring_engine": "monitoring_engine",
        "_safety_config": "safety_config",
        "_agent": "agent",
        "_audit_logger": "audit_logger",
        "_metrics_collector": "metrics_collector",
        "_db": "database",
        "_mcp_store": "mcp_store",
        "_safety_guard": "safety_guard",
        "_working_memory": "working_memory",
        "_message_router": "message_router",
        "_scheduler": "scheduler",
        "_subagent_manager": "subagent_manager",
        "_webhook_manager": "webhook_manager",
        "_auth": "auth",
        "_container_executor": "container_executor",
        "_swarm_manager": "swarm_manager",
        "_skill_store": "skill_store",
        "_performance_tracker": "performance_tracker",
        "_search_engine": "search_engine",
        "_token_manager": "token_manager",
        "_commander": "commander",
        "_messenger_security": "messenger_security",
        "_lifecycle_manager": "lifecycle_manager",
        "_orchestrator": "orchestrator",
        "_bg_job_manager": "bg_job_manager",
        "_embedding_service": "embedding_service",
        "_plugin_mgr": "plugin_mgr",
    }

    def __getattr__(self, name: str):
        ctx_field = WebApp._CTX_ATTR_MAP.get(name)
        if ctx_field is not None:
            return getattr(self.ctx, ctx_field)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name: str, value):
        ctx_field = WebApp._CTX_ATTR_MAP.get(name)
        if ctx_field is not None:
            setattr(self.ctx, ctx_field, value)
        else:
            super().__setattr__(name, value)

    async def _on_behavior_prompt_updated(self, new_prompt: str, reason: str):
        """Broadcast behavior prompt update to connected WebSocket clients."""
        await self.broadcast_event({
            "type": "behavior_prompt_updated",
            "prompt": new_prompt,
            "reason": reason,
        })

    async def on_monitoring_event(self, event):
        """Called by monitoring engine when an event occurs."""
        event_dict = {
            "source": event.source,
            "target": event.target,
            "severity": event.severity,
            "condition": event.condition,
            "details": event.details,
            "timestamp": event.timestamp.isoformat(),
        }
        self._events.append(event_dict)
        # Keep last 100 events
        if len(self._events) > 100:
            self._events = self._events[-100:]
        # Broadcast to connected WebSocket clients
        await self.broadcast_event(event_dict)

    async def broadcast_event(self, event_dict):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "monitoring_event", "event": event_dict}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)

    def _setup_routes(self):
        app = self.app
        rate_limiter = RateLimiter()

        # Middleware registration order: first registered = innermost.
        # Execution order (outermost → innermost):
        #   HTTPS enforce → Rate limit → Security headers → Auth → Metrics → Idempotency → handler

        # --- Idempotency middleware (innermost – registered first) ---
        setup_idempotency(app)

        # --- Metrics collection middleware ---

        _metrics_registry = get_metrics_registry()
        _active_connections_count = 0
        _active_lock = asyncio.Lock()

        @app.middleware("http")
        async def metrics_middleware(request: Request, call_next):
            nonlocal _active_connections_count
            path = request.url.path
            method = request.method

            # Skip metrics collection for the /metrics endpoint itself and static files
            if path == "/metrics" or path.startswith("/static/"):
                return await call_next(request)

            async with _active_lock:
                _active_connections_count += 1
            _metrics_registry.gauge(
                "breadmind_active_connections",
                "Currently active HTTP connections",
                value=_active_connections_count,
            )

            start = time.perf_counter()
            try:
                response = await call_next(request)
            finally:
                duration = time.perf_counter() - start
                async with _active_lock:
                    _active_connections_count -= 1
                _metrics_registry.gauge(
                    "breadmind_active_connections",
                    "Currently active HTTP connections",
                    value=_active_connections_count,
                )

            normalized = normalize_path(path)
            status_code = str(response.status_code)
            _metrics_registry.counter(
                "breadmind_http_requests_total",
                "Total HTTP requests",
                labels={"method": method, "path": normalized, "status_code": status_code},
            )
            _metrics_registry.histogram_observe(
                "breadmind_http_request_duration_seconds",
                "HTTP request duration in seconds",
                value=duration,
                labels={"method": method, "path": normalized},
            )
            return response

        # --- Auth middleware ---

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            path = request.url.path
            # Skip auth for certain paths
            skip_paths = ["/api/auth/", "/health", "/metrics",
                         "/api/webhook/receive/", "/api/workers/install-script",
                         "/credential-input/", "/api/vault/submit-external/"]
            if any(path.startswith(p) for p in skip_paths):
                return await call_next(request)

            # Setup endpoints: only skip auth during first run
            if path.startswith("/api/setup/"):
                setup_allowed = False
                if not self._db:
                    setup_allowed = True
                else:
                    try:
                        from breadmind.core.setup_wizard import is_first_run_async
                        setup_allowed = await is_first_run_async(self._db)
                    except Exception:
                        setup_allowed = True
                if setup_allowed:
                    return await call_next(request)

            # Skip if auth not enabled
            if not self._auth or not self._auth.enabled:
                return await call_next(request)

            # Let the index route handle its own rendering
            if path == "/":
                return await call_next(request)

            # Static files don't need auth
            if path.startswith("/static/"):
                return await call_next(request)

            # API calls need auth
            if path.startswith("/api/") and not self._auth.authenticate_request(request):
                return JSONResponse(status_code=401, content={"error": "Authentication required"})

            # WebSocket paths are handled in their own route
            if path.startswith("/ws/"):
                return await call_next(request)

            return await call_next(request)

        # --- Security headers middleware ---

        @app.middleware("http")
        async def add_security_headers(request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            return response

        # --- Rate limiting middleware ---

        @app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            # Skip rate limiting for health checks and WebSocket connections
            path = request.url.path
            if path == "/health" or path.startswith("/ws/"):
                return await call_next(request)

            client_ip = request.client.host if request.client else "unknown"

            # Auth endpoint rate limiting (stricter)
            if path.startswith("/api/auth/login"):
                if rate_limiter.is_auth_blocked(client_ip):
                    return JSONResponse(
                        status_code=429,
                        content={"error": "Too many failed login attempts. Try again in 5 minutes."},
                    )

            # General rate limiting
            if not rate_limiter.is_allowed(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded. Try again later."},
                )

            response = await call_next(request)

            # Record auth failures
            if path.startswith("/api/auth/login") and response.status_code == 401:
                rate_limiter.record_auth_fail(client_ip)

            return response

        # --- HTTPS enforce middleware (outermost – registered last) ---

        @app.middleware("http")
        async def enforce_https(request: Request, call_next):
            if (self._config and hasattr(self._config, 'security')
                    and self._config.security.require_https
                    and request.url.scheme == "http"
                    and request.url.hostname not in ("localhost", "127.0.0.1")):
                https_url = request.url.replace(scheme="https")
                return RedirectResponse(url=str(https_url), status_code=301)
            return await call_next(request)

        # --- Index route ---

        @app.get("/", response_class=HTMLResponse)
        async def index():
            html_path = Path(__file__).parent / "static" / "index.html"
            if html_path.exists():
                return html_path.read_text(encoding="utf-8")
            return "<html><body><h1>BreadMind</h1><p>Static files not found.</p></body></html>"

        # --- Register route modules ---

        setup_system_routes(app, self)
        setup_config_routes(app, self)
        setup_tools_routes(app, self)
        setup_mcp_routes(app, self)
        setup_monitoring_routes(app, self)
        setup_swarm_routes(app, self)
        setup_scheduler_routes(app, self)
        setup_subagent_routes(app, self)
        setup_container_routes(app, self)
        setup_settings_routes(app, self)
        setup_messenger_routes(app, self)
        setup_worker_routes(app, self)
        setup_chat_routes(app, self)
        setup_credential_input_routes(app, self)
        setup_bg_job_routes(app, self)
        register_coding_job_routes(app)
        app.include_router(oauth_router)
        app.include_router(integrations_router)
        app.include_router(personal_router)
        app.include_router(infra_router)
        app.include_router(plugins_router)
        app.include_router(upload_router)
        setup_export_routes(app, self)
        setup_backup_routes(app, self)

        # --- Prometheus metrics endpoint (outside versioning) ---

        @app.get("/metrics")
        async def prometheus_metrics():
            """Return all metrics in Prometheus text exposition format."""
            body = _metrics_registry.format_prometheus()
            return PlainTextResponse(
                content=body,
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

        # --- API versioning (must come after all route registrations) ---
        setup_versioning(app)

        # --- Static files (JS, CSS) ---
        static_dir = Path(__file__).parent / "static"
        if static_dir.exists():
            app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    async def _persist_swarm_roles(self):
        """Save all swarm roles to DB."""
        if self._db and self._swarm_manager:
            try:
                await self._db.set_setting("swarm_roles", self._swarm_manager.export_roles())
            except Exception:
                pass

    async def broadcast(self, message: str):
        async with self._lock:
            connections = self._connections[:]
        for ws in connections:
            try:
                await ws.send_text(json.dumps({"type": "notification", "message": message}))
            except Exception:
                async with self._lock:
                    if ws in self._connections:
                        self._connections.remove(ws)
