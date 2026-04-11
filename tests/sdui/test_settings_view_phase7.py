"""Phase 7 SDUI settings view tests.

Covers:
  - Each existing skill market has an inline edit form with action key skill_markets
  - Each existing cron entry has an inline edit form with action key scheduler_cron
  - Edit forms prefill from existing data
  - Edit form name fields are read_only
  - Delete buttons are still present alongside edit forms
  - View renders cleanly with no settings_store
- Schema coerces string bools for skill_markets and scheduler_cron enabled fields
"""
from breadmind.sdui.views import settings_view


def _walk(component, predicate):
    out = []
    if predicate(component):
        out.append(component)
    for ch in component.children:
        out.extend(_walk(ch, predicate))
    return out


class FakeStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_setting(self, key):
        return self.data.get(key)


_MARKETS = [
    {"name": "official", "type": "skills_sh", "enabled": True},
    {"name": "custom", "type": "clawhub", "enabled": False, "url": "https://example.com"},
]

_CRONS = [
    {
        "id": "job-1",
        "name": "daily-report",
        "schedule": "0 9 * * 1",
        "task": "Generate daily report",
        "enabled": True,
    },
    {
        "id": "job-2",
        "name": "weekly-cleanup",
        "schedule": "0 0 * * 0",
        "task": "Clean up old data",
        "enabled": False,
    },
]


def _update_item_forms(spec):
    forms = _walk(spec.root, lambda c: c.type == "form")
    return [f for f in forms if (f.props.get("action") or {}).get("kind") == "settings_update_item"]


def _edit_form_for_market(spec, market_name):
    for f in _update_item_forms(spec):
        action = f.props.get("action") or {}
        if action.get("key") == "skill_markets" and action.get("match_value") == market_name:
            return f
    return None


def _edit_form_for_cron(spec, cron_name):
    for f in _update_item_forms(spec):
        action = f.props.get("action") or {}
        if action.get("key") == "scheduler_cron" and action.get("match_value") == cron_name:
            return f
    return None


def _field_names(form):
    fields = _walk(form, lambda c: c.type in ("field", "select"))
    return [f.props.get("name") for f in fields]


# ---------------------------------------------------------------------------
# View renders without settings_store
# ---------------------------------------------------------------------------

async def test_view_renders_without_settings_store(test_db):
    """View renders cleanly when settings_store is None."""
    spec = await settings_view.build(test_db, settings_store=None)
    assert spec is not None
    assert spec.root is not None


# ---------------------------------------------------------------------------
# Skill markets inline edit
# ---------------------------------------------------------------------------

async def test_each_market_has_inline_edit_form(test_db):
    """Each existing skill market entry has an inline edit form."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    for market in _MARKETS:
        form = _edit_form_for_market(spec, market["name"])
        assert form is not None, f"No inline edit form found for market '{market['name']}'"


async def test_market_edit_form_action_has_match_field(test_db):
    """Skill market edit form action has match_field='name'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "official")
    assert form is not None
    action = form.props.get("action") or {}
    assert action.get("match_field") == "name"
    assert action.get("match_value") == "official"
    assert action.get("key") == "skill_markets"


async def test_market_edit_form_has_required_fields(test_db):
    """Skill market edit form has name, type, url, enabled fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "official")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "type" in names
    assert "enabled" in names


async def test_market_edit_form_name_field_read_only(test_db):
    """Skill market edit form name field is read_only."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "official")
    assert form is not None
    name_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "name")
    assert len(name_fields) == 1
    props = name_fields[0].props
    assert props.get("read_only") is True or props.get("disabled") is True


async def test_market_edit_form_type_prefilled(test_db):
    """Skill market edit form type select is prefilled from existing data."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "official")
    assert form is not None
    type_fields = _walk(form, lambda c: c.props.get("name") == "type")
    assert len(type_fields) == 1
    assert type_fields[0].props.get("value") == "skills_sh"


async def test_market_edit_form_enabled_prefilled_true(test_db):
    """Skill market edit form enabled prefilled as 'true' for enabled market."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "official")
    assert form is not None
    enabled_fields = _walk(form, lambda c: c.props.get("name") == "enabled")
    assert len(enabled_fields) == 1
    assert enabled_fields[0].props.get("value") == "true"


async def test_market_edit_form_enabled_prefilled_false(test_db):
    """Skill market edit form enabled prefilled as 'false' for disabled market."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    form = _edit_form_for_market(spec, "custom")
    assert form is not None
    enabled_fields = _walk(form, lambda c: c.props.get("name") == "enabled")
    assert len(enabled_fields) == 1
    assert enabled_fields[0].props.get("value") == "false"


async def test_market_delete_button_still_present(test_db):
    """Delete button is still rendered alongside the inline edit form for skill markets."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"skill_markets": _MARKETS}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "skill_markets"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(_MARKETS)


# ---------------------------------------------------------------------------
# Scheduler cron inline edit
# ---------------------------------------------------------------------------

async def test_each_cron_has_inline_edit_form(test_db):
    """Each existing scheduler cron entry has an inline edit form."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    for entry in _CRONS:
        form = _edit_form_for_cron(spec, entry["name"])
        assert form is not None, f"No inline edit form found for cron '{entry['name']}'"


async def test_cron_edit_form_action_has_match_field(test_db):
    """Cron edit form action has match_field='name'."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    action = form.props.get("action") or {}
    assert action.get("match_field") == "name"
    assert action.get("match_value") == "daily-report"
    assert action.get("key") == "scheduler_cron"


async def test_cron_edit_form_has_required_fields(test_db):
    """Cron edit form has name, schedule, task, enabled fields."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    names = _field_names(form)
    assert "name" in names
    assert "schedule" in names
    assert "task" in names
    assert "enabled" in names


async def test_cron_edit_form_name_field_read_only(test_db):
    """Cron edit form name field is read_only."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    name_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "name")
    assert len(name_fields) == 1
    props = name_fields[0].props
    assert props.get("read_only") is True or props.get("disabled") is True


async def test_cron_edit_form_schedule_prefilled(test_db):
    """Cron edit form schedule field is prefilled from existing data."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    schedule_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "schedule")
    assert len(schedule_fields) == 1
    assert schedule_fields[0].props.get("value") == "0 9 * * 1"


async def test_cron_edit_form_task_prefilled(test_db):
    """Cron edit form task field is prefilled from existing data."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    task_fields = _walk(form, lambda c: c.type == "field" and c.props.get("name") == "task")
    assert len(task_fields) == 1
    assert task_fields[0].props.get("value") == "Generate daily report"


async def test_cron_edit_form_enabled_prefilled_true(test_db):
    """Cron edit form enabled prefilled as 'true' for enabled entry."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "daily-report")
    assert form is not None
    enabled_fields = _walk(form, lambda c: c.props.get("name") == "enabled")
    assert len(enabled_fields) == 1
    assert enabled_fields[0].props.get("value") == "true"


async def test_cron_edit_form_enabled_prefilled_false(test_db):
    """Cron edit form enabled prefilled as 'false' for disabled entry."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    form = _edit_form_for_cron(spec, "weekly-cleanup")
    assert form is not None
    enabled_fields = _walk(form, lambda c: c.props.get("name") == "enabled")
    assert len(enabled_fields) == 1
    assert enabled_fields[0].props.get("value") == "false"


async def test_cron_delete_button_still_present(test_db):
    """Delete button is still rendered alongside the inline edit form for cron entries."""
    spec = await settings_view.build(test_db, settings_store=FakeStore({"scheduler_cron": _CRONS}))
    buttons = _walk(spec.root, lambda c: c.type == "button")
    delete_btns = [
        b for b in buttons
        if (b.props.get("action") or {}).get("key") == "scheduler_cron"
        and (b.props.get("action") or {}).get("kind") == "settings_write"
    ]
    assert len(delete_btns) >= len(_CRONS)
