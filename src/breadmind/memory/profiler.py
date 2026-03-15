import logging
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


@dataclass
class UserPreference:
    category: str       # e.g., "snapshot_before_change", "notify_on_restart"
    description: str
    confidence: float = 1.0


@dataclass
class UserPattern:
    action: str          # e.g., "restart_pod", "check_logs_first"
    frequency: int = 1
    context: str = ""


class UserProfiler:
    """Extract and store user preferences and behavioral patterns."""

    def __init__(self, db=None):
        self._preferences: dict[str, list[UserPreference]] = {}  # user -> prefs
        self._patterns: dict[str, list[UserPattern]] = {}  # user -> patterns
        self._db = db
        self._max_preferences = 20

    async def add_preference(self, user: str, pref: UserPreference):
        if user not in self._preferences:
            self._preferences[user] = []
        # Update existing or add new
        for existing in self._preferences[user]:
            if existing.category == pref.category:
                existing.description = pref.description
                existing.confidence = min(existing.confidence + 0.1, 1.0)
                return
        self._preferences[user].append(pref)
        # After adding preference, trim to max
        prefs = self._preferences[user]
        if len(prefs) > self._max_preferences:
            # Remove lowest confidence preferences
            prefs.sort(key=lambda p: p.confidence, reverse=True)
            self._preferences[user] = prefs[:self._max_preferences]

    async def add_pattern(self, user: str, pattern: UserPattern):
        if user not in self._patterns:
            self._patterns[user] = []
        for existing in self._patterns[user]:
            if existing.action == pattern.action:
                existing.frequency += 1
                return
        self._patterns[user].append(pattern)

    async def get_preferences(self, user: str) -> list[UserPreference]:
        return self._preferences.get(user, [])

    async def get_patterns(self, user: str) -> list[UserPattern]:
        return self._patterns.get(user, [])

    async def get_user_context(self, user: str) -> str:
        """Build context string for LLM system prompt injection."""
        prefs = await self.get_preferences(user)
        patterns = await self.get_patterns(user)
        parts = []
        if prefs:
            parts.append("User preferences:")
            for p in prefs:
                parts.append(f"  - {p.category}: {p.description}")
        if patterns:
            parts.append("Behavioral patterns:")
            for p in patterns:
                parts.append(f"  - {p.action} (frequency: {p.frequency})")
        return "\n".join(parts) if parts else ""

    async def decay_preference(self, user: str, category: str, amount: float = 0.15) -> None:
        """Reduce confidence of a preference (e.g., when user bypasses it)."""
        prefs = self._preferences.get(user, [])
        for p in prefs:
            if p.category == category:
                p.confidence = max(0.0, p.confidence - amount)
                break

    async def flush_to_db(self) -> None:
        """Save all profiler data to DB."""
        if not self._db or not hasattr(self._db, 'set_setting'):
            return
        try:
            data = {
                "preferences": {
                    user: [{"category": p.category, "description": p.description, "confidence": p.confidence}
                           for p in prefs]
                    for user, prefs in self._preferences.items()
                },
                "patterns": {
                    user: [{"action": p.action, "frequency": p.frequency, "context": p.context}
                           for p in pats]
                    for user, pats in self._patterns.items()
                },
            }
            await self._db.set_setting("user_profiler", data)
        except Exception as e:
            _log.warning(f"Failed to flush profiler: {e}")

    async def load_from_db(self) -> None:
        """Load profiler data from DB."""
        if not self._db or not hasattr(self._db, 'get_setting'):
            return
        try:
            data = await self._db.get_setting("user_profiler")
            if not data:
                return
            for user, prefs in data.get("preferences", {}).items():
                self._preferences[user] = [
                    UserPreference(category=p["category"], description=p["description"],
                                   confidence=p.get("confidence", 1.0))
                    for p in prefs
                ]
            for user, pats in data.get("patterns", {}).items():
                self._patterns[user] = [
                    UserPattern(action=p["action"], frequency=p.get("frequency", 1),
                                context=p.get("context", ""))
                    for p in pats
                ]
        except Exception as e:
            _log.warning(f"Failed to load profiler: {e}")
