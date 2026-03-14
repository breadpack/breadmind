from dataclasses import dataclass, field


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

    def __init__(self):
        self._preferences: dict[str, list[UserPreference]] = {}  # user -> prefs
        self._patterns: dict[str, list[UserPattern]] = {}  # user -> patterns

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
