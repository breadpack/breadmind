"""Real-time health dashboard for all managed components."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class ComponentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    DEGRADED = "degraded"


@dataclass
class ComponentHealth:
    name: str
    component_type: str  # "tool", "skill", "mcp_server", "plugin"
    status: ComponentStatus = ComponentStatus.ACTIVE
    uptime_seconds: float = 0
    last_used: float = 0
    use_count: int = 0
    error_count: int = 0
    avg_response_ms: float = 0
    last_error: str = ""
    metadata: dict = field(default_factory=dict)

    # Internal tracking (not part of public API)
    _registered_at: float = field(default_factory=time.time, repr=False)
    _total_response_ms: float = field(default=0, repr=False)


@dataclass
class DashboardSnapshot:
    timestamp: float = field(default_factory=time.time)
    total_components: int = 0
    active: int = 0
    inactive: int = 0
    errors: int = 0
    degraded: int = 0
    components: list[ComponentHealth] = field(default_factory=list)

    # Breakdown by type
    tools_active: int = 0
    skills_active: int = 0
    mcp_servers_active: int = 0
    plugins_active: int = 0


_TYPE_ATTR_MAP = {
    "tool": "tools_active",
    "skill": "skills_active",
    "mcp_server": "mcp_servers_active",
    "plugin": "plugins_active",
}


class HealthDashboard:
    """Real-time health dashboard for all managed components.

    Aggregates status from tools, skills, MCP servers, and plugins
    into a single unified view. Supports filtering, alerts, and trends.
    """

    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {}
        self._alerts: list[dict] = []
        self._history: list[DashboardSnapshot] = []
        self._max_history = 100

    # -- Registration --

    def register(
        self,
        name: str,
        component_type: str,
        status: ComponentStatus = ComponentStatus.ACTIVE,
    ) -> ComponentHealth:
        """Register a component and return its health record."""
        now = time.time()
        comp = ComponentHealth(
            name=name,
            component_type=component_type,
            status=status,
            _registered_at=now,
        )
        self._components[name] = comp
        self._check_alerts(name, None, status)
        return comp

    def unregister(self, name: str) -> None:
        """Remove a component from tracking."""
        self._components.pop(name, None)

    # -- Status updates --

    def update_status(
        self, name: str, status: ComponentStatus, error: str = ""
    ) -> None:
        """Update the status of a registered component."""
        comp = self._components.get(name)
        if comp is None:
            return
        old_status = comp.status
        comp.status = status
        if error:
            comp.last_error = error
            comp.error_count += 1
        self._check_alerts(name, old_status, status)

    def record_use(
        self, name: str, response_time_ms: float = 0, success: bool = True
    ) -> None:
        """Record a component usage event."""
        comp = self._components.get(name)
        if comp is None:
            return
        comp.use_count += 1
        comp.last_used = time.time()
        comp._total_response_ms += response_time_ms
        comp.avg_response_ms = comp._total_response_ms / comp.use_count
        if not success:
            comp.error_count += 1

    # -- Queries --

    def get_snapshot(self) -> DashboardSnapshot:
        """Get current dashboard state."""
        now = time.time()
        snap = DashboardSnapshot(timestamp=now)
        snap.total_components = len(self._components)
        for comp in self._components.values():
            comp.uptime_seconds = now - comp._registered_at
            snap.components.append(comp)
            if comp.status == ComponentStatus.ACTIVE:
                snap.active += 1
                attr = _TYPE_ATTR_MAP.get(comp.component_type)
                if attr:
                    setattr(snap, attr, getattr(snap, attr) + 1)
            elif comp.status == ComponentStatus.INACTIVE:
                snap.inactive += 1
            elif comp.status == ComponentStatus.ERROR:
                snap.errors += 1
            elif comp.status == ComponentStatus.DEGRADED:
                snap.degraded += 1
        self._save_snapshot()
        return snap

    def get_component(self, name: str) -> ComponentHealth | None:
        """Get health info for a single component."""
        return self._components.get(name)

    def get_by_type(self, component_type: str) -> list[ComponentHealth]:
        """Get all components of a given type."""
        return [
            c for c in self._components.values() if c.component_type == component_type
        ]

    def get_by_status(self, status: ComponentStatus) -> list[ComponentHealth]:
        """Get all components with a given status."""
        return [c for c in self._components.values() if c.status == status]

    # -- Alerts --

    def get_alerts(self, limit: int = 20) -> list[dict]:
        """Get recent alerts (errors, status changes)."""
        return self._alerts[-limit:]

    # -- Trends --

    def get_trends(self, periods: int = 10) -> list[DashboardSnapshot]:
        """Get historical snapshots for trend analysis."""
        return self._history[-periods:]

    # -- Rendering --

    def render_text(self) -> str:
        """Render dashboard as formatted text for CLI display."""
        snap = self.get_snapshot()
        lines: list[str] = []
        lines.append("=== Health Dashboard ===")
        lines.append(
            f"Total: {snap.total_components}  "
            f"Active: {snap.active}  "
            f"Inactive: {snap.inactive}  "
            f"Error: {snap.errors}  "
            f"Degraded: {snap.degraded}"
        )
        lines.append("")
        lines.append(
            f"Tools: {snap.tools_active}  "
            f"Skills: {snap.skills_active}  "
            f"MCP: {snap.mcp_servers_active}  "
            f"Plugins: {snap.plugins_active}"
        )
        lines.append("")
        for comp in snap.components:
            status_icon = {
                ComponentStatus.ACTIVE: "[OK]",
                ComponentStatus.INACTIVE: "[--]",
                ComponentStatus.ERROR: "[!!]",
                ComponentStatus.DEGRADED: "[~~]",
            }.get(comp.status, "[??]")
            lines.append(
                f"  {status_icon} {comp.name} ({comp.component_type}) "
                f"uses={comp.use_count} "
                f"err={comp.error_count} "
                f"avg={comp.avg_response_ms:.1f}ms"
            )
            if comp.last_error:
                lines.append(f"       last_error: {comp.last_error}")
        return "\n".join(lines)

    # -- Internal --

    def _check_alerts(
        self,
        name: str,
        old_status: ComponentStatus | None,
        new_status: ComponentStatus,
    ) -> None:
        """Generate alerts on status changes."""
        if new_status in (ComponentStatus.ERROR, ComponentStatus.DEGRADED):
            self._alerts.append(
                {
                    "timestamp": time.time(),
                    "component": name,
                    "type": "status_change",
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                }
            )
        elif old_status is not None and old_status != new_status:
            self._alerts.append(
                {
                    "timestamp": time.time(),
                    "component": name,
                    "type": "status_change",
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                }
            )

    def _save_snapshot(self) -> None:
        """Save a snapshot to history, trimming if needed."""
        now = time.time()
        snap = DashboardSnapshot(timestamp=now)
        snap.total_components = len(self._components)
        for comp in self._components.values():
            if comp.status == ComponentStatus.ACTIVE:
                snap.active += 1
            elif comp.status == ComponentStatus.INACTIVE:
                snap.inactive += 1
            elif comp.status == ComponentStatus.ERROR:
                snap.errors += 1
            elif comp.status == ComponentStatus.DEGRADED:
                snap.degraded += 1
        self._history.append(snap)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
