"""Tests for worker deployment: token manager, install generator, routes."""
import pytest
from datetime import datetime, timezone, timedelta
from breadmind.network.token_manager import TokenManager
from breadmind.network.install_generator import generate_install_script


class TestTokenManager:
    def test_create_token(self):
        mgr = TokenManager()
        token = mgr.create_token(ttl_hours=1, max_uses=1, created_by="test")
        assert token.is_valid
        assert len(token.secret) > 20
        assert token.max_uses == 1
        assert token.uses == 0

    def test_validate_and_consume(self):
        mgr = TokenManager()
        token = mgr.create_token(max_uses=2)

        # First use
        result = mgr.validate_and_consume(token.secret)
        assert result is not None
        assert result.uses == 1

        # Second use
        result = mgr.validate_and_consume(token.secret)
        assert result is not None
        assert result.uses == 2

        # Third use — exhausted
        result = mgr.validate_and_consume(token.secret)
        assert result is None

    def test_single_use_token(self):
        mgr = TokenManager()
        token = mgr.create_token(max_uses=1)
        assert mgr.validate_and_consume(token.secret) is not None
        assert mgr.validate_and_consume(token.secret) is None

    def test_expired_token(self):
        mgr = TokenManager()
        token = mgr.create_token(ttl_hours=0.001)  # ~3.6 seconds
        # Force expiration
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert not token.is_valid
        assert mgr.validate_and_consume(token.secret) is None

    def test_revoke_token(self):
        mgr = TokenManager()
        token = mgr.create_token()
        assert mgr.revoke(token.token_id)
        assert not token.is_valid
        assert mgr.validate_and_consume(token.secret) is None

    def test_list_tokens(self):
        mgr = TokenManager()
        mgr.create_token(created_by="user1")
        mgr.create_token(created_by="user2")
        tokens = mgr.list_tokens()
        assert len(tokens) == 2

    def test_peek_does_not_consume(self):
        mgr = TokenManager()
        token = mgr.create_token(max_uses=1)
        peeked = mgr.peek(token.secret)
        assert peeked is not None
        assert peeked.uses == 0  # Not consumed
        # Still valid for actual use
        assert mgr.validate_and_consume(token.secret) is not None

    def test_cleanup_expired(self):
        mgr = TokenManager()
        t1 = mgr.create_token()
        mgr.create_token()
        t1.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        cleaned = mgr.cleanup_expired()
        assert cleaned == 1
        assert len(mgr.list_tokens()) == 1

    def test_labels(self):
        mgr = TokenManager()
        token = mgr.create_token(labels={"role": "monitor", "zone": "dmz"})
        assert token.labels["role"] == "monitor"

    @pytest.mark.asyncio
    async def test_save_load_db(self):
        """Test DB persistence round-trip."""
        class FakeDB:
            def __init__(self):
                self._store = {}
            async def set_setting(self, key, value):
                self._store[key] = value
            async def get_setting(self, key):
                return self._store.get(key)

        db = FakeDB()
        mgr1 = TokenManager(db=db)
        mgr1.create_token(created_by="persist-test")
        await mgr1.save_to_db()

        mgr2 = TokenManager(db=db)
        await mgr2.load_from_db()
        loaded = mgr2.list_tokens()
        assert len(loaded) == 1
        assert loaded[0]["created_by"] == "persist-test"


class TestInstallGenerator:
    def test_linux_script_contains_token(self):
        script = generate_install_script(
            commander_url="ws://10.0.0.1:8081/ws/agent",
            token_secret="test-token-abc",
            os_type="linux",
        )
        assert "test-token-abc" in script
        assert "ws://10.0.0.1:8081/ws/agent" in script
        assert "#!/bin/bash" in script
        assert "pip install" in script
        assert "breadmind" in script

    def test_windows_script_contains_token(self):
        script = generate_install_script(
            commander_url="ws://10.0.0.1:8081/ws/agent",
            token_secret="test-token-abc",
            os_type="windows",
        )
        assert "test-token-abc" in script
        assert "ws://10.0.0.1:8081/ws/agent" in script
        assert "$ErrorActionPreference" in script
        assert "pip install" in script

    def test_custom_agent_id(self):
        script = generate_install_script(
            commander_url="ws://host/ws",
            token_secret="tok",
            agent_id="my-worker-01",
            os_type="linux",
        )
        assert 'AGENT_ID="my-worker-01"' in script

    def test_auto_agent_id(self):
        script = generate_install_script(
            commander_url="ws://host/ws",
            token_secret="tok",
            os_type="linux",
        )
        assert "worker-$(hostname)" in script
