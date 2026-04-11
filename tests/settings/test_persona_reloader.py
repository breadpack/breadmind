from breadmind.settings.reload_registry import SettingsReloadRegistry


class FakeAgent:
    def __init__(self):
        self.persona = "professional"
        self.custom_prompts: dict = {}
        self.custom_instructions = ""
        self.reload_calls = 0

    def reload_prompt_components(self, *, persona=None, custom_prompts=None, custom_instructions=None):
        if persona is not None:
            self.persona = persona
        if custom_prompts is not None:
            self.custom_prompts = custom_prompts
        if custom_instructions is not None:
            self.custom_instructions = custom_instructions
        self.reload_calls += 1


async def test_persona_change_triggers_agent_reload():
    agent = FakeAgent()
    registry = SettingsReloadRegistry()

    async def reload_persona(ctx):
        agent.reload_prompt_components(persona=ctx["new"])

    async def reload_custom_prompts(ctx):
        agent.reload_prompt_components(custom_prompts=ctx["new"])

    async def reload_custom_instructions(ctx):
        agent.reload_prompt_components(custom_instructions=ctx["new"])

    registry.register("persona", reload_persona)
    registry.register("custom_prompts", reload_custom_prompts)
    registry.register("custom_instructions", reload_custom_instructions)

    await registry.dispatch(key="persona", operation="set", old="professional", new="friendly")
    await registry.dispatch(key="custom_prompts", operation="set", old={}, new={"greet": "hi"})
    await registry.dispatch(key="custom_instructions", operation="set", old="", new="be brief")

    assert agent.persona == "friendly"
    assert agent.custom_prompts == {"greet": "hi"}
    assert agent.custom_instructions == "be brief"
    assert agent.reload_calls == 3
