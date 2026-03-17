"""Settings UI routes for runtime configuration of system timeouts, retry, limits, polling, and memory GC."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from breadmind.web.dependencies import get_config, get_db

logger = logging.getLogger(__name__)


def _validate_int(value, name: str, min_val: int, max_val: int) -> tuple[int | None, str | None]:
    """Validate and coerce an integer value within range. Returns (value, error)."""
    try:
        v = int(value)
    except (ValueError, TypeError):
        return None, f"{name} must be an integer"
    if v < min_val or v > max_val:
        return None, f"{name} must be between {min_val} and {max_val}"
    return v, None


def _validate_float(value, name: str, min_val: float, max_val: float) -> tuple[float | None, str | None]:
    """Validate and coerce a float value within range. Returns (value, error)."""
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None, f"{name} must be a number"
    if v < min_val or v > max_val:
        return None, f"{name} must be between {min_val} and {max_val}"
    return v, None


def setup_settings_routes(r: APIRouter, app_state):
    """Register all /api/config/settings-* routes for runtime config editing."""

    # ── 1. System Timeouts ────────────────────────────────────────────

    _TIMEOUT_FIELDS = [
        "tool_call", "llm_api", "ssh_command", "health_check",
        "pypi_check", "http_default", "skill_discovery",
    ]

    @r.get("/api/config/timeouts-system")
    async def get_timeouts_system(config=Depends(get_config)):
        """Return current system-wide timeout settings."""
        if config and hasattr(config, "timeouts"):
            t = config.timeouts
            return {f: getattr(t, f) for f in _TIMEOUT_FIELDS}
        # Defaults from TimeoutsConfig
        from breadmind.config_types import TimeoutsConfig
        d = TimeoutsConfig()
        return {f: getattr(d, f) for f in _TIMEOUT_FIELDS}

    @r.post("/api/config/timeouts-system")
    async def update_timeouts_system(request: Request, config=Depends(get_config), db=Depends(get_db)):
        """Update system-wide timeout settings (all values 1-3600)."""
        data = await request.json()
        if not config or not hasattr(config, "timeouts"):
            return JSONResponse(status_code=503, content={"error": "Config not available"})

        t = config.timeouts
        for field in _TIMEOUT_FIELDS:
            if field in data:
                val, err = _validate_int(data[field], field, 1, 3600)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(t, field, val)

        # Persist
        if db:
            try:
                await db.set_setting(
                    "system_timeouts", {f: getattr(t, f) for f in _TIMEOUT_FIELDS}
                )
            except Exception as e:
                logger.warning("Failed to persist system_timeouts: %s", e)

        return {"status": "ok", "persisted": db is not None}

    # ── 2. Retry Config ───────────────────────────────────────────────

    _RETRY_FIELDS = {
        "max_retries": (1, 50),
        "llm_max_retries": (1, 50),
        "gateway_max_retries": (1, 50),
        "base_backoff": (1, 600),
        "max_backoff": (1, 600),
        "health_check_interval": (5, 3600),
    }

    @r.get("/api/config/retry")
    async def get_retry(config=Depends(get_config)):
        """Return current retry settings."""
        if config and hasattr(config, "retry"):
            rc = config.retry
            return {f: getattr(rc, f) for f in _RETRY_FIELDS}
        from breadmind.config_types import RetryConfig
        d = RetryConfig()
        return {f: getattr(d, f) for f in _RETRY_FIELDS}

    @r.post("/api/config/retry")
    async def update_retry(request: Request, config=Depends(get_config), db=Depends(get_db)):
        """Update retry settings."""
        data = await request.json()
        if not config or not hasattr(config, "retry"):
            return JSONResponse(status_code=503, content={"error": "Config not available"})

        rc = config.retry
        for field, (lo, hi) in _RETRY_FIELDS.items():
            if field in data:
                val, err = _validate_int(data[field], field, lo, hi)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(rc, field, val)

        if db:
            try:
                await db.set_setting(
                    "retry_config", {f: getattr(rc, f) for f in _RETRY_FIELDS}
                )
            except Exception as e:
                logger.warning("Failed to persist retry_config: %s", e)

        return {"status": "ok", "persisted": db is not None}

    # ── 3. Limits Config ──────────────────────────────────────────────

    _LIMITS_INT_FIELDS = {
        "max_tools": (1, 200),
        "max_context_tokens": (100, 1_000_000),
        "max_per_domain_skills": (1, 50),
        "audit_log_recent": (1, 10_000),
        "embedding_cache_size": (10, 100_000),
        "top_roles_limit": (1, 100),
        "smart_retriever_token_budget": (100, 1_000_000),
        "smart_retriever_limit": (1, 100),
    }
    _LIMITS_FLOAT_FIELDS = {
        "low_performance_threshold": (0.0, 1.0),
    }

    @r.get("/api/config/limits")
    async def get_limits(config=Depends(get_config)):
        """Return current limits settings."""
        if config and hasattr(config, "limits"):
            lc = config.limits
            result = {f: getattr(lc, f) for f in _LIMITS_INT_FIELDS}
            result.update({f: getattr(lc, f) for f in _LIMITS_FLOAT_FIELDS})
            return result
        from breadmind.config_types import LimitsConfig
        d = LimitsConfig()
        result = {f: getattr(d, f) for f in _LIMITS_INT_FIELDS}
        result.update({f: getattr(d, f) for f in _LIMITS_FLOAT_FIELDS})
        return result

    @r.post("/api/config/limits")
    async def update_limits(request: Request, config=Depends(get_config), db=Depends(get_db)):
        """Update limits settings."""
        data = await request.json()
        if not config or not hasattr(config, "limits"):
            return JSONResponse(status_code=503, content={"error": "Config not available"})

        lc = config.limits
        for field, (lo, hi) in _LIMITS_INT_FIELDS.items():
            if field in data:
                val, err = _validate_int(data[field], field, lo, hi)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(lc, field, val)

        for field, (lo, hi) in _LIMITS_FLOAT_FIELDS.items():
            if field in data:
                val, err = _validate_float(data[field], field, lo, hi)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(lc, field, val)

        if db:
            try:
                payload = {f: getattr(lc, f) for f in _LIMITS_INT_FIELDS}
                payload.update({f: getattr(lc, f) for f in _LIMITS_FLOAT_FIELDS})
                await db.set_setting("limits_config", payload)
            except Exception as e:
                logger.warning("Failed to persist limits_config: %s", e)

        return {"status": "ok", "persisted": db is not None}

    # ── 4. Polling Config ─────────────────────────────────────────────

    _POLLING_FIELDS = [
        "signal_interval", "gmail_interval", "update_check_interval",
        "data_flush_interval", "auto_cleanup_interval",
    ]

    @r.get("/api/config/polling")
    async def get_polling(config=Depends(get_config)):
        """Return current polling interval settings."""
        if config and hasattr(config, "polling"):
            pc = config.polling
            return {f: getattr(pc, f) for f in _POLLING_FIELDS}
        from breadmind.config_types import PollingConfig
        d = PollingConfig()
        return {f: getattr(d, f) for f in _POLLING_FIELDS}

    @r.post("/api/config/polling")
    async def update_polling(request: Request, config=Depends(get_config), db=Depends(get_db)):
        """Update polling interval settings (all values 1-86400)."""
        data = await request.json()
        if not config or not hasattr(config, "polling"):
            return JSONResponse(status_code=503, content={"error": "Config not available"})

        pc = config.polling
        for field in _POLLING_FIELDS:
            if field in data:
                val, err = _validate_int(data[field], field, 1, 86400)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(pc, field, val)

        if db:
            try:
                await db.set_setting(
                    "polling_config", {f: getattr(pc, f) for f in _POLLING_FIELDS}
                )
            except Exception as e:
                logger.warning("Failed to persist polling_config: %s", e)

        return {"status": "ok", "persisted": db is not None}

    # ── 5. Memory GC Config ───────────────────────────────────────────

    _GC_INT_FIELDS = {
        "interval_seconds": (60, 86400),
        "max_cached_notes": (10, 10000),
        "kg_max_age_days": (1, 365),
        "env_refresh_interval": (1, 3600),
    }
    _GC_FLOAT_FIELDS = {
        "decay_threshold": (0.01, 1.0),
    }

    @r.get("/api/config/memory-gc")
    async def get_memory_gc(config=Depends(get_config)):
        """Return current memory GC settings."""
        if config and hasattr(config, "memory_gc"):
            gc = config.memory_gc
            result = {f: getattr(gc, f) for f in _GC_INT_FIELDS}
            result.update({f: getattr(gc, f) for f in _GC_FLOAT_FIELDS})
            return result
        from breadmind.config_types import MemoryGCConfig
        d = MemoryGCConfig()
        result = {f: getattr(d, f) for f in _GC_INT_FIELDS}
        result.update({f: getattr(d, f) for f in _GC_FLOAT_FIELDS})
        return result

    @r.post("/api/config/memory-gc")
    async def update_memory_gc(request: Request, config=Depends(get_config), db=Depends(get_db)):
        """Update memory GC settings."""
        data = await request.json()
        if not config or not hasattr(config, "memory_gc"):
            return JSONResponse(status_code=503, content={"error": "Config not available"})

        gc = config.memory_gc
        for field, (lo, hi) in _GC_INT_FIELDS.items():
            if field in data:
                val, err = _validate_int(data[field], field, lo, hi)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(gc, field, val)

        for field, (lo, hi) in _GC_FLOAT_FIELDS.items():
            if field in data:
                val, err = _validate_float(data[field], field, lo, hi)
                if err:
                    return JSONResponse(status_code=400, content={"error": err})
                setattr(gc, field, val)

        if db:
            try:
                payload = {f: getattr(gc, f) for f in _GC_INT_FIELDS}
                payload.update({f: getattr(gc, f) for f in _GC_FLOAT_FIELDS})
                await db.set_setting("memory_gc_config", payload)
            except Exception as e:
                logger.warning("Failed to persist memory_gc_config: %s", e)

        return {"status": "ok", "persisted": db is not None}
