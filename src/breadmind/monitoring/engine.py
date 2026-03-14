import asyncio
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

@dataclass
class MonitoringEvent:
    source: str          # "k8s" | "proxmox" | "openwrt"
    target: str          # e.g., "pod:nginx-abc123", "vm:100", "interface:wan"
    severity: str        # "critical" | "warning" | "info"
    condition: str       # e.g., "CrashLoopBackOff", "NotReady", "memory_high"
    details: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass
class MonitoringRule:
    name: str
    source: str
    condition_fn: Callable[[dict, dict | None], list[MonitoringEvent]]
    interval_seconds: int = 60
    severity: str = "warning"

class LoopProtector:
    def __init__(self, cooldown_minutes: int = 10, max_auto_actions: int = 3):
        self._cooldown_minutes = cooldown_minutes
        self._max_auto_actions = max_auto_actions
        self._action_history: dict[str, list[datetime]] = {}
        self._cooldowns: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def can_act(self, target: str, action: str) -> bool:
        key = f"{target}:{action}"
        now = datetime.utcnow()

        async with self._lock:
            # Check cooldown
            last = self._cooldowns.get(key)
            if last and (now - last).total_seconds() < self._cooldown_minutes * 60:
                return False

            # Check circuit breaker
            history = self._action_history.get(key, [])
            # Clean old entries
            cutoff = now - timedelta(hours=1)
            history = [t for t in history if t > cutoff]
            self._action_history[key] = history

            if len(history) >= self._max_auto_actions:
                return False

        return True

    def can_act_sync(self, target: str, action: str) -> bool:
        """Synchronous version for backward compatibility."""
        key = f"{target}:{action}"
        now = datetime.utcnow()

        last = self._cooldowns.get(key)
        if last and (now - last).total_seconds() < self._cooldown_minutes * 60:
            return False

        history = self._action_history.get(key, [])
        cutoff = now - timedelta(hours=1)
        history = [t for t in history if t > cutoff]
        self._action_history[key] = history

        if len(history) >= self._max_auto_actions:
            return False

        return True

    async def record_action(self, target: str, action: str):
        key = f"{target}:{action}"
        now = datetime.utcnow()
        async with self._lock:
            self._cooldowns[key] = now
            if key not in self._action_history:
                self._action_history[key] = []
            self._action_history[key].append(now)

    def record_action_sync(self, target: str, action: str):
        """Synchronous version for backward compatibility."""
        key = f"{target}:{action}"
        now = datetime.utcnow()
        self._cooldowns[key] = now
        if key not in self._action_history:
            self._action_history[key] = []
        self._action_history[key].append(now)

class MonitoringEngine:
    def __init__(
        self,
        on_event: Callable[[MonitoringEvent], Any] | None = None,
        loop_protector: LoopProtector | None = None,
    ):
        self._rules: list[MonitoringRule] = []
        self._on_event = on_event
        self._loop_protector = loop_protector or LoopProtector()
        self._previous_states: dict[str, dict] = {}
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._lock = asyncio.Lock()

    async def add_rule(self, rule: MonitoringRule):
        async with self._lock:
            self._rules.append(rule)

    def add_rule_sync(self, rule: MonitoringRule):
        """Synchronous add_rule for backward compatibility and setup before start."""
        self._rules.append(rule)

    async def start(self):
        async with self._lock:
            if self._running:
                logger.warning("Monitoring engine is already running.")
                return
            self._running = True
            for rule in self._rules:
                task = asyncio.create_task(self._run_rule(rule))
                self._tasks.append(task)
            logger.info(f"Monitoring engine started with {len(self._rules)} rules.")

    async def stop(self):
        async with self._lock:
            if not self._running:
                logger.warning("Monitoring engine is not running.")
                return
            self._running = False
            tasks = self._tasks[:]
            self._tasks.clear()

        logger.info("Monitoring engine stopping...")

        for task in tasks:
            task.cancel()

        if tasks:
            # Wait for tasks to finish with a timeout
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.error(f"Task {i} ended with error during stop: {result}")

        logger.info("Monitoring engine stopped.")

    async def _run_rule(self, rule: MonitoringRule):
        try:
            while self._running:
                try:
                    prev = self._previous_states.get(rule.name)
                    current_state = {}  # Placeholder: real collectors would fetch state here
                    events = rule.condition_fn(current_state, prev)
                    self._previous_states[rule.name] = current_state

                    for event in events:
                        if self._loop_protector.can_act_sync(event.target, event.condition):
                            self._loop_protector.record_action_sync(event.target, event.condition)
                            if self._on_event:
                                if asyncio.iscoroutinefunction(self._on_event):
                                    await self._on_event(event)
                                else:
                                    self._on_event(event)
                            logger.info(f"Event: {event.source}/{event.target} - {event.condition} ({event.severity})")
                        else:
                            logger.warning(f"Suppressed (loop protection): {event.target}/{event.condition}")
                except Exception as e:
                    logger.error(f"Rule '{rule.name}' error: {e}")
                await asyncio.sleep(rule.interval_seconds)
        except asyncio.CancelledError:
            logger.debug(f"Rule '{rule.name}' task cancelled.")
            raise

    async def check_once(self, rule_name: str | None = None) -> list[MonitoringEvent]:
        """Run rules once (for testing). Returns collected events."""
        events = []
        rules = self._rules if rule_name is None else [r for r in self._rules if r.name == rule_name]
        for rule in rules:
            prev = self._previous_states.get(rule.name)
            current_state = {}
            new_events = rule.condition_fn(current_state, prev)
            self._previous_states[rule.name] = current_state
            events.extend(new_events)
        return events
