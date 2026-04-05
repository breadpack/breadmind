"""Per-cron-job tool allowlists to restrict which tools a scheduled job can use."""
from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch


@dataclass
class CronToolPolicy:
    """Tool access policy for a cron job."""

    job_id: str
    allowed_tools: list[str] = field(default_factory=list)  # glob patterns
    denied_tools: list[str] = field(default_factory=list)    # glob patterns

    def is_allowed(self, tool_name: str) -> bool:
        """Check if a tool is allowed for this job.

        Deny takes precedence over allow.
        Empty allowed list = all tools allowed (minus denied).
        """
        # Check deny list first (deny always wins)
        for pattern in self.denied_tools:
            if fnmatch(tool_name, pattern):
                return False

        # If allow list is empty, everything not denied is allowed
        if not self.allowed_tools:
            return True

        # Check allow list
        for pattern in self.allowed_tools:
            if fnmatch(tool_name, pattern):
                return True

        return False


class CronAllowlistManager:
    """Manages per-job tool allowlists for cron jobs.

    Each cron job can have a whitelist/blacklist of tools it can use.
    Patterns support fnmatch globs (e.g., "shell_*", "file_*").
    """

    def __init__(self) -> None:
        self._policies: dict[str, CronToolPolicy] = {}

    def set_policy(
        self,
        job_id: str,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> CronToolPolicy:
        """Create or update a tool policy for a job."""
        policy = CronToolPolicy(
            job_id=job_id,
            allowed_tools=allowed or [],
            denied_tools=denied or [],
        )
        self._policies[job_id] = policy
        return policy

    def get_policy(self, job_id: str) -> CronToolPolicy | None:
        """Get the policy for a job, or None if no policy exists."""
        return self._policies.get(job_id)

    def check_tool(self, job_id: str, tool_name: str) -> bool:
        """Check if tool is allowed for a job. Returns True if no policy exists."""
        policy = self._policies.get(job_id)
        if policy is None:
            return True
        return policy.is_allowed(tool_name)

    def filter_tools(self, job_id: str, tools: list[str]) -> list[str]:
        """Filter a tool list based on job's policy."""
        policy = self._policies.get(job_id)
        if policy is None:
            return list(tools)
        return [t for t in tools if policy.is_allowed(t)]

    def remove_policy(self, job_id: str) -> bool:
        """Remove a job's policy. Returns True if it existed."""
        return self._policies.pop(job_id, None) is not None

    def list_policies(self) -> list[CronToolPolicy]:
        """Return all registered policies."""
        return list(self._policies.values())
