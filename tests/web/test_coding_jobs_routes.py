"""Tests for /api/coding-jobs filters and existence-hiding (Task 13).

Shared fixtures ``web_app_client`` and ``seeded_jobs`` live in
``tests/web/conftest.py``.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _login(client: TestClient, username: str, password: str = "p") -> None:
    r = client.post(
        "/api/auth/login",
        json={"password": password, "username": username},
    )
    assert r.status_code == 200


def test_list_mine_filter(web_app_client: TestClient, seeded_jobs):
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs?mine=1")
    assert r.status_code == 200
    data = r.json()
    assert data, "expected at least one job for alice"
    assert all(j["user"] == "alice" for j in data)


def test_list_admin_sees_all(
    web_app_client: TestClient, seeded_jobs, monkeypatch
):
    monkeypatch.setenv("BREADMIND_ADMIN_USERS", "alice")
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs?mine=0")
    assert r.status_code == 200
    data = r.json()
    users = {j["user"] for j in data}
    assert users >= {"alice", "bob"}


def test_list_non_admin_all_view_forbidden(
    web_app_client: TestClient, seeded_jobs
):
    """Non-admin users asking for the all-jobs view get 403."""
    _login(web_app_client, "carol")
    r = web_app_client.get("/api/coding-jobs?mine=0")
    assert r.status_code == 403


def test_detail_hides_from_non_owner(web_app_client: TestClient, seeded_jobs):
    """Non-owner, non-admin gets 404 for someone else's job (existence hiding)."""
    _login(web_app_client, "carol")
    r = web_app_client.get("/api/coding-jobs/bob-job-1")
    assert r.status_code == 404


def test_detail_owner_can_read_own_job(
    web_app_client: TestClient, seeded_jobs
):
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs/alice-job-1")
    assert r.status_code == 200
    assert r.json()["user"] == "alice"


def test_detail_admin_can_read_any_job(
    web_app_client: TestClient, seeded_jobs, monkeypatch
):
    monkeypatch.setenv("BREADMIND_ADMIN_USERS", "alice")
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs/bob-job-1")
    assert r.status_code == 200
    assert r.json()["user"] == "bob"


def test_active_filters_to_current_user_for_non_admin(
    web_app_client: TestClient, seeded_jobs
):
    """``/api/coding-jobs/active`` must only return jobs owned by the caller
    when the caller is not an admin."""
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs/active")
    assert r.status_code == 200
    data = r.json()
    assert all(j["user"] == "alice" for j in data)


def test_list_default_mine_for_non_admin(
    web_app_client: TestClient, seeded_jobs
):
    """When ``mine`` is unspecified, a non-admin should only see their own."""
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs")
    assert r.status_code == 200
    data = r.json()
    assert all(j["user"] == "alice" for j in data)


def test_cancel_403_non_owner(web_app_client: TestClient, seeded_jobs):
    """Task 15: non-owner non-admin gets 403 (not 404) on cancel.

    Cancel is a mutation, so existence-hiding is relaxed — the caller is
    authenticated and deserves to know their request was rejected for
    authz reasons, not silently shadowed as a 404.
    """
    _login(web_app_client, "carol")
    r = web_app_client.post("/api/coding-jobs/bob-job-1/cancel")
    assert r.status_code == 403


def test_cancel_200_owner(web_app_client: TestClient, seeded_jobs):
    """Owner can cancel their own job and gets a well-formed ack."""
    _login(web_app_client, "alice")
    r = web_app_client.post("/api/coding-jobs/alice-job-1/cancel")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_cancel_200_admin(
    web_app_client: TestClient, seeded_jobs, monkeypatch
):
    """An admin (via BREADMIND_ADMIN_USERS) can cancel any user's job."""
    monkeypatch.setenv("BREADMIND_ADMIN_USERS", "super")
    _login(web_app_client, "super")
    r = web_app_client.post("/api/coding-jobs/alice-job-1/cancel")
    assert r.status_code == 200


def test_logs_pagination(web_app_client: TestClient, seeded_jobs_with_logs):
    """Cursor-paginated phase logs echo the last line_no so the client can
    keep paging forward without duplicates."""
    _login(web_app_client, "alice")
    r = web_app_client.get("/api/coding-jobs/alice-job-1/phases/1/logs?limit=5")
    assert r.status_code == 200
    page1 = r.json()
    assert len(page1["items"]) == 5
    assert page1["next_after_line_no"] == page1["items"][-1]["line_no"]
    r2 = web_app_client.get(
        f"/api/coding-jobs/alice-job-1/phases/1/logs"
        f"?after_line_no={page1['next_after_line_no']}&limit=5"
    )
    page2 = r2.json()
    assert [i["line_no"] for i in page2["items"]] == [6, 7, 8, 9, 10]
