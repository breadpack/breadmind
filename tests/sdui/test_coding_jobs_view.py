from breadmind.sdui.views import coding_jobs_view


def _all_types(c):
    out = {c.type}
    for ch in c.children:
        out |= _all_types(ch)
    return out


def _find_text_with(c, needle):
    if c.type in ("text", "heading") and needle in str(c.props.get("value", "")):
        return True
    return any(_find_text_with(ch, needle) for ch in c.children)


async def test_coding_jobs_view_empty(test_db):
    spec = await coding_jobs_view.build(test_db)
    assert spec.root.type == "page"
    assert _find_text_with(spec.root, "활성") or _find_text_with(spec.root, "0개")


async def test_coding_jobs_view_with_jobs(test_db):
    class FakeTracker:
        def list_jobs(self):
            return [
                {
                    "id": "job-1",
                    "status": "running",
                    "project": "myapp",
                    "job_type": "refactor",
                    "platform": "github",
                    "phases": ["analysis", "coding"],
                    "progress": {"percentage": 45, "message": "Working on phase 2"},
                    "description": "Refactor auth module",
                },
                {
                    "id": "job-2",
                    "status": "completed",
                    "project": "site",
                    "job_type": "feature",
                    "platform": "gitlab",
                    "phases": ["plan", "code", "test"],
                    "progress": {"percentage": 100, "message": "done"},
                },
            ]

    spec = await coding_jobs_view.build(test_db, job_tracker=FakeTracker())
    assert _find_text_with(spec.root, "myapp")
    assert _find_text_with(spec.root, "site")
    types = _all_types(spec.root)
    assert "progress" in types
    assert "badge" in types

    cancel_buttons = []

    def collect(c):
        if c.type == "button" and "취소" in str(c.props.get("label", "")):
            cancel_buttons.append(c)
        for ch in c.children:
            collect(ch)

    collect(spec.root)
    assert len(cancel_buttons) == 1  # only the running job


async def test_coding_jobs_view_with_broken_tracker(test_db):
    class Broken:
        def list_jobs(self):
            raise RuntimeError("nope")

    spec = await coding_jobs_view.build(test_db, job_tracker=Broken())
    assert spec.root.type == "page"


def test_list_view_schema_renders_sections():
    """Task 16: ``build_list_screen`` returns a dict schema with Active/Recent sections."""
    from breadmind.sdui.views.coding_jobs_view import build_list_screen

    schema = build_list_screen(
        active_jobs=[
            {
                "job_id": "a",
                "status": "running",
                "progress_pct": 50,
                "project": "p",
                "prompt": "x",
                "user": "alice",
                "started_at": 1,
                "total_phases": 2,
                "completed_phases": 1,
            }
        ],
        recent_jobs=[
            {
                "job_id": "b",
                "status": "completed",
                "progress_pct": 100,
                "project": "q",
                "prompt": "y",
                "user": "bob",
                "started_at": 0,
                "total_phases": 1,
                "completed_phases": 1,
            }
        ],
        current_username="alice",
        is_admin=False,
        mine=True,
    )
    titles = [s.get("title") for s in schema.get("sections", [])]
    assert "Active" in titles
    assert "Recent" in titles
    # The rows should carry the job_id and a detail link.
    active = next(s for s in schema["sections"] if s["title"] == "Active")
    assert active["items"][0]["id"] == "a"
    assert active["items"][0]["link"] == "/coding-jobs/a"
    # Header must expose filters + current-user context.
    header = schema["header"]
    assert header["current_user"] == "alice"
    assert header["is_admin"] is False
    filter_keys = {f["key"] for f in header["filters"]}
    assert {"mine", "status"} <= filter_keys
    # WS subscription wiring so the UI can live-refresh on job events.
    assert "coding_job_running" in schema["ws_subscribe"]


def test_detail_view_schema():
    """Task 17: ``build_detail_screen`` returns a dict schema with header,
    phases, log_panel, and a conditional cancel_button."""
    from breadmind.sdui.views.coding_jobs_view import build_detail_screen

    job = {
        "job_id": "j1",
        "status": "running",
        "user": "alice",
        "project": "p",
        "agent": "claude",
        "prompt": "do x",
        "total_phases": 2,
        "completed_phases": 1,
        "progress_pct": 50,
        "duration_seconds": 30.5,
        "phases": [
            {
                "step": 1,
                "title": "a",
                "status": "completed",
                "duration_seconds": 10.0,
                "files_changed": ["a.py"],
            },
            {
                "step": 2,
                "title": "b",
                "status": "running",
                "duration_seconds": 0,
                "files_changed": [],
            },
        ],
    }
    schema = build_detail_screen(job=job, can_cancel=True, selected_step=2)
    assert schema["header"]["progress_pct"] == 50
    assert len(schema["phases"]) == 2
    assert schema["log_panel"]["selected_step"] == 2
    assert schema["cancel_button"]["visible"] is True


def test_detail_view_auto_selects_running_step():
    """When ``selected_step`` is None, default to the running phase."""
    from breadmind.sdui.views.coding_jobs_view import build_detail_screen

    job = {
        "job_id": "j2",
        "status": "running",
        "project": "p",
        "agent": "claude",
        "prompt": "x",
        "total_phases": 3,
        "completed_phases": 1,
        "progress_pct": 33,
        "phases": [
            {"step": 1, "title": "a", "status": "completed",
             "duration_seconds": 5, "files_changed": []},
            {"step": 2, "title": "b", "status": "running",
             "duration_seconds": 0, "files_changed": []},
            {"step": 3, "title": "c", "status": "pending",
             "duration_seconds": 0, "files_changed": []},
        ],
    }
    schema = build_detail_screen(job=job, can_cancel=True)
    assert schema["log_panel"]["selected_step"] == 2
    # Fetch URL is keyed off the selected step.
    assert schema["log_panel"]["fetch_url"].endswith("/phases/2/logs")


def test_detail_view_cancel_hidden_when_terminal():
    """Terminal-status jobs (completed/failed/cancelled) hide the cancel button
    even if the caller has permission."""
    from breadmind.sdui.views.coding_jobs_view import build_detail_screen

    job = {
        "job_id": "j3",
        "status": "completed",
        "project": "p",
        "agent": "claude",
        "prompt": "x",
        "total_phases": 1,
        "completed_phases": 1,
        "progress_pct": 100,
        "phases": [
            {"step": 1, "title": "a", "status": "completed",
             "duration_seconds": 1, "files_changed": []},
        ],
    }
    schema = build_detail_screen(job=job, can_cancel=True)
    assert schema["cancel_button"]["visible"] is False


def test_detail_view_files_changed_projection():
    """Phase rows expose both the list and count of files_changed for
    layout flexibility on the client."""
    from breadmind.sdui.views.coding_jobs_view import build_detail_screen

    job = {
        "job_id": "j4",
        "status": "running",
        "project": "p",
        "agent": "claude",
        "prompt": "x",
        "total_phases": 1,
        "completed_phases": 0,
        "progress_pct": 0,
        "phases": [
            {"step": 1, "title": "a", "status": "running",
             "duration_seconds": 2, "files_changed": ["a.py", "b.py", "c.py"]},
        ],
    }
    schema = build_detail_screen(job=job, can_cancel=False)
    assert schema["phases"][0]["files_changed_count"] == 3
    assert schema["phases"][0]["files_changed"] == ["a.py", "b.py", "c.py"]
    # can_cancel=False always hides, regardless of status.
    assert schema["cancel_button"]["visible"] is False
