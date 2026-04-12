# Hooks v3: Extended Handlers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PromptHook, AgentHook, HttpHook handler types and conditional filtering (`if`) to BreadMind's hook system.

**Architecture:** Each handler implements the existing `HookHandler` protocol. Conditional filtering is a standalone module integrated at `HookChain` level. HttpHook includes an SSRF guard module. All share the same `HookDecision` protocol.

**Tech Stack:** Python 3.12+, aiohttp, Jinja2, existing LLM provider system, existing ToolRegistry, fnmatch for glob patterns.

---

### Task 1: Conditional Filtering Module

**Files:**
- Create: `src/breadmind/hooks/condition.py`
- Test: `tests/hooks/test_condition.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hooks/test_condition.py
import pytest
from breadmind.hooks.condition import matches_condition
from breadmind.hooks.events import HookEvent, HookPayload


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


def test_none_condition_always_matches():
    assert matches_condition(None, _payload()) is True


def test_tool_pattern_match():
    p = _payload(tool_name="Bash", tool_input="git status")
    assert matches_condition("Bash(git *)", p) is True


def test_tool_pattern_no_match():
    p = _payload(tool_name="Read", tool_input="foo.py")
    assert matches_condition("Bash(git *)", p) is False


def test_tool_pattern_wildcard_tool():
    p = _payload(tool_name="Write", tool_input="src/main.py")
    assert matches_condition("Write(*)", p) is True


def test_tool_pattern_no_args_in_pattern():
    p = _payload(tool_name="Bash", tool_input="echo hi")
    assert matches_condition("Bash", p) is True


def test_tool_pattern_tool_name_only_no_match():
    p = _payload(tool_name="Read", tool_input="foo.py")
    assert matches_condition("Bash", p) is False


def test_data_field_match():
    p = _payload(channel_id="general")
    assert matches_condition("data.channel_id=general", p) is True


def test_data_field_no_match():
    p = _payload(channel_id="random")
    assert matches_condition("data.channel_id=general", p) is False


def test_data_field_missing():
    p = _payload()
    assert matches_condition("data.channel_id=general", p) is False


def test_event_match():
    p = _payload()
    assert matches_condition("event=pre_tool_use", p) is True


def test_event_no_match():
    p = _payload()
    assert matches_condition("event=post_tool_use", p) is False


def test_not_prefix():
    p = _payload(tool_name="Bash", tool_input="rm -rf /")
    assert matches_condition("!Bash(rm *)", p) is False


def test_not_prefix_passes():
    p = _payload(tool_name="Bash", tool_input="git status")
    assert matches_condition("!Bash(rm *)", p) is True


def test_or_array():
    p = _payload(tool_name="Write", tool_input="foo.py")
    assert matches_condition(["Bash(*)", "Write(*)"], p) is True


def test_or_array_no_match():
    p = _payload(tool_name="Read", tool_input="foo.py")
    assert matches_condition(["Bash(*)", "Write(*)"], p) is False


def test_nested_data_field():
    p = _payload(user={"role": "admin"})
    assert matches_condition("data.user.role=admin", p) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_condition.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'breadmind.hooks.condition'`

- [ ] **Step 3: Implement condition module**

```python
# src/breadmind/hooks/condition.py
from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any

from breadmind.hooks.events import HookPayload

_TOOL_RE = re.compile(r"^(\w+)(?:\((.+)\))?$")
_DATA_RE = re.compile(r"^data\.([\w.]+)=(.+)$")
_EVENT_RE = re.compile(r"^event=(.+)$")


def _resolve_nested(data: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    obj: Any = data
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def _matches_single(cond: str, payload: HookPayload) -> bool:
    negate = False
    if cond.startswith("!"):
        negate = True
        cond = cond[1:]

    result = _eval_condition(cond, payload)
    return not result if negate else result


def _eval_condition(cond: str, payload: HookPayload) -> bool:
    m = _EVENT_RE.match(cond)
    if m:
        return payload.event.value == m.group(1)

    m = _DATA_RE.match(cond)
    if m:
        val = _resolve_nested(payload.data, m.group(1))
        return str(val) == m.group(2) if val is not None else False

    m = _TOOL_RE.match(cond)
    if m:
        tool_name_pat = m.group(1)
        arg_pat = m.group(2)
        actual_tool = payload.data.get("tool_name", "")
        if not fnmatch(actual_tool, tool_name_pat):
            return False
        if arg_pat is None:
            return True
        actual_input = str(payload.data.get("tool_input", ""))
        return fnmatch(actual_input, arg_pat)

    return False


def matches_condition(
    condition: str | list[str] | None,
    payload: HookPayload,
) -> bool:
    if condition is None:
        return True
    if isinstance(condition, list):
        return any(_matches_single(c, payload) for c in condition)
    return _matches_single(condition, payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/hooks/test_condition.py -v`
Expected: All 18 PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/hooks/condition.py tests/hooks/test_condition.py
git commit -m "feat(hooks): add conditional filtering module with CC-compat syntax"
```

---

### Task 2: Integrate Condition Filtering into HookChain + Existing Handlers

**Files:**
- Modify: `src/breadmind/hooks/handler.py` (add `if_condition` to PythonHook/ShellHook)
- Modify: `src/breadmind/hooks/chain.py` (check condition before running handler)
- Test: `tests/hooks/test_chain_condition.py`

- [ ] **Step 1: Write failing test**

```python
# tests/hooks/test_chain_condition.py
import pytest
from breadmind.hooks.chain import HookChain
from breadmind.hooks.decision import DecisionKind, HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook


def _make_hook(name, event, decision, priority=0, if_condition=None):
    return PythonHook(
        name=name, event=event, handler=lambda p: decision,
        priority=priority, if_condition=if_condition,
    )


async def test_condition_skips_non_matching_handler():
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[
        _make_hook("blocker", HookEvent.PRE_TOOL_USE,
                   HookDecision.block("nope"),
                   if_condition="Bash(rm *)"),
    ])
    payload = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        data={"tool_name": "Read", "tool_input": "foo.py"},
    )
    decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.PROCEED


async def test_condition_fires_matching_handler():
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[
        _make_hook("blocker", HookEvent.PRE_TOOL_USE,
                   HookDecision.block("blocked"),
                   if_condition="Bash(rm *)"),
    ])
    payload = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        data={"tool_name": "Bash", "tool_input": "rm -rf /tmp"},
    )
    decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.BLOCK


async def test_no_condition_always_fires():
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[
        _make_hook("always", HookEvent.PRE_TOOL_USE,
                   HookDecision.block("always blocked")),
    ])
    payload = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        data={"tool_name": "Read", "tool_input": "x.py"},
    )
    decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.BLOCK


async def test_shell_hook_with_condition():
    """ShellHook should also have if_condition field."""
    from breadmind.hooks.handler import ShellHook
    hook = ShellHook(
        name="sh", event=HookEvent.PRE_TOOL_USE,
        command="echo ok", if_condition="Bash(*)",
    )
    assert hook.if_condition == "Bash(*)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_chain_condition.py -v`
Expected: FAIL — `TypeError: PythonHook.__init__() got an unexpected keyword argument 'if_condition'`

- [ ] **Step 3: Add if_condition field to PythonHook and ShellHook**

In `src/breadmind/hooks/handler.py`, add to both dataclasses:

```python
# In PythonHook dataclass, after timeout_sec:
    if_condition: str | list[str] | None = None

# In ShellHook dataclass, after shell:
    if_condition: str | list[str] | None = None
```

- [ ] **Step 4: Integrate condition check into HookChain.run()**

In `src/breadmind/hooks/chain.py`, add import at top:

```python
from breadmind.hooks.condition import matches_condition
```

In the `for handler in self._sorted():` loop, add before `t0 = _time.perf_counter()`:

```python
            if_cond = getattr(handler, "if_condition", None)
            if if_cond is not None and not matches_condition(if_cond, payload):
                continue
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/hooks/test_chain_condition.py tests/hooks/test_chain.py -v`
Expected: All PASS (new tests + existing chain tests unbroken)

- [ ] **Step 6: Commit**

```bash
git add src/breadmind/hooks/handler.py src/breadmind/hooks/chain.py tests/hooks/test_chain_condition.py
git commit -m "feat(hooks): integrate conditional filtering into HookChain"
```

---

### Task 3: SSRF Guard Module

**Files:**
- Create: `src/breadmind/hooks/http_guard.py`
- Test: `tests/hooks/test_http_guard.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hooks/test_http_guard.py
import pytest
from breadmind.hooks.http_guard import validate_url, SSRFError


def test_allow_public_https():
    validate_url("https://example.com/webhook")


def test_block_localhost():
    with pytest.raises(SSRFError, match="private"):
        validate_url("http://127.0.0.1/hook")


def test_block_private_10():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://10.0.0.1/hook")


def test_block_private_172():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://172.16.0.1/hook")


def test_block_private_192():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://192.168.1.1/hook")


def test_block_link_local():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://169.254.169.254/latest/meta-data/")


def test_block_http_by_default():
    with pytest.raises(SSRFError, match="HTTPS"):
        validate_url("http://example.com/webhook")


def test_allow_http_when_permitted():
    validate_url("http://example.com/webhook", allow_http=True)


def test_allowed_hosts_strict_pass():
    validate_url("https://hooks.slack.com/x", allowed_hosts=["hooks.slack.com"])


def test_allowed_hosts_strict_fail():
    with pytest.raises(SSRFError, match="not in allowed"):
        validate_url("https://evil.com/x", allowed_hosts=["hooks.slack.com"])


def test_block_ipv6_loopback():
    with pytest.raises(SSRFError, match="private"):
        validate_url("https://[::1]/hook")


def test_allow_public_ip():
    validate_url("https://8.8.8.8/hook")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_http_guard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SSRF guard**

```python
# src/breadmind/hooks/http_guard.py
from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class SSRFError(Exception):
    pass


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fd00::/8"),
]


def _is_private_ip(host: str) -> bool:
    host = host.strip("[]")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


def validate_url(
    url: str,
    *,
    allow_http: bool = False,
    allowed_hosts: list[str] | None = None,
) -> None:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https"):
        raise SSRFError(f"Unsupported scheme: {scheme}")
    if not allow_http and scheme == "http":
        raise SSRFError("HTTPS required (set allow_http=True to override)")

    hostname = parsed.hostname or ""
    if not hostname:
        raise SSRFError("No hostname in URL")

    if _is_private_ip(hostname):
        raise SSRFError(f"Host {hostname} resolves to private/reserved IP")

    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise SSRFError(f"Host {hostname} not in allowed hosts list")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/hooks/test_http_guard.py -v`
Expected: All 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/hooks/http_guard.py tests/hooks/test_http_guard.py
git commit -m "feat(hooks): add SSRF guard for HttpHook"
```

---

### Task 4: HttpHook Handler

**Files:**
- Create: `src/breadmind/hooks/http_hook.py`
- Test: `tests/hooks/test_http_hook.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hooks/test_http_hook.py
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from breadmind.hooks.decision import DecisionKind
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.http_hook import HttpHook


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


def _mock_response(status=200, body=None):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body or {"action": "proceed"})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


@pytest.fixture
def hook():
    return HttpHook(
        name="webhook", event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/hook",
        headers={"X-Secret": "test"},
    )


async def test_proceed_on_success(hook):
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        session.request = MagicMock(return_value=_mock_response(200, {"action": "proceed"}))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = session
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.PROCEED


async def test_block_on_response(hook):
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        session.request = MagicMock(return_value=_mock_response(
            200, {"action": "block", "reason": "denied"}
        ))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = session
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK
    assert "denied" in d.reason


async def test_non_2xx_failure(hook):
    with patch("aiohttp.ClientSession") as MockSession:
        session = AsyncMock()
        session.request = MagicMock(return_value=_mock_response(500))
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        MockSession.return_value = session
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK


async def test_ssrf_blocked():
    hook = HttpHook(
        name="evil", event=HookEvent.PRE_TOOL_USE,
        url="https://127.0.0.1/hook",
    )
    d = await hook.run(_payload())
    assert d.kind == DecisionKind.BLOCK
    assert "private" in d.reason.lower() or "ssrf" in d.reason.lower()


async def test_env_var_interpolation():
    import os
    os.environ["TEST_HOOK_SECRET"] = "s3cret"
    hook = HttpHook(
        name="env", event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/hook",
        headers={"Authorization": "Bearer $TEST_HOOK_SECRET"},
    )
    assert hook._interpolate_env("Bearer $TEST_HOOK_SECRET") == "Bearer s3cret"
    del os.environ["TEST_HOOK_SECRET"]


async def test_if_condition_field():
    hook = HttpHook(
        name="cond", event=HookEvent.PRE_TOOL_USE,
        url="https://example.com", if_condition="Bash(*)",
    )
    assert hook.if_condition == "Bash(*)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_http_hook.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement HttpHook**

```python
# src/breadmind/hooks/http_hook.py
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field

import aiohttp

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import _failure_decision, _parse_shell_decision
from breadmind.hooks.http_guard import SSRFError, validate_url

logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{?(\w+)\}?")


@dataclass
class HttpHook:
    name: str
    event: HookEvent
    url: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 10.0
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "POST"
    allow_http: bool = False
    allowed_hosts: list[str] | None = None
    if_condition: str | list[str] | None = None

    def _interpolate_env(self, value: str) -> str:
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)

    async def run(self, payload: HookPayload) -> HookDecision:
        url = self._interpolate_env(self.url)
        try:
            validate_url(url, allow_http=self.allow_http, allowed_hosts=self.allowed_hosts)
        except SSRFError as e:
            d = _failure_decision(self.event, f"SSRF blocked: {e}")
            d.hook_id = self.name
            return d

        headers = {k: self._interpolate_env(v) for k, v in self.headers.items()}
        headers.setdefault("Content-Type", "application/json")
        body = json.dumps(
            {"event": payload.event.value, "data": payload.data, "hook_name": self.name},
            default=str,
        )

        try:
            async with aiohttp.ClientSession() as session:
                resp_ctx = session.request(
                    self.method, url, data=body, headers=headers,
                )
                async with resp_ctx as resp:
                    if resp.status >= 400:
                        reason = f"HTTP {resp.status} from {url}"
                        d = _failure_decision(self.event, reason)
                        d.hook_id = self.name
                        return d
                    resp_json = await resp.json()
        except asyncio.TimeoutError:
            d = _failure_decision(self.event, f"http hook '{self.name}' timeout")
            d.hook_id = self.name
            return d
        except Exception as e:
            d = _failure_decision(self.event, f"http hook '{self.name}' error: {e}")
            d.hook_id = self.name
            return d

        stdout = json.dumps(resp_json)
        decision = _parse_shell_decision(stdout, self.event)
        decision.hook_id = self.name
        return decision
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/hooks/test_http_hook.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/hooks/http_hook.py tests/hooks/test_http_hook.py
git commit -m "feat(hooks): add HttpHook handler with SSRF guard"
```

---

### Task 5: PromptHook Handler

**Files:**
- Create: `src/breadmind/hooks/prompt_hook.py`
- Test: `tests/hooks/test_prompt_hook.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hooks/test_prompt_hook.py
import pytest
from unittest.mock import AsyncMock, patch

from breadmind.hooks.decision import DecisionKind
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.prompt_hook import PromptHook


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


def _make_hook(**overrides):
    defaults = dict(
        name="prompt-guard",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Is {{ tool_name }} safe? Respond JSON {ok, reason}.",
        timeout_sec=5.0,
    )
    defaults.update(overrides)
    return PromptHook(**defaults)


async def test_ok_true_proceeds():
    hook = _make_hook()
    with patch.object(hook, "_call_llm", new_callable=AsyncMock,
                      return_value='{"ok": true, "reason": "safe"}'):
        d = await hook.run(_payload(tool_name="Read"))
    assert d.kind == DecisionKind.PROCEED
    assert "safe" in d.context


async def test_ok_false_blocks():
    hook = _make_hook()
    with patch.object(hook, "_call_llm", new_callable=AsyncMock,
                      return_value='{"ok": false, "reason": "dangerous"}'):
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK
    assert "dangerous" in d.reason


async def test_non_json_response_proceeds():
    hook = _make_hook()
    with patch.object(hook, "_call_llm", new_callable=AsyncMock,
                      return_value="I think it's fine"):
        d = await hook.run(_payload(tool_name="Read"))
    assert d.kind == DecisionKind.PROCEED


async def test_timeout_uses_failure_decision():
    import asyncio
    hook = _make_hook(timeout_sec=0.01)
    async def slow(*a, **kw):
        await asyncio.sleep(1)
        return '{"ok": true}'
    with patch.object(hook, "_call_llm", side_effect=slow):
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK


async def test_jinja_template_renders():
    hook = _make_hook(prompt="Tool={{ tool_name }}, event={{ event }}")
    rendered = hook._render_prompt(_payload(tool_name="Write"))
    assert "Tool=Write" in rendered
    assert "event=pre_tool_use" in rendered


async def test_observational_event_proceeds_on_failure():
    hook = _make_hook(event=HookEvent.POST_TOOL_USE)
    with patch.object(hook, "_call_llm", new_callable=AsyncMock,
                      side_effect=Exception("boom")):
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.PROCEED


async def test_if_condition_field():
    hook = _make_hook(if_condition="Bash(*)")
    assert hook.if_condition == "Bash(*)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_prompt_hook.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement PromptHook**

```python
# src/breadmind/hooks/prompt_hook.py
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload, is_blockable
from breadmind.hooks.handler import _failure_decision

logger = logging.getLogger(__name__)


@dataclass
class PromptHook:
    name: str
    event: HookEvent
    prompt: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 15.0
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    endpoint: str | None = None
    if_condition: str | list[str] | None = None

    def _render_prompt(self, payload: HookPayload) -> str:
        try:
            from jinja2 import Template
            tpl = Template(self.prompt)
        except ImportError:
            tpl = None

        ctx: dict[str, Any] = {
            "event": payload.event.value,
            "data": payload.data,
            "tool_name": payload.data.get("tool_name", ""),
            "args": payload.data.get("tool_input", ""),
        }

        if tpl is not None:
            return tpl.render(**ctx)

        result = self.prompt
        for k, v in ctx.items():
            result = result.replace("{{ " + k + " }}", str(v))
        return result

    async def _call_llm(self, rendered_prompt: str) -> str:
        if self.endpoint and self.api_key:
            return await self._call_direct(rendered_prompt)
        return await self._call_provider(rendered_prompt)

    async def _call_direct(self, prompt: str) -> str:
        import aiohttp
        import os
        api_key = os.environ.get(self.api_key.lstrip("$"), self.api_key) if self.api_key else ""
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 256}
        if self.model:
            body["model"] = self.model
        async with aiohttp.ClientSession() as session:
            async with session.post(self.endpoint, json=body, headers=headers) as resp:
                data = await resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def _call_provider(self, prompt: str) -> str:
        try:
            from breadmind.llm.factory import create_provider
            provider_name = self.provider or "default"
            provider = create_provider(provider_name)
            messages = [{"role": "user", "content": prompt}]
            kwargs: dict[str, Any] = {}
            if self.model:
                kwargs["model"] = self.model
            result = await provider.chat(messages, **kwargs)
            if isinstance(result, dict):
                return result.get("content", str(result))
            return str(result)
        except Exception as e:
            raise RuntimeError(f"LLM call failed: {e}") from e

    def _parse_response(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    async def run(self, payload: HookPayload) -> HookDecision:
        rendered = self._render_prompt(payload)
        try:
            async def _invoke():
                raw = await self._call_llm(rendered)
                return self._parse_response(raw)

            result = await asyncio.wait_for(_invoke(), timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            d = _failure_decision(self.event, f"prompt hook '{self.name}' timeout")
            d.hook_id = self.name
            return d
        except Exception as e:
            d = _failure_decision(self.event, f"prompt hook '{self.name}' error: {e}")
            d.hook_id = self.name
            return d

        ok = result.get("ok", True)
        reason = result.get("reason", "")

        if not ok:
            if is_blockable(self.event):
                d = HookDecision.block(reason or "blocked by prompt hook")
            else:
                logger.warning("PromptHook %s: ok=false on observational event; proceeding", self.name)
                d = HookDecision.proceed(context=reason)
        else:
            d = HookDecision.proceed(context=reason)

        d.hook_id = self.name
        return d
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/hooks/test_prompt_hook.py -v`
Expected: All 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/hooks/prompt_hook.py tests/hooks/test_prompt_hook.py
git commit -m "feat(hooks): add PromptHook LLM-based handler"
```

---

### Task 6: AgentHook Handler

**Files:**
- Create: `src/breadmind/hooks/agent_hook.py`
- Test: `tests/hooks/test_agent_hook.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/hooks/test_agent_hook.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from breadmind.hooks.decision import DecisionKind
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.agent_hook import AgentHook, READONLY_TOOLS


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


def _make_hook(**overrides):
    defaults = dict(
        name="agent-verifier",
        event=HookEvent.PRE_TOOL_USE,
        prompt="Check if the tool call is safe.",
        max_turns=3,
        timeout_sec=10.0,
    )
    defaults.update(overrides)
    return AgentHook(**defaults)


def test_readonly_preset():
    assert "Read" in READONLY_TOOLS
    assert "Grep" in READONLY_TOOLS
    assert "Glob" in READONLY_TOOLS


def test_resolve_tools_readonly():
    hook = _make_hook(allowed_tools="readonly")
    assert hook._resolve_allowed_tools() == READONLY_TOOLS


def test_resolve_tools_explicit_list():
    hook = _make_hook(allowed_tools=["Read", "Bash"])
    assert hook._resolve_allowed_tools() == ["Read", "Bash"]


def test_resolve_tools_all():
    hook = _make_hook(allowed_tools="all")
    assert hook._resolve_allowed_tools() is None


async def test_ok_true_proceeds():
    hook = _make_hook()
    with patch.object(hook, "_run_agent_loop", new_callable=AsyncMock,
                      return_value={"ok": True, "reason": "safe"}):
        d = await hook.run(_payload(tool_name="Read"))
    assert d.kind == DecisionKind.PROCEED


async def test_ok_false_blocks():
    hook = _make_hook()
    with patch.object(hook, "_run_agent_loop", new_callable=AsyncMock,
                      return_value={"ok": False, "reason": "risky operation"}):
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK
    assert "risky" in d.reason


async def test_timeout_blocks():
    import asyncio
    hook = _make_hook(timeout_sec=0.01)
    async def slow(*a, **kw):
        await asyncio.sleep(1)
        return {"ok": True}
    with patch.object(hook, "_run_agent_loop", side_effect=slow):
        d = await hook.run(_payload(tool_name="Bash"))
    assert d.kind == DecisionKind.BLOCK


async def test_exhausted_turns_proceeds():
    hook = _make_hook()
    with patch.object(hook, "_run_agent_loop", new_callable=AsyncMock,
                      return_value={}):
        d = await hook.run(_payload(tool_name="Read"))
    assert d.kind == DecisionKind.PROCEED


async def test_if_condition_field():
    hook = _make_hook(if_condition=["Bash(*)", "Write(*)"])
    assert hook.if_condition == ["Bash(*)", "Write(*)"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_agent_hook.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AgentHook**

```python
# src/breadmind/hooks/agent_hook.py
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from breadmind.hooks.decision import HookDecision
from breadmind.hooks.events import HookEvent, HookPayload, is_blockable
from breadmind.hooks.handler import _failure_decision

logger = logging.getLogger(__name__)

READONLY_TOOLS = ["Read", "Grep", "Glob"]

_SYSTEM_PROMPT = (
    "You are a hook verifier agent. Your task is to check conditions using "
    "available tools. After checking, respond with ONLY a JSON object: "
    '{"ok": true/false, "reason": "explanation"}. '
    "Do NOT include any other text outside the JSON."
)


@dataclass
class AgentHook:
    name: str
    event: HookEvent
    prompt: str
    priority: int = 0
    tool_pattern: str | None = None
    timeout_sec: float = 30.0
    max_turns: int = 3
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | str = "readonly"
    if_condition: str | list[str] | None = None

    def _resolve_allowed_tools(self) -> list[str] | None:
        if self.allowed_tools == "readonly":
            return list(READONLY_TOOLS)
        if self.allowed_tools == "all":
            return None
        if isinstance(self.allowed_tools, list):
            return list(self.allowed_tools)
        return list(READONLY_TOOLS)

    async def _get_provider(self):
        from breadmind.llm.factory import create_provider
        return create_provider(self.provider or "default")

    def _build_tools_schema(self, allowed: list[str] | None) -> list[dict]:
        try:
            from breadmind.tools.registry import ToolRegistry
            registry = ToolRegistry.instance()
            all_tools = registry.list_tools()
            if allowed is None:
                return [t.schema() for t in all_tools if hasattr(t, "schema")]
            return [
                t.schema() for t in all_tools
                if hasattr(t, "schema") and t.name in allowed
            ]
        except Exception:
            return []

    async def _run_agent_loop(
        self, user_prompt: str, payload: HookPayload,
    ) -> dict[str, Any]:
        llm = await self._get_provider()
        allowed = self._resolve_allowed_tools()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {}
        if self.model:
            kwargs["model"] = self.model

        for _ in range(self.max_turns):
            result = await llm.chat(messages, **kwargs)
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            tool_calls = result.get("tool_calls", []) if isinstance(result, dict) else []

            if not tool_calls:
                return self._extract_json(content)

            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                tool_name = tc.get("function", {}).get("name", "")
                if allowed is not None and tool_name not in allowed:
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""),
                        "content": f"Tool '{tool_name}' not allowed in this hook context.",
                    })
                    continue
                try:
                    from breadmind.tools.registry import ToolRegistry
                    registry = ToolRegistry.instance()
                    tool_result = await registry.execute(
                        tool_name, json.loads(tc.get("function", {}).get("arguments", "{}"))
                    )
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""),
                        "content": str(tool_result),
                    })
                except Exception as e:
                    messages.append({
                        "role": "tool", "tool_call_id": tc.get("id", ""),
                        "content": f"Error: {e}",
                    })

        return {}

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}

    async def run(self, payload: HookPayload) -> HookDecision:
        context_info = json.dumps(payload.data, default=str)[:2000]
        user_prompt = f"{self.prompt}\n\nContext:\n{context_info}"

        try:
            result = await asyncio.wait_for(
                self._run_agent_loop(user_prompt, payload),
                timeout=self.timeout_sec,
            )
        except asyncio.TimeoutError:
            d = _failure_decision(self.event, f"agent hook '{self.name}' timeout")
            d.hook_id = self.name
            return d
        except Exception as e:
            d = _failure_decision(self.event, f"agent hook '{self.name}' error: {e}")
            d.hook_id = self.name
            return d

        ok = result.get("ok", True)
        reason = result.get("reason", "")

        if not result:
            d = HookDecision.proceed(context="agent exhausted turns without verdict")
            d.hook_id = self.name
            return d

        if not ok:
            if is_blockable(self.event):
                d = HookDecision.block(reason or "blocked by agent hook")
            else:
                logger.warning("AgentHook %s: ok=false on observational event", self.name)
                d = HookDecision.proceed(context=reason)
        else:
            d = HookDecision.proceed(context=reason)

        d.hook_id = self.name
        return d
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/hooks/test_agent_hook.py -v`
Expected: All 10 PASS

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/hooks/agent_hook.py tests/hooks/test_agent_hook.py
git commit -m "feat(hooks): add AgentHook multi-turn verifier handler"
```

---

### Task 7: Registry, Manifest, Routes & SDUI Integration

**Files:**
- Modify: `src/breadmind/hooks/registry.py`
- Modify: `src/breadmind/hooks/manifest.py`
- Modify: `src/breadmind/hooks/__init__.py`
- Modify: `src/breadmind/web/routes/hooks.py`
- Modify: `src/breadmind/sdui/views/hooks_view.py`
- Test: `tests/hooks/test_registry_new_types.py`

- [ ] **Step 1: Write failing test**

```python
# tests/hooks/test_registry_new_types.py
import pytest
from breadmind.hooks.db_store import HookOverride
from breadmind.hooks.events import HookEvent
from breadmind.hooks.registry import HookRegistry


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows
    async def list_all(self):
        return list(self._rows)
    async def list_by_event(self, event):
        return [r for r in self._rows if r.event == event]
    async def insert(self, ov):
        self._rows.append(ov)
    async def delete(self, hook_id):
        self._rows = [r for r in self._rows if r.hook_id != hook_id]


async def test_build_prompt_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="llm-guard", source="user", event="pre_tool_use",
            type="prompt", tool_pattern=None, priority=50, enabled=True,
            config_json={"prompt": "Is this safe?", "model": "gemini-2.5-flash"},
        ),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    h = chain.handlers[0]
    assert h.name == "llm-guard"
    assert h.__class__.__name__ == "PromptHook"


async def test_build_http_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="webhook", source="user", event="pre_tool_use",
            type="http", tool_pattern=None, priority=30, enabled=True,
            config_json={"url": "https://example.com/hook", "headers": {"X-Key": "val"}},
        ),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    h = chain.handlers[0]
    assert h.__class__.__name__ == "HttpHook"


async def test_build_agent_hook_from_db():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="agent-check", source="user", event="pre_tool_use",
            type="agent", tool_pattern=None, priority=20, enabled=True,
            config_json={"prompt": "Verify safety", "max_turns": 2, "allowed_tools": "readonly"},
        ),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 1
    h = chain.handlers[0]
    assert h.__class__.__name__ == "AgentHook"
    assert h.max_turns == 2


async def test_unknown_type_still_skipped():
    reg = HookRegistry(store=_FakeStore([
        HookOverride(
            hook_id="bad", source="user", event="pre_tool_use",
            type="unknown_type", tool_pattern=None, priority=0, enabled=True,
            config_json={},
        ),
    ]))
    await reg.reload()
    chain = reg.build_chain(HookEvent.PRE_TOOL_USE)
    assert len(chain.handlers) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/hooks/test_registry_new_types.py -v`
Expected: FAIL — PromptHook not being built from `_build_from_override`

- [ ] **Step 3: Update registry.py**

In `src/breadmind/hooks/registry.py`, add imports:

```python
from breadmind.hooks.http_hook import HttpHook
from breadmind.hooks.prompt_hook import PromptHook
from breadmind.hooks.agent_hook import AgentHook
```

Replace `_build_from_override` method with:

```python
    @staticmethod
    def _build_from_override(ov: HookOverride, event: HookEvent) -> HookHandler | None:
        cfg = ov.config_json or {}
        if_cond = cfg.get("if") or cfg.get("if_condition")

        if ov.type == "shell":
            command = cfg.get("command", "")
            if not command:
                logger.warning("DB shell hook %r missing command", ov.hook_id)
                return None
            return ShellHook(
                name=ov.hook_id, event=event, command=command,
                priority=ov.priority, tool_pattern=ov.tool_pattern,
                timeout_sec=float(cfg.get("timeout_sec", 10.0)),
                shell=cfg.get("shell", "auto"),
                if_condition=if_cond,
            )

        if ov.type == "prompt":
            prompt_text = cfg.get("prompt", "")
            if not prompt_text:
                logger.warning("DB prompt hook %r missing prompt", ov.hook_id)
                return None
            return PromptHook(
                name=ov.hook_id, event=event, prompt=prompt_text,
                priority=ov.priority, tool_pattern=ov.tool_pattern,
                timeout_sec=float(cfg.get("timeout_sec", 15.0)),
                provider=cfg.get("provider"),
                model=cfg.get("model"),
                api_key=cfg.get("api_key"),
                endpoint=cfg.get("endpoint"),
                if_condition=if_cond,
            )

        if ov.type == "agent":
            prompt_text = cfg.get("prompt", "")
            if not prompt_text:
                logger.warning("DB agent hook %r missing prompt", ov.hook_id)
                return None
            allowed = cfg.get("allowed_tools", "readonly")
            return AgentHook(
                name=ov.hook_id, event=event, prompt=prompt_text,
                priority=ov.priority, tool_pattern=ov.tool_pattern,
                timeout_sec=float(cfg.get("timeout_sec", 30.0)),
                max_turns=int(cfg.get("max_turns", 3)),
                provider=cfg.get("provider"),
                model=cfg.get("model"),
                allowed_tools=allowed,
                if_condition=if_cond,
            )

        if ov.type == "http":
            url = cfg.get("url", "")
            if not url:
                logger.warning("DB http hook %r missing url", ov.hook_id)
                return None
            return HttpHook(
                name=ov.hook_id, event=event, url=url,
                priority=ov.priority, tool_pattern=ov.tool_pattern,
                timeout_sec=float(cfg.get("timeout_sec", 10.0)),
                headers=cfg.get("headers", {}),
                method=cfg.get("method", "POST"),
                allow_http=cfg.get("allow_http", False),
                allowed_hosts=cfg.get("allowed_hosts"),
                if_condition=if_cond,
            )

        if ov.type == "python":
            logger.warning("DB-only Python hook %r not supported", ov.hook_id)
            return None

        logger.warning("Unknown override type %r", ov.type)
        return None
```

- [ ] **Step 4: Update manifest.py to parse new types**

In `src/breadmind/hooks/manifest.py`, add imports:

```python
from breadmind.hooks.http_hook import HttpHook
from breadmind.hooks.prompt_hook import PromptHook
from breadmind.hooks.agent_hook import AgentHook
```

In the `load_hooks_from_manifest` function, after the `elif hook_type == "python":` block and before the `else:`, add:

```python
        elif hook_type == "prompt":
            prompt_text = entry.get("prompt", "")
            if not prompt_text:
                logger.warning("Prompt hook %s missing prompt; skipping", name)
                continue
            out.append(PromptHook(
                name=name, event=ev, prompt=prompt_text,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                provider=entry.get("provider"),
                model=entry.get("model"),
                if_condition=entry.get("if"),
            ))
        elif hook_type == "agent":
            prompt_text = entry.get("prompt", "")
            if not prompt_text:
                logger.warning("Agent hook %s missing prompt; skipping", name)
                continue
            out.append(AgentHook(
                name=name, event=ev, prompt=prompt_text,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                max_turns=int(entry.get("max_turns", 3)),
                allowed_tools=entry.get("allowed_tools", "readonly"),
                if_condition=entry.get("if"),
            ))
        elif hook_type == "http":
            url = entry.get("url", "")
            if not url:
                logger.warning("HTTP hook %s missing url; skipping", name)
                continue
            out.append(HttpHook(
                name=name, event=ev, url=url,
                priority=priority, tool_pattern=tool_pattern,
                timeout_sec=timeout,
                headers=entry.get("headers", {}),
                method=entry.get("method", "POST"),
                if_condition=entry.get("if"),
            ))
```

- [ ] **Step 5: Update __init__.py exports**

In `src/breadmind/hooks/__init__.py`, add:

```python
from breadmind.hooks.agent_hook import AgentHook
from breadmind.hooks.condition import matches_condition
from breadmind.hooks.http_hook import HttpHook
from breadmind.hooks.prompt_hook import PromptHook
```

And add to `__all__`:
```python
    "AgentHook",
    "HttpHook",
    "PromptHook",
    "matches_condition",
```

- [ ] **Step 6: Update web routes validation**

In `src/breadmind/web/routes/hooks.py`, change line 95:

```python
    if body.type not in {"shell", "python", "prompt", "agent", "http"}:
```

- [ ] **Step 7: Update SDUI hooks_view type options**

In `src/breadmind/sdui/views/hooks_view.py`, replace `_TYPE_OPTIONS`:

```python
_TYPE_OPTIONS = [
    {"value": "shell", "label": "shell"},
    {"value": "prompt", "label": "prompt (LLM)"},
    {"value": "agent", "label": "agent (multi-turn)"},
    {"value": "http", "label": "http (webhook)"},
]
```

- [ ] **Step 8: Run all tests**

Run: `python -m pytest tests/hooks/ -v`
Expected: All PASS (new + existing)

- [ ] **Step 9: Commit**

```bash
git add src/breadmind/hooks/registry.py src/breadmind/hooks/manifest.py \
  src/breadmind/hooks/__init__.py src/breadmind/web/routes/hooks.py \
  src/breadmind/sdui/views/hooks_view.py tests/hooks/test_registry_new_types.py
git commit -m "feat(hooks): wire prompt/agent/http types into registry, manifest, routes, SDUI"
```

---

### Task 8: End-to-End Integration Tests

**Files:**
- Create: `tests/hooks/test_hooks_v3_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/hooks/test_hooks_v3_integration.py
"""End-to-end: HookChain + new handler types + conditional filtering."""
import pytest
from unittest.mock import AsyncMock, patch

from breadmind.hooks.chain import HookChain
from breadmind.hooks.decision import DecisionKind, HookDecision
from breadmind.hooks.events import HookEvent, HookPayload
from breadmind.hooks.handler import PythonHook, ShellHook
from breadmind.hooks.prompt_hook import PromptHook
from breadmind.hooks.agent_hook import AgentHook
from breadmind.hooks.http_hook import HttpHook


def _payload(**data) -> HookPayload:
    return HookPayload(event=HookEvent.PRE_TOOL_USE, data=data)


async def test_mixed_handler_chain_with_conditions():
    """Python + Shell + Prompt hooks, only matching conditions fire."""
    py = PythonHook(
        name="py-pass", event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.proceed(context="py-ok"),
        priority=100,
    )
    prompt = PromptHook(
        name="prompt-guard", event=HookEvent.PRE_TOOL_USE,
        prompt="check", priority=50,
        if_condition="Bash(rm *)",
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[py, prompt])
    payload = _payload(tool_name="Read", tool_input="foo.py")
    with patch.object(prompt, "_call_llm", new_callable=AsyncMock,
                      return_value='{"ok": false, "reason": "block"}'):
        decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.PROCEED
    assert "py-ok" in decision.context


async def test_prompt_hook_blocks_in_chain():
    prompt = PromptHook(
        name="prompt-block", event=HookEvent.PRE_TOOL_USE,
        prompt="check", priority=100,
        if_condition="Bash(*)",
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[prompt])
    payload = _payload(tool_name="Bash", tool_input="rm -rf /")
    with patch.object(prompt, "_call_llm", new_callable=AsyncMock,
                      return_value='{"ok": false, "reason": "dangerous"}'):
        decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.BLOCK
    assert "dangerous" in decision.reason


async def test_http_hook_in_chain():
    import json
    http = HttpHook(
        name="webhook", event=HookEvent.PRE_TOOL_USE,
        url="https://example.com/hook", priority=80,
        if_condition="Write(*)",
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[http])
    payload = _payload(tool_name="Write", tool_input="secret.py")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"action": "block", "reason": "no writes"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.request = lambda *a, **kw: mock_resp
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.BLOCK


async def test_agent_hook_in_chain():
    agent = AgentHook(
        name="agent-v", event=HookEvent.PRE_TOOL_USE,
        prompt="verify", priority=90,
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[agent])
    payload = _payload(tool_name="Bash", tool_input="echo hi")

    with patch.object(agent, "_run_agent_loop", new_callable=AsyncMock,
                      return_value={"ok": True, "reason": "safe"}):
        decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.PROCEED


async def test_priority_ordering_with_mixed_types():
    """Higher priority runs first; prompt blocks before python runs."""
    prompt = PromptHook(
        name="high-pri", event=HookEvent.PRE_TOOL_USE,
        prompt="x", priority=100,
    )
    py = PythonHook(
        name="low-pri", event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.proceed(), priority=10,
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[py, prompt])
    payload = _payload(tool_name="Bash", tool_input="test")

    with patch.object(prompt, "_call_llm", new_callable=AsyncMock,
                      return_value='{"ok": false, "reason": "nope"}'):
        decision, _ = await chain.run(payload)
    assert decision.kind == DecisionKind.BLOCK


async def test_or_condition_with_multiple_patterns():
    py = PythonHook(
        name="multi-cond", event=HookEvent.PRE_TOOL_USE,
        handler=lambda p: HookDecision.block("caught"),
        priority=100,
        if_condition=["Bash(rm *)", "Write(*.env)"],
    )
    chain = HookChain(event=HookEvent.PRE_TOOL_USE, handlers=[py])

    d1, _ = await chain.run(_payload(tool_name="Read", tool_input="x.py"))
    assert d1.kind == DecisionKind.PROCEED

    d2, _ = await chain.run(_payload(tool_name="Write", tool_input=".env"))
    assert d2.kind == DecisionKind.BLOCK

    d3, _ = await chain.run(_payload(tool_name="Bash", tool_input="rm -rf /"))
    assert d3.kind == DecisionKind.BLOCK
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/hooks/test_hooks_v3_integration.py -v`
Expected: All 6 PASS

- [ ] **Step 3: Run full hooks test suite**

Run: `python -m pytest tests/hooks/ -v --tb=short`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add tests/hooks/test_hooks_v3_integration.py
git commit -m "test(hooks): add v3 end-to-end integration tests"
```

---

## Self-Review

**Spec coverage:**
- PromptHook: Task 5 ✓
- AgentHook: Task 6 ✓
- HttpHook: Task 4 ✓
- SSRF guard: Task 3 ✓
- Conditional filtering: Task 1 ✓
- Chain integration: Task 2 ✓
- Registry/manifest/routes/SDUI: Task 7 ✓
- Integration tests: Task 8 ✓

**Placeholder scan:** No TBD/TODO/placeholders found.

**Type consistency:** All handler types use same `if_condition: str | list[str] | None = None` field. All use `_failure_decision()` from handler.py. PromptHook/AgentHook share `_parse_response`/`_extract_json` pattern. HttpHook reuses `_parse_shell_decision` from handler.py.
