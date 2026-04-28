import asyncio
import json
import logging
import time
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from breadmind.core.metrics import get_metrics_registry, normalize_path

from breadmind.web.context import AppContext
from breadmind.web.idempotency import setup_idempotency
from breadmind.web.rate_limiter import RateLimiter
from breadmind.web.versioning import setup_versioning
from breadmind.web.routes import (
    setup_browser_routes,
    setup_chat_routes,
    setup_config_routes,
    setup_connectors_routes,
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
from breadmind.web.routes.companions import setup_companion_routes
from breadmind.web.routes.credential_input import setup_credential_input_routes
from breadmind.web.routes.bg_jobs import setup_bg_job_routes
from breadmind.web.routes.coding_jobs import register_coding_job_routes
from breadmind.web.routes.plugins import router as plugins_router
from breadmind.web.routes.hooks import router as hooks_router
from breadmind.web.routes.skills_bundle import router as skills_bundle_router
from breadmind.web.routes.upload import router as upload_router
from breadmind.web.routes.export import setup_export_routes
from breadmind.web.routes.backup import setup_backup_routes
from breadmind.web.routes.webhook_automation import setup_webhook_automation_routes
from breadmind.web.routes.pwa import setup_pwa_routes, send_push
from breadmind.web.routes.review import router as review_router
from breadmind.web.routes.ui import router as ui_router
from breadmind.web.routes.kb_metrics import router as kb_metrics_router
from breadmind.kb import tracing as kb_tracing

logger = logging.getLogger(__name__)

class WebApp:
    def __init__(self, ctx: AppContext | None = None, **kwargs):
        # Support both new (ctx) and legacy (kwargs) initialization
        if ctx is None:
            ctx = AppContext(**kwargs)
        self.ctx = ctx

        # Register AuthManager with the shared get_current_user dependency so
        # route handlers that use ``Depends(get_current_user)`` can reach it.
        from breadmind.web.deps import set_auth_manager
        set_auth_manager(self._auth)

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
        "_webhook_automation_store": "webhook_automation_store",
        "_webhook_rule_engine": "webhook_rule_engine",
        "_webhook_pipeline_executor": "webhook_pipeline_executor",
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
        # Send push notification for warning/critical events
        if event.severity in ("warning", "critical"):
            try:
                await send_push(
                    self._db,
                    title=f"[{event.severity.upper()}] {event.source}",
                    body=f"{event.target}: {event.condition}",
                    url="/#monitoring",
                    tag=f"monitor-{event.severity}",
                )
            except Exception:
                pass

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
        setup_connectors_routes(app, self)
        setup_messenger_routes(app, self)
        setup_worker_routes(app, self)
        setup_companion_routes(app, self)
        setup_chat_routes(app, self)
        setup_credential_input_routes(app, self)
        setup_bg_job_routes(app, self)
        register_coding_job_routes(app)
        app.include_router(oauth_router)
        app.include_router(integrations_router)
        app.include_router(personal_router)
        app.include_router(infra_router)
        app.include_router(plugins_router)
        app.include_router(hooks_router)
        app.include_router(skills_bundle_router)
        app.include_router(upload_router)
        # KB review UI — production ReviewQueue dependency is wired in a
        # later P5 task; until then the default dependency raises 500.
        app.include_router(review_router, prefix="/api/review")
        # KB Prometheus metrics (/kb/metrics) — spec §8.4 metric family served
        # from the prometheus_client default registry. The legacy /metrics
        # endpoint below keeps serving the in-tree registry for back-compat.
        app.include_router(kb_metrics_router)
        # Messenger v1 REST API — 16 sub-routers (workspaces, channels, messages,
        # search, ...). Built in M1; mounted here so it's reachable from the
        # main app and from rt-relay's BackfillSince callback. Closes M2a dep #1.
        from breadmind.messenger.api.v1 import (
            router as messenger_v1_router,
            install_exception_handlers as _install_messenger_handlers,
        )
        app.include_router(messenger_v1_router)
        _install_messenger_handlers(app)
        setup_export_routes(app, self)
        setup_backup_routes(app, self)
        setup_webhook_automation_routes(app, self)
        setup_browser_routes(app, self)
        setup_pwa_routes(app, self)
        # Server-Driven UI WebSocket (/ws/ui). The FlowEventBus + UISpecProjector
        # singletons are constructed lazily on first connection (see ui.py),
        # because the WebApp factory has no async startup hook.
        app.include_router(ui_router)

        # --- HookRegistry startup init (hooks-v2) ---
        # Constructs a HookRegistry backed by HookOverrideStore(pool) and
        # exposes it on app.state.hook_registry for /api/hooks/* routes.
        # WebApp.__init__ is sync, so we attach an on_startup handler.
        @app.on_event("startup")
        async def _init_hook_registry():
            try:
                from breadmind.hooks.db_store import HookOverrideStore
                from breadmind.hooks.registry import HookRegistry
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("hooks module import failed: %s", e)
                return
            db = self._db
            pool = getattr(db, "_pool", None) if db is not None else None
            if pool is None:
                logger.info("HookRegistry init skipped: no database pool")
                return
            try:
                app.state.hook_registry = HookRegistry(store=HookOverrideStore(pool=pool))
                await app.state.hook_registry.reload()
                logger.info("HookRegistry initialized")
            except Exception as e:
                logger.warning("HookRegistry init failed: %s", e)

        # --- Coding JobStore + LogBuffer wiring (long-running monitoring) ---
        # Construct a JobStore against the shared DB, bind it onto both the
        # JobTracker singleton (for write-through) and ``app.state`` (for
        # the /api/coding-jobs/{id}/phases/{step}/logs route). Also wires a
        # LogBuffer + background tick task that drains idle per-phase
        # buffers so UIs tailing a phase don't stall when the producer
        # goes quiet between batches.
        self._coding_tick_task: asyncio.Task | None = None

        @app.on_event("startup")
        async def _init_coding_job_store():
            db = self._db
            if db is None:
                logger.info("coding JobStore init skipped: no database")
                return
            try:
                from breadmind.coding.job_store import JobStore
                from breadmind.coding.job_tracker import JobTracker
                from breadmind.coding.log_buffer import LogBuffer
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("coding module import failed: %s", e)
                return
            try:
                store = JobStore(db)
                app.state.job_store = store
                tracker = JobTracker.get_instance()
                tracker.bind_store(store)
                buffer = LogBuffer(
                    flush_fn=JobTracker.make_default_flush(store),
                    size_threshold=50,
                    time_threshold_s=1.0,
                    per_phase_cap=5000,
                )
                tracker.bind_log_buffer(buffer)

                async def _tick_loop():
                    # Drain idle per-phase buffers every 0.5s so UIs
                    # tailing a phase don't stall between producer bursts.
                    while True:
                        try:
                            await asyncio.sleep(0.5)
                            await buffer.tick()
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:  # pragma: no cover - defensive
                            logger.debug("LogBuffer.tick failed: %s", e)

                self._coding_tick_task = asyncio.create_task(_tick_loop())
                logger.info("coding JobStore + LogBuffer wired")
            except Exception as e:
                logger.warning("coding JobStore wiring failed: %s", e)

        @app.on_event("shutdown")
        async def _shutdown_coding_tick():
            task = self._coding_tick_task
            if task is None:
                return
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # pragma: no cover
                pass

        # --- SkillStore exposure (skills-v2) ---
        # The skills_bundle router reads app.state.skill_store. The canonical
        # instance lives on ctx.skill_store (see WebApp._CTX_ATTR_MAP); mirror
        # it onto app.state at startup so the router can find it without
        # reaching through app_state.
        @app.on_event("startup")
        async def _init_skill_store_state():
            try:
                store = self.ctx.skill_store
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("skill_store access failed: %s", e)
                return
            if store is None:
                logger.info("skill_store not configured; skills_bundle router will 503")
                return
            try:
                app.state.skill_store = store
                logger.info("skill_store exposed on app.state")
            except Exception as e:
                logger.warning("skill_store exposure failed: %s", e)

        # --- Prometheus metrics endpoint (outside versioning) ---

        @app.get("/metrics")
        async def prometheus_metrics():
            """Return all metrics in Prometheus text exposition format."""
            body = _metrics_registry.format_prometheus()
            return PlainTextResponse(
                content=body,
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

        # --- OpenTelemetry tracing + auto-instrumentation (KB spec §8.4) ---
        # Install tracer provider and FastAPI/asyncpg instrumentation at startup
        # so spans emitted by breadmind.kb.tracing (kb.retrieve, kb.redact, ...)
        # flow through the configured exporter (OTLP if OTEL_EXPORTER_OTLP_ENDPOINT
        # is set, ConsoleSpanExporter otherwise). Guarded by idempotent install
        # helpers so re-importing the app module in tests is safe.
        @app.on_event("startup")
        async def _install_kb_tracing():
            try:
                kb_tracing.install_default_provider()
                kb_tracing.install_fastapi(app)
                kb_tracing.install_asyncpg()
                logger.info("KB tracing installed (FastAPI + asyncpg)")
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("KB tracing install failed: %s", e)

        # --- API versioning (must come after all route registrations) ---
        setup_versioning(app)

        # --- Static files (JS, CSS) ---
        static_dir = Path(__file__).parent / "static"
        if static_dir.exists():
            class _NoCacheStatic(StaticFiles):
                async def get_response(self, path, scope):
                    response = await super().get_response(path, scope)
                    # Disable browser caching for static assets to make dev iteration painless.
                    # Production should serve assets via a proper CDN/cache-control strategy.
                    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                    if "etag" in response.headers:
                        del response.headers["etag"]
                    if "last-modified" in response.headers:
                        del response.headers["last-modified"]
                    return response
            app.mount("/static", _NoCacheStatic(directory=str(static_dir)), name="static")

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
