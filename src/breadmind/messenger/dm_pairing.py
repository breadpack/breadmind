"""DM pairing security for messenger platforms."""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class DMPolicy(str, Enum):
    PAIRING = "pairing"      # Unknown senders get pairing code
    ALLOWLIST = "allowlist"   # Only pre-approved users
    OPEN = "open"             # Anyone can DM
    DISABLED = "disabled"     # DMs ignored


@dataclass
class PairingCode:
    code: str
    channel: str
    sender_id: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0  # set in __post_init__

    def __post_init__(self):
        if not self.expires_at:
            self.expires_at = self.created_at + 3600  # 1 hour

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


class DMPairingManager:
    """Manages DM access control with pairing codes."""

    def __init__(self, policy: DMPolicy = DMPolicy.PAIRING,
                 data_dir: str | None = None,
                 max_pending_per_channel: int = 3) -> None:
        self._policy = policy
        self._data_dir = data_dir or os.path.join(Path.home().as_posix(), ".breadmind", "pairing")
        self._max_pending = max_pending_per_channel
        self._allowlist: dict[str, set[str]] = {}  # channel -> set of user_ids
        self._pending: dict[str, list[PairingCode]] = {}  # channel -> codes
        os.makedirs(self._data_dir, exist_ok=True)
        self._load_state()

    def check_access(self, channel: str, sender_id: str) -> tuple[bool, str]:
        """Check if sender has DM access. Returns (allowed, reason)."""
        if self._policy == DMPolicy.DISABLED:
            return False, "DMs are disabled"
        if self._policy == DMPolicy.OPEN:
            return True, "open policy"
        if sender_id in self._allowlist.get(channel, set()):
            return True, "allowlisted"
        if self._policy == DMPolicy.ALLOWLIST:
            return False, "not on allowlist"
        # PAIRING mode: generate code
        return False, "pairing_required"

    def generate_code(self, channel: str, sender_id: str) -> str | None:
        """Generate a pairing code for a sender."""
        pending = self._pending.get(channel, [])
        pending = [p for p in pending if not p.expired]  # clean expired
        self._pending[channel] = pending

        if len(pending) >= self._max_pending:
            return None  # too many pending

        code = secrets.token_hex(4).upper()  # 8-char hex code
        pc = PairingCode(code=code, channel=channel, sender_id=sender_id)
        self._pending.setdefault(channel, []).append(pc)
        self._save_state()
        return code

    def approve(self, channel: str, code: str) -> bool:
        """Approve a pairing code, adding sender to allowlist."""
        pending = self._pending.get(channel, [])
        for pc in pending:
            if pc.code == code and not pc.expired:
                self._allowlist.setdefault(channel, set()).add(pc.sender_id)
                pending.remove(pc)
                self._save_state()
                return True
        return False

    def add_to_allowlist(self, channel: str, sender_id: str) -> None:
        self._allowlist.setdefault(channel, set()).add(sender_id)
        self._save_state()

    def remove_from_allowlist(self, channel: str, sender_id: str) -> bool:
        allowed = self._allowlist.get(channel, set())
        if sender_id in allowed:
            allowed.remove(sender_id)
            self._save_state()
            return True
        return False

    def get_pending(self, channel: str) -> list[PairingCode]:
        return [p for p in self._pending.get(channel, []) if not p.expired]

    def _save_state(self) -> None:
        state = {
            "allowlist": {ch: list(ids) for ch, ids in self._allowlist.items()},
            "pending": {
                ch: [{"code": p.code, "sender": p.sender_id, "expires": p.expires_at}
                     for p in codes if not p.expired]
                for ch, codes in self._pending.items()
            },
        }
        path = os.path.join(self._data_dir, "dm_state.json")
        with open(path, 'w') as f:
            json.dump(state, f)

    def _load_state(self) -> None:
        path = os.path.join(self._data_dir, "dm_state.json")
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                state = json.load(f)
            self._allowlist = {ch: set(ids) for ch, ids in state.get("allowlist", {}).items()}
            for ch, codes in state.get("pending", {}).items():
                self._pending[ch] = [
                    PairingCode(code=c["code"], channel=ch, sender_id=c["sender"],
                                expires_at=c.get("expires", 0))
                    for c in codes
                ]
        except (json.JSONDecodeError, KeyError):
            pass
