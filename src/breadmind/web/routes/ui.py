"""WebSocket /ws/ui — Server-Driven UI channel.

Pushes UISpec documents to the client and receives user actions. On first
connection the client sends a ``view_request`` message; the server replies
with a ``spec_full`` message containing the fully-built UISpec. The server
also subscribes to the :class:`FlowEventBus` so that flow-related views are
refreshed (as ``spec_patch`` messages) whenever relevant events occur.

Auth: mirrors the pattern used by ``/ws/chat`` (``token`` query param or the
``breadmind_session`` cookie validated via ``app._auth``). When no auth is
configured, connections are accepted and the ``user`` query param (or the
default ``"default"``) is used as the user id. This is sufficient for the
Phase 1 milestone of Durable Task Flow.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from breadmind.sdui.actions import ActionHandler
from breadmind.sdui.patches import diff_specs
from breadmind.sdui.projector import UISpecProjector
from breadmind.sdui.spec import UISpec

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ui"])


_USER_SCOPED_VIEWS = {"chat_view", "flow_list_view", "settings_view"}
_FLOW_SCOPED_VIEWS = {"flow_list_view", "flow_detail_view"}


async def _ensure_projector(app: Any) -> tuple[UISpecProjector | None, Any]:
    """Lazily construct and cache ``UISpecProjector`` + ``FlowEventBus``.

    The web app factory does not currently expose a startup hook, so we
    build these singletons on first use and stash them on ``app.state``.
    Subsequent connections reuse the same instances. The
    :class:`ActionHandler` is constructed alongside so that the ``action``
    branch of ``handle_ws_ui`` always finds it populated.
    """
    projector = getattr(app.state, "uispec_projector", None)
    flow_bus = getattr(app.state, "flow_event_bus", None)
    if projector is not None and flow_bus is not None:
        return projector, flow_bus

    app_state = getattr(app.state, "app_state", None)
    if app_state is None:
        return None, None
    database = getattr(app_state, "_db", None)
    if database is None:
        return None, None

    # Serialize concurrent initialization.
    lock: asyncio.Lock = getattr(app.state, "_uispec_init_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state._uispec_init_lock = lock

    async with lock:
        projector = getattr(app.state, "uispec_projector", None)
        flow_bus = getattr(app.state, "flow_event_bus", None)
        if projector is not None and flow_bus is not None:
            return projector, flow_bus

        from breadmind.flow.event_bus import FlowEventBus
        from breadmind.flow.store import FlowEventStore

        store = FlowEventStore(database)
        flow_bus = FlowEventBus(store=store, redis=None)
        await flow_bus.start()

        working_memory = getattr(app_state, "_working_memory", None)
        message_handler = getattr(app_state, "_message_handler", None)

        # Optional dependencies for the SDUI views beyond the chat experience.
        # Each is fetched best-effort against the actual attribute names used
        # in this codebase (see other routes/*.py for the canonical patterns).
        # Views always fall back to graceful placeholders when missing.
        settings_store = (
            getattr(app_state, "_settings_store", None)
            or getattr(app_state, "_db", None)  # FileSettingsStore lives on the db helper for now
        )
        plugin_manager = getattr(app_state, "_plugin_mgr", None)
        messenger_router = getattr(app_state, "_message_router", None)

        # Browser engine: try the container slot first, then plugin path.
        browser_engine = None
        try:
            container = getattr(app_state, "_container", None)
            if container:
                browser_engine = container.get("browser_engine")
        except Exception:
            browser_engine = None
        if browser_engine is None and plugin_manager is not None:
            try:
                for p in getattr(plugin_manager, "_plugins", {}).values():
                    eng = getattr(p, "_engine", None)
                    if eng is not None:
                        browser_engine = eng
                        break
            except Exception:
                browser_engine = None

        try:
            from breadmind.coding.job_tracker import JobTracker
            job_tracker = JobTracker.get_instance()
        except Exception:
            job_tracker = None

        try:
            from breadmind.storage.credential_vault import CredentialVault
            credential_vault = CredentialVault(database)
        except Exception:
            credential_vault = None

        projector = UISpecProjector(
            db=database,
            bus=flow_bus,
            working_memory=working_memory,
            settings_store=settings_store,
            credential_vault=credential_vault,
            plugin_manager=plugin_manager,
            browser_engine=browser_engine,
            messenger_router=messenger_router,
            job_tracker=job_tracker,
        )
        app.state.flow_event_bus = flow_bus
        app.state.uispec_projector = projector

        # Shared SettingsService so SDUI (ActionHandler) and agent-tool
        # (ToolRegistry) write paths route through the same reload registry.
        from breadmind.settings.reload_registry import SettingsReloadRegistry
        from breadmind.settings.service import SettingsService

        reload_registry = SettingsReloadRegistry()

        # Build the service with a placeholder audit sink, then back-fill the
        # real one from ActionHandler below. Only after back-fill do we
        # publish the service to ``app.state`` — otherwise another coroutine
        # could observe the placeholder and record audit_id=None on a write.
        async def _placeholder_audit(**kwargs):
            return None

        settings_service = SettingsService(
            store=settings_store,
            vault=credential_vault,
            audit_sink=_placeholder_audit,
            reload_registry=reload_registry,
            event_bus=flow_bus,
        )

        action_handler = ActionHandler(
            bus=flow_bus,
            message_handler=message_handler,
            working_memory=working_memory,
            settings_store=settings_store,
            credential_vault=credential_vault,
            event_bus=flow_bus,
            settings_service=settings_service,
        )
        settings_service.set_audit_sink(action_handler._record_audit)
        app.state.settings_reload_registry = reload_registry
        app.state.settings_service = settings_service
        app.state.sdui_action_handler = action_handler

        # Task 9: hot-reload LLM provider on `llm` / `apikey:*` changes.
        # The CoreAgent auto-wraps its provider in an ``LLMProviderHolder`` at
        # construction time; here we just locate it and register a reloader
        # that rebuilds the provider via ``create_provider`` and swaps the
        # inner reference. If we cannot find an agent or config, we skip with
        # a warning so the web app still boots in minimal/test deployments.
        try:
            from breadmind.settings.llm_holder import LLMProviderHolder

            agent = getattr(app_state, "_agent", None)
            config = getattr(app_state, "_config", None)
            if agent is None or config is None:
                logger.warning(
                    "LLM hot-reload wiring skipped: agent=%s config=%s",
                    agent is not None,
                    config is not None,
                )
            else:
                existing_provider = getattr(agent, "_provider", None)
                if existing_provider is None:
                    logger.warning(
                        "LLM hot-reload wiring skipped: agent has no _provider",
                    )
                else:
                    if isinstance(existing_provider, LLMProviderHolder):
                        llm_holder = existing_provider
                    else:
                        llm_holder = LLMProviderHolder(existing_provider)
                        agent._provider = llm_holder

                    async def _reload_llm(ctx):
                        try:
                            key = ctx.get("key") or ""
                            new_value = ctx.get("new")

                            # `create_provider` reads from `config.llm.*` and
                            # `os.environ`, so push the fresh values into those
                            # sources first — otherwise the rebuild returns an
                            # identical provider and the "reload" is a no-op.
                            if key == "llm" and isinstance(new_value, dict):
                                llm_cfg = getattr(config, "llm", None)
                                if llm_cfg is not None:
                                    provider_name = new_value.get("default_provider")
                                    if provider_name:
                                        llm_cfg.default_provider = provider_name
                                    model = new_value.get("default_model")
                                    if model:
                                        llm_cfg.default_model = model
                            elif key.startswith("apikey:"):
                                # Fetch the fresh secret from the vault and push
                                # it into os.environ under the matching env var
                                # so create_provider's env lookup sees it.
                                import os
                                from breadmind.llm.factory import (
                                    _PROVIDER_REGISTRY,
                                )
                                slug = key.split(":", 1)[1]
                                vault = getattr(app_state, "_credential_vault", None)
                                if vault is not None:
                                    try:
                                        secret = await vault.retrieve(key)
                                    except Exception:
                                        secret = None
                                    if secret:
                                        info = _PROVIDER_REGISTRY.get(slug)
                                        if info is not None and info.env_key:
                                            os.environ[info.env_key] = secret

                            from breadmind.llm.factory import create_provider
                            old_inner = llm_holder.current
                            new_provider = create_provider(config)
                            llm_holder.swap(new_provider)

                            # Release resources on the old inner provider.
                            if old_inner is not new_provider:
                                close = getattr(old_inner, "close", None)
                                if close is not None:
                                    try:
                                        import inspect
                                        if inspect.iscoroutinefunction(close):
                                            await close()
                                        else:
                                            close()
                                    except Exception as exc:  # noqa: BLE001
                                        logger.debug(
                                            "old LLM provider close failed: %s",
                                            exc,
                                        )

                            logger.info(
                                "LLM provider hot-reloaded (trigger=%s)", key,
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning(
                                "LLM hot-reload failed: %s", exc, exc_info=True,
                            )

                    reload_registry.register("llm", _reload_llm)
                    reload_registry.register("apikey:*", _reload_llm)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM hot-reload wiring skipped: %s", exc)

        # Register the eight agent settings tools onto the CoreAgent's tool
        # registry so LLM-driven write paths also hit the shared service.
        # Guarded because some deployments (tests, minimal runtimes) may not
        # have a tool registry attached to ``app_state``.
        tool_registry = getattr(app_state, "_tool_registry", None)
        if tool_registry is not None:
            from breadmind.tools.settings_tool_registration import (
                register_settings_tools,
            )
            try:
                register_settings_tools(
                    tool_registry,
                    service=settings_service,
                    actor="agent:core",
                )
            except Exception as exc:
                logger.warning("register_settings_tools failed: %s", exc)
        return projector, flow_bus


def _authenticate(ws: WebSocket) -> str | None:
    """Resolve a ``user_id`` from the WebSocket connection.

    Mirrors the pattern used by ``/ws/chat``: when ``app._auth`` is enabled
    the session ``token`` is validated from the query param or the
    ``breadmind_session`` cookie. When auth is disabled (single-user mode)
    we fall back to the ``user`` query param, defaulting to ``"default"``.
    """
    app_state = getattr(ws.app.state, "app_state", None)
    auth = getattr(app_state, "_auth", None) if app_state is not None else None

    if auth is not None and getattr(auth, "enabled", False):
        token = ws.query_params.get("token", "")
        if not (token and auth.verify_session(token)):
            token = ws.cookies.get("breadmind_session", "")
            if not (token and auth.verify_session(token)):
                return None
        # Prefer an explicit user hint sent by the client, fall back to token.
        return ws.query_params.get("user") or token

    return ws.query_params.get("user") or "default"


async def handle_ws_ui(ws: WebSocket) -> None:
    """Handle a single ``/ws/ui`` connection.

    Split out from the route function so tests can drive the handler with a
    mocked ``WebSocket`` without relying on a running HTTP server.
    """
    user_id = _authenticate(ws)
    if user_id is None:
        await ws.close(code=4401, reason="Authentication required")
        return

    await ws.accept()

    projector, flow_bus = await _ensure_projector(ws.app)
    if projector is None or flow_bus is None:
        logger.error("uispec_projector/flow_event_bus unavailable — closing /ws/ui")
        await ws.close(code=1011, reason="UI channel not ready")
        return

    current_view: str | None = None
    current_params: dict[str, Any] = {}
    current_spec: UISpec | None = None
    subscription_task: asyncio.Task | None = None

    def _call_params(view_key: str, params: dict[str, Any]) -> dict[str, Any]:
        call = dict(params)
        if view_key in _USER_SCOPED_VIEWS:
            call.setdefault("user_id", user_id)
        if view_key == "chat_view":
            call.setdefault("session_id", f"sdui:{user_id}")
        return call

    async def push_view(view_key: str, params: dict[str, Any]) -> None:
        nonlocal current_view, current_params, current_spec
        try:
            spec = await projector.build_view(view_key, **_call_params(view_key, params))
        except Exception as exc:
            logger.warning("build_view(%s) failed: %s", view_key, exc)
            await ws.send_text(json.dumps({
                "type": "error",
                "view_key": view_key,
                "error": str(exc),
            }))
            return
        current_view = view_key
        current_params = dict(params)
        current_spec = spec
        await ws.send_text(json.dumps({
            "type": "spec_full",
            "view_key": view_key,
            "spec": spec.to_dict(),
        }))

    async def refresh_current() -> None:
        nonlocal current_spec
        if current_view is None or current_spec is None:
            return
        try:
            new_spec = await projector.build_view(
                current_view, **_call_params(current_view, current_params)
            )
        except Exception as exc:
            logger.warning("refresh(%s) failed: %s", current_view, exc)
            return
        patch = diff_specs(current_spec, new_spec)
        if patch:
            try:
                await ws.send_text(json.dumps({
                    "type": "spec_patch",
                    "view_key": current_view,
                    "patch": patch,
                }))
            except Exception:
                return
        current_spec = new_spec

    async def flow_event_listener() -> None:
        subscriber_id = f"ws-ui-{id(ws)}"
        try:
            async for _event in flow_bus.subscribe(subscriber_id):
                if current_view in _FLOW_SCOPED_VIEWS:
                    await refresh_current()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("flow event listener crashed: %s", exc)

    try:
        subscription_task = asyncio.create_task(flow_event_listener())
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "view_request":
                await push_view(
                    msg.get("view_key", "chat_view"),
                    msg.get("params") or {},
                )
            elif mtype == "action":
                action = msg.get("action") or {}
                kind = action.get("kind")
                if kind == "view_request":
                    # Form-driven view requests carry their field values in
                    # ``action.values`` (the SDUI form widget always wraps
                    # field state under that key). Merge them into params so
                    # search/filter forms that target a view can pass query
                    # state without inventing a new action kind.
                    merged_params = dict(action.get("params") or {})
                    form_values = action.get("values")
                    if isinstance(form_values, dict):
                        for k, v in form_values.items():
                            merged_params.setdefault(k, v)
                    await push_view(
                        action.get("view_key", "chat_view"),
                        merged_params,
                    )
                else:
                    handler = getattr(ws.app.state, "sdui_action_handler", None)
                    if handler is not None:
                        try:
                            result = await handler.handle(action, user_id=user_id)
                            await ws.send_text(json.dumps({
                                "type": "action_result",
                                "result": result,
                            }))
                            refresh_key = (
                                result.get("refresh_view")
                                if isinstance(result, dict) else None
                            )
                            if refresh_key:
                                if refresh_key == current_view:
                                    await refresh_current()
                                else:
                                    await push_view(refresh_key, current_params)
                        except Exception as exc:
                            logger.warning("action handler error: %s", exc)
                            await ws.send_text(json.dumps({
                                "type": "action_result",
                                "error": str(exc),
                            }))
            elif mtype == "viewport":
                # Layout hints: stored in Phase 2.
                continue
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("/ws/ui unexpected error: %s", exc)
    finally:
        if subscription_task is not None:
            subscription_task.cancel()
            try:
                await subscription_task
            except (asyncio.CancelledError, Exception):
                pass


@router.websocket("/ws/ui")
async def ws_ui(ws: WebSocket) -> None:
    await handle_ws_ui(ws)
