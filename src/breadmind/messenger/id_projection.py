"""Slack-compat ID projection.

Internal entities use UUID. Slack-compat surface uses prefix + base32(uuid)[:12].
Bidirectional + deterministic.
"""
from __future__ import annotations
import base64
from typing import Literal
from uuid import UUID

# 12 base32 chars = 60 bits. Collision risk 1/2^60 per workspace; acceptable.
_PROJECTED_LEN = 12

ChannelKind = Literal["public", "private", "dm", "mpdm"]
UserKind = Literal["human", "bot", "agent"]


class IdParseError(ValueError):
    pass


def _b32(uuid: UUID) -> str:
    raw = uuid.bytes
    encoded = base64.b32encode(raw).decode("ascii").rstrip("=")
    return encoded[:_PROJECTED_LEN].upper()


def project_workspace_id(uuid: UUID) -> str:
    return "T" + _b32(uuid)


def project_user_id(uuid: UUID, *, kind: UserKind) -> str:
    prefix = "U" if kind == "human" else "B"
    return prefix + _b32(uuid)


def project_channel_id(uuid: UUID, *, kind: ChannelKind) -> str:
    prefix = {
        "public": "C",
        "private": "G",
        "dm": "D",
        "mpdm": "G",  # Slack uses G for MPDM as well
    }[kind]
    return prefix + _b32(uuid)


def project_file_id(uuid: UUID) -> str:
    return "F" + _b32(uuid)


def parse_id(s: str) -> tuple[str, UUID]:
    """Parse a projected ID into (prefix, uuid).

    The UUID returned is reconstructed from the first 60 bits of the base32-
    encoded value with the remaining 68 bits zero-padded. It is therefore
    LOSSY — equality with the original UUID is not guaranteed. Production
    callers must resolve the projection back to a real UUID via the
    ``legacy_slack_id`` column or a projection mapping table.
    """
    if not s or len(s) < 2:
        raise IdParseError("id too short")
    prefix = s[0] if s[0] in "TUBCGDFM" else None
    if prefix is None:
        raise IdParseError(f"unknown prefix in {s!r}")
    body = s[1:]
    if len(body) != _PROJECTED_LEN:
        raise IdParseError(f"body length must be {_PROJECTED_LEN}")
    return prefix, _b32_to_uuid_lossy(body)


def _b32_to_uuid_lossy(body: str) -> UUID:
    """Reconstruct UUID from first 60 bits + zero-pad. Unique within workspace
    by collision-detection in caller; not globally unique."""
    padding = "=" * ((-len(body)) % 8)
    raw = base64.b32decode(body + padding)
    uuid_bytes = raw + bytes(16 - len(raw))
    return UUID(bytes=uuid_bytes)


def parse_user_kind(slack_id: str) -> UserKind:
    if slack_id.startswith("U"):
        return "human"
    if slack_id.startswith("B"):
        return "bot"
    raise IdParseError(f"not a user id: {slack_id}")
