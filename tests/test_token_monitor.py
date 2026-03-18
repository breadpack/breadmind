"""TokenMonitor tests."""
import time
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_healthy_token():
    from breadmind.personal.oauth import OAuthCredentials
    from breadmind.personal.token_monitor import TokenMonitor

    oauth = AsyncMock()
    oauth.get_credentials = AsyncMock(
        return_value=OAuthCredentials(
            provider="google",
            access_token="tok",
            expires_at=time.time() + 7200,
        )
    )

    monitor = TokenMonitor(oauth_manager=oauth)
    statuses = await monitor.check_all()
    google = [s for s in statuses if "google" in s.service_id]
    assert len(google) == 1
    assert google[0].healthy is True


@pytest.mark.asyncio
async def test_expired_token():
    from breadmind.personal.oauth import OAuthCredentials
    from breadmind.personal.token_monitor import TokenMonitor

    oauth = AsyncMock()
    oauth.get_credentials = AsyncMock(
        return_value=OAuthCredentials(
            provider="google",
            access_token="tok",
            expires_at=time.time() - 100,
        )
    )

    monitor = TokenMonitor(oauth_manager=oauth)
    statuses = await monitor.check_all()
    google = [s for s in statuses if "google" in s.service_id]
    assert google[0].healthy is False
    assert "만료" in google[0].message


@pytest.mark.asyncio
async def test_no_credentials():
    from breadmind.personal.token_monitor import TokenMonitor

    oauth = AsyncMock()
    oauth.get_credentials = AsyncMock(return_value=None)

    monitor = TokenMonitor(oauth_manager=oauth)
    statuses = await monitor.check_all()
    google = [s for s in statuses if "google" in s.service_id]
    assert google[0].healthy is False
    assert "인증되지 않음" in google[0].message


@pytest.mark.asyncio
async def test_get_alerts_only_unhealthy():
    from breadmind.personal.oauth import OAuthCredentials
    from breadmind.personal.token_monitor import TokenMonitor

    oauth = AsyncMock()

    # Google: expired, Microsoft: healthy
    async def mock_get_creds(provider, user_id="default"):
        if provider == "google":
            return OAuthCredentials(
                provider="google",
                access_token="tok",
                expires_at=time.time() - 100,
            )
        return OAuthCredentials(
            provider="microsoft",
            access_token="tok",
            expires_at=time.time() + 90000,  # >24h so not flagged as expiring-soon
        )

    oauth.get_credentials = mock_get_creds
    monitor = TokenMonitor(oauth_manager=oauth)
    await monitor.check_all()
    alerts = await monitor.get_alerts()
    assert len(alerts) == 1
    assert "google" in alerts[0].service_id
