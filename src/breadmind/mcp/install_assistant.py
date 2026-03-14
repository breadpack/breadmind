import json
import logging
from breadmind.llm.base import LLMProvider, LLMMessage

logger = logging.getLogger(__name__)

INSTALL_SYSTEM_PROMPT = """You are an MCP server installation assistant.
Analyze server metadata and provide structured installation guidance.
Always respond in valid JSON. Do not include markdown code fences."""

ANALYZE_PROMPT = """Analyze this MCP server and determine how to install/run it:
Name: {name}
Description: {description}
Source: {source}
Install Command: {install_command}

Respond with JSON:
{{
  "runtime": "node" | "python" | "docker" | "binary",
  "command": "the command to run",
  "args": ["list", "of", "args"],
  "required_env": [
    {{"name": "ENV_VAR_NAME", "description": "what this is for", "secret": true/false}}
  ],
  "optional_env": [],
  "dependencies": ["node>=18"],
  "summary": "Brief Korean description of what this server does and what it needs"
}}"""

TROUBLESHOOT_PROMPT = """An MCP server installation failed. Analyze and suggest a fix.
Server: {name}
Command: {command} {args}
Error log:
{error_log}

Respond with JSON:
{{
  "analysis": "What went wrong (Korean)",
  "suggestion": "How to fix it (Korean)",
  "auto_fix_available": true/false,
  "fix_command": "command to run if auto_fix_available"
}}"""


class InstallAssistant:
    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def analyze(self, server_meta: dict) -> dict:
        """Phase 1: Analyze server metadata and return structured install guide."""
        prompt = ANALYZE_PROMPT.format(
            name=server_meta.get("name", ""),
            description=server_meta.get("description", ""),
            source=server_meta.get("source", ""),
            install_command=server_meta.get("install_command", ""),
        )
        try:
            response = await self._provider.chat([
                LLMMessage(role="system", content=INSTALL_SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ])
            return self._parse_json(response.content)
        except Exception as e:
            logger.error(f"LLM analyze failed: {e}")
            return self._fallback_analyze(server_meta)

    async def troubleshoot(self, server_name: str, command: str, args: list, error_log: str) -> dict:
        """Phase 3: Analyze error and suggest fix."""
        prompt = TROUBLESHOOT_PROMPT.format(
            name=server_name,
            command=command,
            args=" ".join(args),
            error_log=error_log[-2000:],  # Limit log size
        )
        try:
            response = await self._provider.chat([
                LLMMessage(role="system", content=INSTALL_SYSTEM_PROMPT),
                LLMMessage(role="user", content=prompt),
            ])
            return self._parse_json(response.content)
        except Exception as e:
            logger.error(f"LLM troubleshoot failed: {e}")
            return {
                "analysis": f"LLM 분석 실패: {e}",
                "suggestion": "수동으로 에러 로그를 확인해주세요.",
                "auto_fix_available": False,
                "fix_command": "",
            }

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            text = text.rsplit("```", 1)[0]
        return json.loads(text)

    def _fallback_analyze(self, meta: dict) -> dict:
        """Fallback when LLM is unavailable."""
        cmd = meta.get("install_command", "")
        return {
            "runtime": "node" if "npx" in cmd or "node" in cmd else "python" if "pip" in cmd or "uvx" in cmd else "unknown",
            "command": cmd.split()[0] if cmd else "",
            "args": cmd.split()[1:] if cmd else [],
            "required_env": [],
            "optional_env": [],
            "dependencies": [],
            "summary": meta.get("description", ""),
        }
