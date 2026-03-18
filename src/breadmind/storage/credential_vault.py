"""Centralized credential vault with Fernet encryption.

All sensitive credentials (SSH passwords, messenger tokens, OAuth tokens)
are stored encrypted in the database. Consumers receive only reference IDs
(``credential_ref:xxx``) to pass through chat/LLM context — never plaintext.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that indicate sensitive values in text
_SENSITIVE_PATTERNS = re.compile(
    r"(?i)"
    r"(?:password|passwd|pwd)\s*[:=]\s*\S+"
    r"|(?:token|secret|api[_-]?key)\s*[:=]\s*\S+"
    r"|(?:Bearer|Basic)\s+[A-Za-z0-9\-._~+/]+=*"
    r"|xox[bpsar]-[A-Za-z0-9\-]+"           # Slack tokens
    r"|ghp_[A-Za-z0-9]{36}"                  # GitHub PAT
    r"|sk-[A-Za-z0-9]{20,}"                  # OpenAI keys
    r"|AIza[A-Za-z0-9\-_]{35}"               # Google API keys
    r"|AKIA[0-9A-Z]{16}"                     # AWS access keys
    r"|-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"  # Private keys
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"     # JWT tokens
    r"|(?:mysql|postgres|mongodb)://\S+"      # Connection strings
)

_CREDENTIAL_REF_RE = re.compile(r"credential_ref:[\w:.@\-]+")


class CredentialVault:
    """Encrypted credential storage backed by the database settings table.

    Credentials are stored under ``vault:{credential_id}`` keys with the
    value Fernet-encrypted.  The vault never exposes plaintext through its
    public API except via an explicit ``retrieve()`` call.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    # ── Store / Retrieve / Delete ─────────────────────────────────────

    async def store(
        self,
        credential_id: str,
        value: str,
        metadata: dict | None = None,
    ) -> str:
        """Encrypt *value* and persist it.  Returns the credential_id."""
        from breadmind.config_env import encrypt_value

        encrypted = encrypt_value(value)
        record: dict[str, Any] = {
            "encrypted": encrypted,
            "stored_at": time.time(),
        }
        if metadata:
            record["metadata"] = metadata

        await self._db.set_setting(f"vault:{credential_id}", record)
        logger.info("Credential stored: %s", credential_id)
        return credential_id

    async def retrieve(self, credential_id: str) -> str | None:
        """Decrypt and return the plaintext value, or *None* if missing."""
        from breadmind.config_env import decrypt_value

        data = await self._db.get_setting(f"vault:{credential_id}")
        if not data or "encrypted" not in data:
            return None
        try:
            return decrypt_value(data["encrypted"])
        except Exception:
            logger.warning("Failed to decrypt credential: %s", credential_id)
            return None

    async def delete(self, credential_id: str) -> bool:
        """Remove a credential.  Returns True if it existed."""
        existing = await self._db.get_setting(f"vault:{credential_id}")
        if existing is None:
            return False
        await self._db.delete_setting(f"vault:{credential_id}")
        logger.info("Credential deleted: %s", credential_id)
        return True

    async def exists(self, credential_id: str) -> bool:
        data = await self._db.get_setting(f"vault:{credential_id}")
        return data is not None and "encrypted" in data

    async def list_ids(self, prefix: str = "") -> list[str]:
        """List credential IDs, optionally filtered by *prefix*."""
        full_prefix = f"vault:{prefix}" if prefix else "vault:"
        rows = await self._db.list_settings_by_prefix(full_prefix)
        return [key.removeprefix("vault:") for key in rows]

    # ── Reference helpers ─────────────────────────────────────────────

    @staticmethod
    def make_ref(credential_id: str) -> str:
        """Create a safe reference string for use in chat / LLM context."""
        return f"credential_ref:{credential_id}"

    @staticmethod
    def is_ref(text: str) -> bool:
        return text.startswith("credential_ref:")

    @staticmethod
    def extract_id(ref: str) -> str:
        return ref.removeprefix("credential_ref:")

    # ── Context sanitisation ──────────────────────────────────────────

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Replace detected credential patterns with ``[REDACTED]``.

        Leaves ``credential_ref:xxx`` tokens intact since they are safe.
        """
        if not text:
            return text
        # 1. Protect credential_ref tokens AND their surrounding key labels
        #    e.g. "password: credential_ref:xxx" must not be redacted
        _ref_with_context = re.compile(
            r"(?:\w+\s*[:=]\s*)?credential_ref:[\w:.@\-]+"
        )
        matches = list(_ref_with_context.finditer(text))
        protected = text
        placeholders: dict[str, str] = {}
        for i, m in enumerate(reversed(matches)):
            ph = f"\x00CREF{i}\x00"
            placeholders[ph] = m.group(0)
            protected = protected[:m.start()] + ph + protected[m.end():]
        # 2. Redact sensitive patterns
        result = _SENSITIVE_PATTERNS.sub("[REDACTED]", protected)
        # 3. Restore placeholders
        for ph, original in placeholders.items():
            result = result.replace(ph, original)
        return result

    # ── Migration ─────────────────────────────────────────────────────

    async def migrate_plaintext_credentials(self) -> dict[str, int]:
        """One-time migration of existing plaintext credentials to vault.

        Migrates:
        - ``messenger_token:*`` — plaintext messenger tokens
        - ``oauth:*`` — plaintext OAuth credentials

        Already-encrypted ``apikey:*`` keys are skipped.
        Returns count of migrated items per category.
        """
        counts: dict[str, int] = {"messenger": 0, "oauth": 0}

        # Check if migration already done
        flag = await self._db.get_setting("vault_migration_done")
        if flag:
            return counts

        # 1. Migrate messenger tokens
        try:
            messenger_keys = await self._db.list_settings_by_prefix(
                "messenger_token:"
            )
            for key in messenger_keys:
                data = await self._db.get_setting(key)
                if not data:
                    continue
                # Old format: {"value": "<plaintext>", "stored_at": ...}
                plaintext = data.get("value") if isinstance(data, dict) else None
                if not plaintext:
                    continue
                # Already migrated?
                cred_id = f"messenger:{key.removeprefix('messenger_token:')}"
                if await self.exists(cred_id):
                    continue
                await self.store(cred_id, plaintext)
                await self._db.delete_setting(key)
                counts["messenger"] += 1
        except Exception:
            logger.exception("Messenger token migration error")

        # 2. Migrate OAuth credentials
        try:
            oauth_keys = await self._db.list_settings_by_prefix("oauth:")
            for key in oauth_keys:
                data = await self._db.get_setting(key)
                if not data:
                    continue
                # Old format: JSON string of OAuthCredentials dict
                import json
                if isinstance(data, str):
                    cred_id = key  # "oauth:google:default" etc.
                    if await self.exists(cred_id):
                        continue
                    await self.store(cred_id, data)
                    await self._db.delete_setting(key)
                    counts["oauth"] += 1
        except Exception:
            logger.exception("OAuth credential migration error")

        await self._db.set_setting("vault_migration_done", {"at": time.time()})
        logger.info("Credential migration complete: %s", counts)
        return counts
