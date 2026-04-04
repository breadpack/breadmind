from __future__ import annotations
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from breadmind.core.protocols import Message, PromptBlock, PromptContext, CompactResult


class JinjaPromptBuilder:
    """Jinja2 기반 PromptProtocol 구현체."""

    def __init__(self, templates_dir: Path, token_counter: callable | None = None) -> None:
        self._templates_dir = templates_dir
        self._env = Environment(loader=FileSystemLoader(str(templates_dir)))
        self._count_tokens = token_counter or (lambda text: len(text) // 4)
        self._last_static: list[PromptBlock] = []

    def build(self, context: PromptContext, provider: str = "claude", persona: str = "professional",
              role: str | None = None) -> list[PromptBlock]:
        blocks: list[PromptBlock] = []

        # Iron Laws (불변, cacheable, priority=0)
        iron_laws = self._render_template("behaviors/iron_laws.j2", context)
        blocks.append(PromptBlock(section="iron_laws", content=iron_laws, cacheable=True, priority=0,
                                  provider_hints={"claude": {"scope": "global"}}))

        # Identity (cacheable, priority=1)
        identity_vars = self._load_persona_vars(persona)
        role_vars = self._load_role_vars(role) if role else {}
        all_vars = {**self._context_to_dict(context), **identity_vars, **role_vars}
        identity = self._render_provider_template(provider, all_vars)
        blocks.append(PromptBlock(section="identity", content=identity, cacheable=True, priority=1,
                                  provider_hints={"claude": {"scope": "org"}}))

        # Behaviors (cacheable, priority=2)
        for tmpl_name in ["proactive", "tool_usage", "delegation", "safety"]:
            tmpl_path = f"behaviors/{tmpl_name}.j2"
            if (self._templates_dir / tmpl_path).exists():
                content = self._render_template(tmpl_path, context)
                blocks.append(PromptBlock(section=f"behavior_{tmpl_name}", content=content, cacheable=True, priority=2))

        # Role (dynamic, priority=3)
        if role and role_vars:
            blocks.append(PromptBlock(section="role", content=role_vars.get("domain_context", ""),
                                      cacheable=False, priority=3))

        # Env (dynamic, priority=5)
        env_content = f"OS: {context.os_info}\nDate: {context.current_date}\nModel: {context.provider_model}"
        blocks.append(PromptBlock(section="env", content=env_content, cacheable=False, priority=5))

        # Custom instructions (dynamic, priority=6)
        if context.custom_instructions:
            blocks.append(PromptBlock(section="custom", content=context.custom_instructions, cacheable=False, priority=6))

        # Fragments (dynamic, priority=10)
        for frag in ["os_context", "credential_handling", "interactive_input"]:
            frag_path = f"fragments/{frag}.j2"
            if (self._templates_dir / frag_path).exists():
                content = self._render_template(frag_path, context)
                blocks.append(PromptBlock(section=f"fragment_{frag}", content=content, cacheable=False, priority=10))

        self._last_static = [b for b in blocks if b.cacheable]
        return blocks

    def rebuild_dynamic(self, context: PromptContext) -> list[PromptBlock]:
        full = self.build(context)
        return [b for b in full if not b.cacheable]

    def trim_to_budget(self, blocks: list[PromptBlock], max_tokens: int) -> list[PromptBlock]:
        total = sum(self._count_tokens(b.content) for b in blocks)
        if total <= max_tokens:
            return blocks
        sorted_blocks = sorted(blocks, key=lambda b: -b.priority)
        result = list(blocks)
        for block in sorted_blocks:
            if block.priority == 0:
                break
            result.remove(block)
            total -= self._count_tokens(block.content)
            if total <= max_tokens:
                break
        return result

    async def compact(self, messages: list[Message], budget_tokens: int) -> CompactResult:
        raise NotImplementedError("Compaction requires LLMCompactor plugin")

    def inject_reminder(self, key: str, content: str) -> Message:
        return Message(role="user", content=f"<system-reminder>\n# {key}\n{content}\n</system-reminder>", is_meta=True)

    def _render_template(self, template_path: str, context: PromptContext) -> str:
        try:
            tmpl = self._env.get_template(template_path)
            return tmpl.render(**self._context_to_dict(context))
        except Exception:
            return ""

    def _render_provider_template(self, provider: str, variables: dict) -> str:
        try:
            tmpl = self._env.get_template(f"providers/{provider}.j2")
            return tmpl.render(**variables)
        except Exception:
            return f"You are {variables.get('persona_name', 'BreadMind')}."

    def _load_persona_vars(self, persona: str) -> dict:
        path = self._templates_dir / "personas" / f"{persona}.j2"
        if not path.exists():
            return {}
        return self._extract_set_vars(path.read_text(encoding="utf-8"))

    def _load_role_vars(self, role: str) -> dict:
        path = self._templates_dir / "roles" / f"{role}.j2"
        if not path.exists():
            return {}
        return self._extract_set_vars(path.read_text(encoding="utf-8"))

    def _extract_set_vars(self, template_text: str) -> dict:
        simple = dict(re.findall(r'\{%\s*set\s+(\w+)\s*=\s*"([^"]*)"\s*%\}', template_text))
        block_pattern = r'\{%\s*set\s+(\w+)\s*%\}(.*?)\{%\s*endset\s*%\}'
        for name, value in re.findall(block_pattern, template_text, re.DOTALL):
            simple[name] = value.strip()
        return simple

    def _context_to_dict(self, context: PromptContext) -> dict:
        return {
            "persona_name": context.persona_name, "language": context.language,
            "specialties": context.specialties, "os_info": context.os_info,
            "current_date": context.current_date, "available_tools": context.available_tools,
            "provider_model": context.provider_model, "custom_instructions": context.custom_instructions or "",
        }
