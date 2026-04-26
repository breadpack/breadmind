import pytest
from uuid import UUID, uuid4
from breadmind.messenger.id_projection import (
    project_workspace_id, project_user_id, project_channel_id,
    project_file_id, parse_id, parse_user_kind, IdParseError,
)


def test_project_workspace_id_starts_with_T():
    wid = uuid4()
    s = project_workspace_id(wid)
    assert s.startswith("T")
    assert len(s) == 13  # T + 12 base32


def test_project_user_id_human():
    uid = uuid4()
    assert project_user_id(uid, kind="human").startswith("U")


def test_project_user_id_bot_or_agent():
    uid = uuid4()
    assert project_user_id(uid, kind="bot").startswith("B")
    assert project_user_id(uid, kind="agent").startswith("B")


def test_project_channel_id_by_kind():
    cid = uuid4()
    assert project_channel_id(cid, kind="public").startswith("C")
    assert project_channel_id(cid, kind="private").startswith("G")
    assert project_channel_id(cid, kind="dm").startswith("D")
    assert project_channel_id(cid, kind="mpdm").startswith("G")


def test_project_file_id():
    fid = uuid4()
    assert project_file_id(fid).startswith("F")


def test_parse_id_round_trip():
    wid = uuid4()
    s = project_workspace_id(wid)
    prefix, parsed = parse_id(s)
    assert prefix == "T"
    # parsed is lossy (60 bits only); equality with original is not guaranteed
    assert isinstance(parsed, UUID)


def test_parse_id_invalid_prefix_raises():
    with pytest.raises(IdParseError):
        parse_id("X12345ABCDE12")


def test_parse_id_invalid_length_raises():
    with pytest.raises(IdParseError):
        parse_id("Tabc")


def test_parse_user_kind_human_and_bot():
    assert parse_user_kind("U" + "A" * 12) == "human"
    assert parse_user_kind("B" + "A" * 12) == "bot"
    with pytest.raises(IdParseError):
        parse_user_kind("C" + "A" * 12)
