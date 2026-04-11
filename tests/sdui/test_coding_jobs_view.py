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
