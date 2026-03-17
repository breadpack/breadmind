import hashlib
import hmac
import logging
import secrets
import time

from fastapi import Request, WebSocket

logger = logging.getLogger(__name__)


class AuthManager:
    """Session-based authentication for BreadMind web UI."""

    def __init__(self, password_hash: str = "", api_keys: list[str] = None, session_timeout: int = 86400):
        self._password_hash = password_hash  # SHA-256 hash of password
        self._api_keys: set[str] = set(api_keys or [])
        self._sessions: dict[str, dict] = {}  # token -> {created_at, ip, user_agent}
        self._session_timeout = session_timeout  # seconds, default 24h
        self._enabled = bool(password_hash) or bool(self._api_keys)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

    def verify_password(self, password: str) -> bool:
        return hmac.compare_digest(self.hash_password(password), self._password_hash)

    def verify_api_key(self, key: str) -> bool:
        return key in self._api_keys

    def create_session(self, ip: str = "", user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "created_at": time.time(),
            "ip": ip,
            "user_agent": user_agent,
        }
        return token

    def verify_session(self, token: str) -> bool:
        session = self._sessions.get(token)
        if not session:
            return False
        if time.time() - session["created_at"] > self._session_timeout:
            del self._sessions[token]
            return False
        return True

    def revoke_session(self, token: str):
        self._sessions.pop(token, None)

    def authenticate_request(self, request: Request) -> bool:
        """Check if request is authenticated via session cookie or API key header."""
        if not self._enabled:
            return True

        # Check API key header
        api_key = request.headers.get("X-API-Key", "")
        if api_key and self.verify_api_key(api_key):
            return True

        # Check session cookie
        token = request.cookies.get("breadmind_session", "")
        if token and self.verify_session(token):
            return True

        # Check Authorization header (Bearer token)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and self.verify_session(auth[7:]):
            return True

        return False

    def authenticate_websocket(self, websocket: WebSocket) -> bool:
        """Check WebSocket authentication via query param or cookie."""
        if not self._enabled:
            return True

        # Check query param
        token = websocket.query_params.get("token", "")
        if token and self.verify_session(token):
            return True

        # Check cookie
        token = websocket.cookies.get("breadmind_session", "")
        if token and self.verify_session(token):
            return True

        return False

    def cleanup_expired(self):
        """Remove expired sessions."""
        now = time.time()
        expired = [t for t, s in self._sessions.items() if now - s["created_at"] > self._session_timeout]
        for t in expired:
            del self._sessions[t]

    def get_active_sessions(self) -> int:
        self.cleanup_expired()
        return len(self._sessions)
