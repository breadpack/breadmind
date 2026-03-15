# tests/test_sync.py
import pytest
from breadmind.network.sync import SyncManager

@pytest.fixture
def sync_mgr():
    return SyncManager()

def test_accept_first_wins_new_task(sync_mgr):
    result = {"task_id": "t1", "status": "success", "output": "ok"}
    accepted = sync_mgr.reconcile("idem-1", result)
    assert accepted is True

def test_accept_first_wins_duplicate(sync_mgr):
    r1 = {"task_id": "t1", "status": "success", "output": "ok"}
    r2 = {"task_id": "t1-dup", "status": "success", "output": "also ok"}
    sync_mgr.reconcile("idem-1", r1)
    accepted = sync_mgr.reconcile("idem-1", r2)
    assert accepted is False  # Already have a success

def test_reconcile_allows_success_over_pending(sync_mgr):
    r1 = {"task_id": "t1", "status": "pending", "output": ""}
    sync_mgr.reconcile("idem-1", r1)
    r2 = {"task_id": "t1", "status": "success", "output": "done"}
    accepted = sync_mgr.reconcile("idem-1", r2)
    assert accepted is True

def test_bulk_reconcile(sync_mgr):
    results = [
        {"idempotency_key": "k1", "task_id": "t1", "status": "success", "output": "a"},
        {"idempotency_key": "k2", "task_id": "t2", "status": "success", "output": "b"},
        {"idempotency_key": "k1", "task_id": "t1-dup", "status": "success", "output": "c"},
    ]
    accepted, rejected = sync_mgr.bulk_reconcile(results)
    assert accepted == 2
    assert rejected == 1
