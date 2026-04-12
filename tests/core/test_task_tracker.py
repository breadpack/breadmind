"""Tests for in-session task tracker."""
import json
import os
import pytest
from breadmind.core.task_tracker import TaskTracker, TaskStatus


@pytest.fixture
def tracker():
    return TaskTracker()


def test_create_task(tracker):
    task = tracker.create("Build feature", description="Implement X")
    assert task.title == "Build feature"
    assert task.description == "Implement X"
    assert task.status == TaskStatus.PENDING
    assert task.id.startswith("task_")
    assert tracker.get(task.id) is task


def test_update_task_status(tracker):
    task = tracker.create("Task A")
    updated = tracker.update(task.id, status=TaskStatus.IN_PROGRESS)
    assert updated is not None
    assert updated.status == TaskStatus.IN_PROGRESS

    updated = tracker.update(task.id, status=TaskStatus.COMPLETED)
    assert updated.status == TaskStatus.COMPLETED


def test_list_tasks_filter_by_status(tracker):
    t1 = tracker.create("Task 1")
    t2 = tracker.create("Task 2")
    tracker.update(t1.id, status=TaskStatus.COMPLETED)

    pending = tracker.list_tasks(status=TaskStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].id == t2.id

    completed = tracker.list_tasks(status=TaskStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0].id == t1.id


def test_dependency_tracking(tracker):
    t1 = tracker.create("Parent task")
    t2 = tracker.create("Child task", blocked_by=[t1.id])
    # Reverse dependency updated
    assert t2.id in t1.blocks
    assert t1.id in t2.blocked_by


def test_get_ready_tasks(tracker):
    t1 = tracker.create("Setup")
    t2 = tracker.create("Build", blocked_by=[t1.id])
    t3 = tracker.create("Independent")

    ready = tracker.get_ready_tasks()
    ready_ids = [t.id for t in ready]
    assert t1.id in ready_ids
    assert t3.id in ready_ids
    assert t2.id not in ready_ids  # blocked by t1

    # Complete t1 -> t2 should become ready
    tracker.update(t1.id, status=TaskStatus.COMPLETED)
    ready = tracker.get_ready_tasks()
    ready_ids = [t.id for t in ready]
    assert t2.id in ready_ids


def test_delete_cleans_references(tracker):
    t1 = tracker.create("Parent")
    t2 = tracker.create("Child", blocked_by=[t1.id])
    assert t2.id in t1.blocks

    tracker.delete(t1.id)
    assert tracker.get(t1.id) is None
    assert t1.id not in t2.blocked_by


def test_file_persistence(tmp_path):
    persist_dir = str(tmp_path / "tasks")
    tracker = TaskTracker(persist_dir=persist_dir)
    t1 = tracker.create("Persisted task", description="Should survive reload")
    tracker.update(t1.id, status=TaskStatus.IN_PROGRESS)

    # Verify file exists
    assert os.path.exists(os.path.join(persist_dir, "tasks.json"))

    # Load from file in new tracker
    tracker2 = TaskTracker(persist_dir=persist_dir)
    loaded = tracker2.get(t1.id)
    assert loaded is not None
    assert loaded.title == "Persisted task"
    assert loaded.status == TaskStatus.IN_PROGRESS


def test_load_from_file(tmp_path):
    persist_dir = str(tmp_path / "tasks")
    os.makedirs(persist_dir)
    data = {
        "task_abc12345": {
            "title": "Preloaded",
            "description": "From file",
            "status": "completed",
            "owner": "agent_1",
            "blocks": [],
            "blocked_by": [],
            "metadata": {"key": "value"},
            "created_at": 1000.0,
            "updated_at": 2000.0,
        }
    }
    with open(os.path.join(persist_dir, "tasks.json"), "w") as f:
        json.dump(data, f)

    tracker = TaskTracker(persist_dir=persist_dir)
    task = tracker.get("task_abc12345")
    assert task is not None
    assert task.title == "Preloaded"
    assert task.status == TaskStatus.COMPLETED
    assert task.owner == "agent_1"
    assert task.metadata == {"key": "value"}
