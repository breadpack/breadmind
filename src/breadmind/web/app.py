import asyncio
import json
import logging
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from typing import Callable

from breadmind.web.rate_limiter import RateLimiter
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
from breadmind.web.routes.plugins import router as plugins_router

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, message_handler: Callable | None = None, tool_registry=None, mcp_manager=None,
                 config=None, monitoring_engine=None, safety_config=None,
                 agent=None, audit_logger=None, metrics_collector=None, database=None,
                 mcp_store=None, safety_guard=None, working_memory=None, message_router=None,
                 scheduler=None, subagent_manager=None, webhook_manager=None, auth=None,
                 container_executor=None, swarm_manager=None,
                 skill_store=None, performance_tracker=None, search_engine=None,
                 token_manager=None, commander=None,
                 messenger_security=None, lifecycle_manager=None, orchestrator=None,
                 bg_job_manager=None, embedding_service=None,
                 plugin_mgr=None):
        try:
            from importlib.metadata import version as _pkg_ver
            _version = _pkg_ver("breadmind")
        except Exception:
            _version = "0.0.0"
        self.app = FastAPI(title="BreadMind", version=_version)
        # Expose self via FastAPI state so Depends() helpers can reach it
        self.app.state.app_state = self
        self._message_handler = message_handler
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_manager
        self._config = config
        self._monitoring_engine = monitoring_engine
        self._safety_config = safety_config
        self._agent = agent
        self._audit_logger = audit_logger
        self._metrics_collector = metrics_collector
        self._db = database
        self._mcp_store = mcp_store
        self._safety_guard = safety_guard
        self._working_memory = working_memory
        self._message_router = message_router
        self._scheduler = scheduler
        self._subagent_manager = subagent_manager
        self._webhook_manager = webhook_manager
        self._auth = auth
        self._container_executor = container_executor
        self._swarm_manager = swarm_manager
        self._skill_store = skill_store
        self._performance_tracker = performance_tracker
        self._search_engine = search_engine
        self._token_manager = token_manager
        self._commander = commander
        self._messenger_security = messenger_security
        self._lifecycle_manager = lifecycle_manager
        self._orchestrator = orchestrator
        self._bg_job_manager = bg_job_manager
        self._embedding_service = embedding_service
        self._plugin_mgr = plugin_mgr
        self._marketplace = None

        # CORS middleware
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
        #   HTTPS enforce → Rate limit → Security headers → Auth → handler

        # --- Auth middleware (innermost – registered first) ---

        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):
            path = request.url.path
            # Skip auth for certain paths
            skip_paths = ["/api/auth/", "/health", "/api/webhook/receive/", "/api/workers/install-script",
                         "/credential-input/", "/api/vault/submit-external/",
                         "/sw.js", "/manifest.json", "/offline.html"]
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

        # --- PWA routes ---

        static_dir = Path(__file__).parent / "static"

        @app.get("/manifest.json")
        async def manifest():
            return FileResponse(static_dir / "manifest.json", media_type="application/manifest+json")

        @app.get("/sw.js")
        async def service_worker():
            return FileResponse(
                static_dir / "sw.js",
                media_type="application/javascript",
                headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
            )

        @app.get("/offline.html")
        async def offline():
            return FileResponse(static_dir / "offline.html", media_type="text/html")

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
        app.include_router(oauth_router)
        app.include_router(integrations_router)
        app.include_router(personal_router)
        app.include_router(infra_router)
        app.include_router(plugins_router)

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
