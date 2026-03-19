from __future__ import annotations

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult


class CodexAdapter(CodingAgentAdapter):
    name = "codex"
    cli_command = "codex"
    config_filename = "AGENTS.md"

    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]:
        opts = options or {}
        cmd = [self.cli_command, "--prompt", prompt, "--cwd", project, "--quiet"]
        if opts.get("session_id"):
            cmd += ["--session", opts["session_id"]]
        return cmd

    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult:
        return CodingResult(
            success=returncode == 0,
            output=stdout or stderr,
            files_changed=[],
        )
