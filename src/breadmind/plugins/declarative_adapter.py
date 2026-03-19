from __future__ import annotations

import json

from breadmind.coding.adapters.base import CodingAgentAdapter, CodingResult


class DeclarativeAdapter(CodingAgentAdapter):
    def __init__(self, config: dict):
        self.name = config["name"]
        self.cli_command = config.get("cli_command", config["name"])
        self.config_filename = config.get("config_filename", "")
        self._prompt_flag = config.get("prompt_flag", "-p")
        self._cwd_flag = config.get("cwd_flag", "--cwd")
        self._output_format = config.get("output_format", "text")
        self._session_flag = config.get("session_flag", "")
        self._model_flag = config.get("model_flag", "--model")
        self._extra_flags = config.get("extra_flags", [])

    def build_command(self, project: str, prompt: str, options: dict | None = None) -> list[str]:
        cmd = [self.cli_command, self._prompt_flag, prompt]
        if self._cwd_flag:
            cmd.extend([self._cwd_flag, project])
        if self._output_format == "json":
            cmd.extend(["--output-format", "json"])
        elif self._output_format == "quiet":
            cmd.append("--quiet")
        if options:
            if options.get("session_id") and self._session_flag:
                cmd.extend([self._session_flag, options["session_id"]])
            if options.get("model"):
                cmd.extend([self._model_flag, options["model"]])
        cmd.extend(self._extra_flags)
        return cmd

    def parse_result(self, stdout: str, stderr: str, returncode: int) -> CodingResult:
        if self._output_format == "json" and returncode == 0:
            try:
                data = json.loads(stdout)
                return CodingResult(
                    success=True,
                    output=data.get("result", stdout),
                    files_changed=data.get("files_changed", []),
                    session_id=data.get("session_id"),
                    cost=data.get("cost"),
                    agent=self.name,
                )
            except (json.JSONDecodeError, KeyError):
                pass
        return CodingResult(
            success=returncode == 0,
            output=stdout if returncode == 0 else (stderr or stdout),
            files_changed=[],
            agent=self.name,
        )
