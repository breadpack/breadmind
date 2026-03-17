"""Tests for Teams, LINE, Matrix auto-connectors."""
import pytest


@pytest.mark.asyncio
async def test_teams_setup_steps():
    from breadmind.messenger.auto_connect.teams import TeamsAutoConnector
    connector = TeamsAutoConnector()
    steps = await connector.get_setup_steps()
    assert len(steps) == 3
    assert steps[0].action_type == "user_action"
    assert steps[1].action_type == "user_input"
    assert any(f.name == "app_id" for f in steps[1].input_fields)


@pytest.mark.asyncio
async def test_teams_validate_empty_creds():
    from breadmind.messenger.auto_connect.teams import TeamsAutoConnector
    connector = TeamsAutoConnector()
    result = await connector.validate_credentials({})
    assert result.valid is False


@pytest.mark.asyncio
async def test_line_setup_steps():
    from breadmind.messenger.auto_connect.line import LINEAutoConnector
    connector = LINEAutoConnector()
    steps = await connector.get_setup_steps()
    assert len(steps) == 3
    assert any(f.name == "channel_token" for f in steps[1].input_fields)


@pytest.mark.asyncio
async def test_line_validate_empty_creds():
    from breadmind.messenger.auto_connect.line import LINEAutoConnector
    connector = LINEAutoConnector()
    result = await connector.validate_credentials({})
    assert result.valid is False


@pytest.mark.asyncio
async def test_matrix_setup_steps():
    from breadmind.messenger.auto_connect.matrix import MatrixAutoConnector
    connector = MatrixAutoConnector()
    steps = await connector.get_setup_steps()
    assert len(steps) == 3
    assert any(f.name == "homeserver" for f in steps[1].input_fields)
    assert any(f.name == "access_token" for f in steps[1].input_fields)


@pytest.mark.asyncio
async def test_matrix_validate_empty_creds():
    from breadmind.messenger.auto_connect.matrix import MatrixAutoConnector
    connector = MatrixAutoConnector()
    result = await connector.validate_credentials({})
    assert result.valid is False
