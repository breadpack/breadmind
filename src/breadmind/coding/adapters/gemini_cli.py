from __future__ import annotations

import json

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult


class GeminiCLIAdapter(CodingAgentAdapter):
    name = "gemini"
    cli_command = "gemini"
    config_filename = "GEMINI.md"

    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]:
        opts = options or {}
        cmd = [self.cli_command, "-p", prompt, "--cwd", project, "--output-format", "json"]
        if opts.get("session_id"):
            cmd += ["--session", opts["session_id"]]
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
