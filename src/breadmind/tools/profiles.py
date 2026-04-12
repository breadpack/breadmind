"""Tool profiles and group shorthands for bulk allow/deny."""
from __future__ import annotations


# Group definitions
TOOL_GROUPS: dict[str, list[str]] = {
    "group:fs": [
        "file_read", "file_write", "file_edit", "file_read_tracked", "list_files",
    ],
    "group:runtime": ["shell_exec", "process_list", "process_kill"],
    "group:web": ["web_search", "web_fetch"],
    "group:lsp": [
        "lsp_goto_definition", "lsp_find_references", "lsp_document_symbols",
    ],
    "group:git": ["git_commit", "git_status", "git_diff"],
    "group:notebook": ["notebook_read", "notebook_edit"],
    "group:infra": [
        "k8s_list_pods", "k8s_apply", "proxmox_list_vms", "openwrt_status",
    ],
    "group:memory": ["memory_search", "memory_save"],
    "group:all": [],  # special: means all tools
}

# Pre-defined profiles
PROFILES: dict[str, dict] = {
    "full": {
        "description": "All tools, no restriction",
        "allow": ["group:all"],
        "deny": [],
    },
    "coding": {
        "description": "File I/O, runtime, web, git, LSP, notebook",
        "allow": [
            "group:fs", "group:runtime", "group:web",
            "group:git", "group:lsp", "group:notebook",
        ],
        "deny": ["group:infra"],
    },
    "readonly": {
        "description": "Read-only tools only",
        "allow": [
            "file_read", "file_read_tracked", "list_files", "web_search",
            "git_status", "git_diff", "lsp_goto_definition", "lsp_find_references",
            "lsp_document_symbols", "notebook_read",
        ],
        "deny": ["group:runtime", "file_write", "file_edit", "git_commit"],
    },
    "minimal": {
        "description": "Status tools only",
        "allow": ["git_status", "list_files"],
        "deny": ["group:all"],
    },
}


class ToolProfileManager:
    """Manages tool profiles and resolves group shorthands."""

    def __init__(self, custom_groups: dict[str, list[str]] | None = None) -> None:
        self._groups = {**TOOL_GROUPS}
        if custom_groups:
            self._groups.update(custom_groups)

    def resolve_groups(self, entries: list[str]) -> set[str]:
        """Expand group shorthands to individual tool names."""
        result: set[str] = set()
        for entry in entries:
            if entry in self._groups:
                if entry == "group:all":
                    result.add("*")
                else:
                    result.update(self._groups[entry])
            else:
                result.add(entry)
        return result

    def get_profile(self, name: str) -> dict | None:
        return PROFILES.get(name)

    def is_allowed(self, tool_name: str, profile: str) -> bool:
        """Check if a tool is allowed under a profile."""
        prof = PROFILES.get(profile)
        if not prof:
            return True  # unknown profile = allow all

        denied = self.resolve_groups(prof.get("deny", []))
        if "*" in denied and tool_name not in self.resolve_groups(prof.get("allow", [])):
            return False
        if tool_name in denied:
            return False

        allowed = self.resolve_groups(prof.get("allow", []))
        if "*" in allowed:
            return True
        return tool_name in allowed

    def list_profiles(self) -> list[dict]:
        return [{"name": name, **prof} for name, prof in PROFILES.items()]

    def register_profile(
        self,
        name: str,
        allow: list[str],
        deny: list[str],
        description: str = "",
    ) -> None:
        PROFILES[name] = {
            "description": description,
            "allow": allow,
            "deny": deny,
        }
