from __future__ import annotations

import json

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult


class ClaudeCodeAdapter(CodingAgentAdapter):
    name = "claude"
    cli_command = "claude"
    config_filename = "CLAUDE.md"

    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]:
        opts = options or {}
        cmd = [
            self.cli_command, "-p", prompt,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]
        if opts.get("session_id"):
            cmd += ["--resume", opts["session_id"]]
        if opts.get("model"):
            cmd += ["--model", opts["model"]]
        return cmd

    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult:
        if stdout.strip():
            try:
                data = json.loads(stdout)
                return CodingResult(
                    success=returncode == 0,
                    output=data.get("result", stdout),
                    files_changed=data.get("files_changed", []),
                    cost=data.get("cost"),
                    session_id=data.get("session_id"),
                )
            except (json.JSONDecodeError, TypeError):
                pass

        return CodingResult(
            success=returncode == 0,
            output=stdout or stderr,
            files_changed=[],
        )
