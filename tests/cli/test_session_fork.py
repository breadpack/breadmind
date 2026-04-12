"""SessionForker unit tests."""
from __future__ import annotations

import pytest

from breadmind.cli.session_fork import SessionForker


@pytest.fixture
def forker(tmp_path):
    return SessionForker(storage_dir=tmp_path)


SAMPLE_MESSAGES = [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "hi"},
    {"role": "user", "content": "do something"},
    {"role": "assistant", "content": "done"},
]


class TestFork:
    def test_fork_creates_branch(self, forker: SessionForker):
        branch = forker.fork("parent-1", SAMPLE_MESSAGES, label="test-fork")
        assert branch.parent_id == "parent-1"
        assert branch.branch_point == len(SAMPLE_MESSAGES)
        assert branch.label == "test-fork"
        assert len(branch.session_id) == 12

    def test_fork_at_specific_point(self, forker: SessionForker):
        branch = forker.fork("parent-1", SAMPLE_MESSAGES, branch_at=2)
        assert branch.branch_point == 2

    def test_fork_clamps_branch_at(self, forker: SessionForker):
        branch = forker.fork("p", SAMPLE_MESSAGES, branch_at=100)
        assert branch.branch_point == len(SAMPLE_MESSAGES)
        branch_neg = forker.fork("p", SAMPLE_MESSAGES, branch_at=-5)
        assert branch_neg.branch_point == 0

    def test_fork_generates_unique_ids(self, forker: SessionForker):
        b1 = forker.fork("p", SAMPLE_MESSAGES)
        b2 = forker.fork("p", SAMPLE_MESSAGES)
        assert b1.session_id != b2.session_id


class TestGetBranch:
    def test_get_existing(self, forker: SessionForker):
        branch = forker.fork("p", SAMPLE_MESSAGES)
        result = forker.get_branch(branch.session_id)
        assert result is not None
        assert result.session_id == branch.session_id

    def test_get_nonexistent_returns_none(self, forker: SessionForker):
        assert forker.get_branch("nonexistent") is None


class TestGetBranchTree:
    def test_tree_includes_children_and_grandchildren(self, forker: SessionForker):
        b1 = forker.fork("root", SAMPLE_MESSAGES, label="child-1")
        b2 = forker.fork("root", SAMPLE_MESSAGES, label="child-2")
        b3 = forker.fork(b1.session_id, SAMPLE_MESSAGES, label="grandchild")

        tree = forker.get_branch_tree("root")
        ids = {b.session_id for b in tree}
        assert b1.session_id in ids
        assert b2.session_id in ids
        assert b3.session_id in ids

    def test_tree_empty_for_leaf(self, forker: SessionForker):
        branch = forker.fork("root", SAMPLE_MESSAGES)
        assert forker.get_branch_tree(branch.session_id) == []


class TestGetMessagesAtBranch:
    def test_returns_messages_up_to_branch_point(self, forker: SessionForker):
        branch = forker.fork("p", SAMPLE_MESSAGES, branch_at=2)
        msgs = forker.get_messages_at_branch(branch, SAMPLE_MESSAGES)
        assert len(msgs) == 2
        assert msgs[-1]["content"] == "hi"

    def test_full_branch_returns_all(self, forker: SessionForker):
        branch = forker.fork("p", SAMPLE_MESSAGES)
        msgs = forker.get_messages_at_branch(branch, SAMPLE_MESSAGES)
        assert len(msgs) == len(SAMPLE_MESSAGES)


class TestListBranches:
    def test_list_sorted_newest_first(self, forker: SessionForker):
        forker.fork("p", SAMPLE_MESSAGES, label="first")
        forker.fork("p", SAMPLE_MESSAGES, label="second")
        branches = forker.list_branches()
        assert len(branches) == 2
        assert branches[0].label == "second"


class TestPersistence:
    def test_branches_survive_reload(self, tmp_path):
        f1 = SessionForker(storage_dir=tmp_path)
        branch = f1.fork("parent", SAMPLE_MESSAGES, label="persist-test")

        f2 = SessionForker(storage_dir=tmp_path)
        result = f2.get_branch(branch.session_id)
        assert result is not None
        assert result.label == "persist-test"
        assert result.parent_id == "parent"

    def test_corrupt_file_handled_gracefully(self, tmp_path):
        (tmp_path / "branches.json").write_text("{bad", encoding="utf-8")
        f = SessionForker(storage_dir=tmp_path)
        assert f.list_branches() == []
