import json
from pathlib import Path


from breadmind.hooks.manifest import load_hooks_from_manifest


def test_parses_python_and_shell_hooks(tmp_path: Path):
    manifest = {
        "name": "demo",
        "hooks": [
            {
                "name": "block-rm",
                "event": "pre_tool_use",
                "type": "shell",
                "command": "exit 1",
                "tool_pattern": "shell_*",
                "priority": 100,
            },
            {
                "name": "inject-ns",
                "event": "pre_tool_use",
                "type": "python",
                "entry": "tests.hooks.fixtures.hook_handlers:inject_ns",
                "priority": 50,
            },
        ],
    }
    p = tmp_path / "plugin.json"
    p.write_text(json.dumps(manifest))

    hooks = load_hooks_from_manifest(p, resolver=lambda dotted: (lambda payload: None))
    assert len(hooks) == 2
    assert hooks[0].name == "block-rm"
    assert hooks[0].event.value == "pre_tool_use"
    assert hooks[0].__class__.__name__ == "ShellHook"
    assert hooks[0].priority == 100
    assert hooks[1].__class__.__name__ == "PythonHook"


def test_ignores_unknown_event(tmp_path: Path, caplog):
    p = tmp_path / "plugin.json"
    p.write_text(json.dumps({
        "hooks": [{
            "name": "x", "event": "not_an_event", "type": "shell", "command": "x",
        }],
    }))
    hooks = load_hooks_from_manifest(p, resolver=lambda d: None)
    assert hooks == []


def test_missing_hooks_field_is_empty(tmp_path: Path):
    p = tmp_path / "plugin.json"
    p.write_text(json.dumps({"name": "nohooks"}))
    assert load_hooks_from_manifest(p, resolver=lambda d: None) == []
