"""Tests for DM pairing security."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from breadmind.messenger.dm_pairing import DMPairingManager, DMPolicy, PairingCode


def test_open_policy_allows_all(tmp_path):
    """OPEN policy should allow any sender."""
    mgr = DMPairingManager(policy=DMPolicy.OPEN, data_dir=str(tmp_path))
    allowed, reason = mgr.check_access("slack", "user123")
    assert allowed is True
    assert reason == "open policy"


def test_disabled_policy_denies_all(tmp_path):
    """DISABLED policy should deny all DMs."""
    mgr = DMPairingManager(policy=DMPolicy.DISABLED, data_dir=str(tmp_path))
    allowed, reason = mgr.check_access("slack", "user123")
    assert allowed is False
    assert "disabled" in reason


def test_pairing_generates_code(tmp_path):
    """PAIRING policy should generate a code for unknown senders."""
    mgr = DMPairingManager(policy=DMPolicy.PAIRING, data_dir=str(tmp_path))

    allowed, reason = mgr.check_access("slack", "user1")
    assert allowed is False
    assert reason == "pairing_required"

    code = mgr.generate_code("slack", "user1")
    assert code is not None
    assert len(code) == 8  # 4 bytes hex = 8 chars


def test_approve_code_adds_to_allowlist(tmp_path):
    """Approving a code should add the sender to the allowlist."""
    mgr = DMPairingManager(policy=DMPolicy.PAIRING, data_dir=str(tmp_path))

    code = mgr.generate_code("slack", "user1")
    assert code is not None

    result = mgr.approve("slack", code)
    assert result is True

    allowed, reason = mgr.check_access("slack", "user1")
    assert allowed is True
    assert reason == "allowlisted"


def test_expired_code_rejected(tmp_path):
    """Expired pairing codes should be rejected."""
    mgr = DMPairingManager(policy=DMPolicy.PAIRING, data_dir=str(tmp_path))

    code = mgr.generate_code("slack", "user1")
    assert code is not None

    # Expire the code by manipulating its expires_at
    for pc in mgr._pending.get("slack", []):
        pc.expires_at = time.time() - 1

    result = mgr.approve("slack", code)
    assert result is False


def test_max_pending_limit(tmp_path):
    """Should not exceed max pending codes per channel."""
    mgr = DMPairingManager(
        policy=DMPolicy.PAIRING,
        data_dir=str(tmp_path),
        max_pending_per_channel=2,
    )

    code1 = mgr.generate_code("slack", "user1")
    code2 = mgr.generate_code("slack", "user2")
    code3 = mgr.generate_code("slack", "user3")

    assert code1 is not None
    assert code2 is not None
    assert code3 is None  # should be rejected


def test_allowlist_add_remove(tmp_path):
    """add_to_allowlist / remove_from_allowlist should work correctly."""
    mgr = DMPairingManager(policy=DMPolicy.ALLOWLIST, data_dir=str(tmp_path))

    # Initially not allowed
    allowed, _ = mgr.check_access("discord", "user1")
    assert allowed is False

    # Add to allowlist
    mgr.add_to_allowlist("discord", "user1")
    allowed, _ = mgr.check_access("discord", "user1")
    assert allowed is True

    # Remove
    removed = mgr.remove_from_allowlist("discord", "user1")
    assert removed is True
    allowed, _ = mgr.check_access("discord", "user1")
    assert allowed is False

    # Remove non-existent
    removed = mgr.remove_from_allowlist("discord", "user1")
    assert removed is False


def test_state_persistence(tmp_path):
    """State should persist across manager instances."""
    mgr1 = DMPairingManager(policy=DMPolicy.PAIRING, data_dir=str(tmp_path))
    mgr1.add_to_allowlist("slack", "user1")
    code = mgr1.generate_code("slack", "user2")

    # Create new manager with same data dir
    mgr2 = DMPairingManager(policy=DMPolicy.PAIRING, data_dir=str(tmp_path))
    allowed, _ = mgr2.check_access("slack", "user1")
    assert allowed is True

    # Pending code should also persist
    pending = mgr2.get_pending("slack")
    assert len(pending) >= 1
    assert any(p.code == code for p in pending)
