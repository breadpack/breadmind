"""Pairing flow: connect to Commander with a join token, receive certs."""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote, urlencode

from breadmind.companion.config import CompanionConfig, save_config, _default_config_dir

logger = logging.getLogger(__name__)


async def pair(commander_url: str, token: str) -> CompanionConfig:
    """Execute the pairing handshake with a Commander.

    1. Connect to Commander's pairing endpoint via HTTP
    2. Submit the join token
    3. Receive session key and (optionally) certificate
    4. Save config locally

    Returns the resulting CompanionConfig.
    """
    import aiohttp

    # Derive HTTP URL from WS URL
    http_url = commander_url.replace("ws://", "http://").replace("wss://", "https://")
    # Strip any path like /ws/agent and use the pairing endpoint
    base_url = http_url.split("/ws/")[0] if "/ws/" in http_url else http_url
    pair_endpoint = f"{base_url}/api/companions/pair"

    logger.info("Pairing with Commander at %s", pair_endpoint)

    async with aiohttp.ClientSession() as session:
        async with session.post(pair_endpoint, json={"token": token}) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Pairing failed (HTTP {resp.status}): {body}")
            data = await resp.json()

    config = CompanionConfig(
        commander_url=commander_url,
        session_key=data.get("session_key", ""),
    )

    # Store certificate if provided
    cert_data = data.get("cert")
    key_data = data.get("key")
    if cert_data and key_data:
        config_dir = _default_config_dir()
        certs_dir = config_dir / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)

        cert_path = certs_dir / "cert.pem"
        key_path = certs_dir / "key.pem"
        cert_path.write_text(cert_data, encoding="utf-8")
        key_path.write_text(key_data, encoding="utf-8")

        config.cert_path = str(cert_path)
        config.key_path = str(key_path)

    save_config(config)
    logger.info("Pairing complete. Agent ID: %s", config.agent_id)
    return config


def generate_pairing_url(commander_url: str, token: str) -> str:
    """Create a companion:// deep-link URL for one-click pairing."""
    params = urlencode({"token": token, "url": commander_url})
    return f"breadmind-companion://pair?{params}"
