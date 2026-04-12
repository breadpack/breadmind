"""External credential input via temporary URL pages.

When a messenger channel (Slack, Discord, etc.) needs credentials,
this module generates a one-time URL that serves a standalone HTML form.
The user opens the URL in a browser, fills in credentials, and the
password fields are encrypted in the CredentialVault.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["credential-input"])

# ── Token Store ──────────────────────────────────────────────────────

DEFAULT_TTL = 300  # 5 minutes
MAX_PENDING = 100


@dataclass
class _TokenEntry:
    form: dict
    callback: dict
    created_at: float
    csrf_token: str
    used: bool = False


class ExternalInputTokenStore:
    """In-memory store for one-time credential input tokens."""

    def __init__(self) -> None:
        self._tokens: dict[str, _TokenEntry] = {}

    def create(
        self,
        form: dict,
        callback: dict,
        base_url: str = "",
    ) -> dict:
        """Create a one-time token and return {url, token, expires_at}."""
        self._cleanup_expired()

        # Enforce max pending tokens
        if len(self._tokens) >= MAX_PENDING:
            oldest_key = min(self._tokens, key=lambda k: self._tokens[k].created_at)
            del self._tokens[oldest_key]

        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(16)
        now = time.time()

        self._tokens[token] = _TokenEntry(
            form=form,
            callback=callback,
            created_at=now,
            csrf_token=csrf,
        )

        url = f"{base_url}/credential-input/{token}"
        return {
            "url": url,
            "token": token,
            "expires_at": now + DEFAULT_TTL,
        }

    def validate(self, token: str) -> _TokenEntry | None:
        """Return the entry if token is valid, unexpired, and unused."""
        entry = self._tokens.get(token)
        if not entry:
            return None
        if entry.used:
            return None
        if time.time() - entry.created_at > DEFAULT_TTL:
            del self._tokens[token]
            return None
        return entry

    def mark_used(self, token: str) -> None:
        entry = self._tokens.get(token)
        if entry:
            entry.used = True

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._tokens.items()
                   if now - v.created_at > DEFAULT_TTL]
        for k in expired:
            del self._tokens[k]


# Singleton store
_token_store = ExternalInputTokenStore()


def get_token_store() -> ExternalInputTokenStore:
    return _token_store


# ── Pydantic models ──────────────────────────────────────────────────

class _ExtFieldSubmit(BaseModel):
    name: str
    value: str
    type: str = "text"


class _ExtSubmitRequest(BaseModel):
    csrf_token: str
    fields: list[_ExtFieldSubmit]


# ── Helper: resolve base URL ─────────────────────────────────────────

def _get_base_url(request: Request | None = None) -> str:
    """Determine base URL from env or request headers."""
    env_url = os.environ.get("BREADMIND_BASE_URL", "").rstrip("/")
    if env_url:
        return env_url
    if request:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost:8080"))
        return f"{scheme}://{host}"
    return "http://localhost:8080"


# ── HTML page generator ──────────────────────────────────────────────

def _render_form_page(entry: _TokenEntry, token: str) -> str:
    """Generate a standalone HTML page for the credential form."""
    form = entry.form
    title = form.get("title", "Credential Input")
    fields = form.get("fields", [])
    csrf = entry.csrf_token

    fields_html = ""
    for f in fields:
        ftype = f.get("type", "text")
        fname = f.get("name", "")
        flabel = f.get("label", fname)
        input_type = "password" if ftype == "password" else "text"
        fields_html += f"""
        <div class="field">
          <label for="{fname}">{flabel}</label>
          <input type="{input_type}" id="{fname}" name="{fname}"
                 data-field-type="{ftype}" required autocomplete="off">
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - BreadMind</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0a0a0f;
  color: #e0e0e0;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 20px;
}}
.card {{
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 16px;
  padding: 32px;
  max-width: 420px;
  width: 100%;
  backdrop-filter: blur(20px);
}}
.card h1 {{
  font-size: 1.3rem;
  margin-bottom: 8px;
  color: #fff;
}}
.card .subtitle {{
  font-size: 0.85rem;
  color: #888;
  margin-bottom: 24px;
}}
.field {{
  margin-bottom: 16px;
}}
.field label {{
  display: block;
  font-size: 0.85rem;
  color: #aaa;
  margin-bottom: 6px;
}}
.field input {{
  width: 100%;
  padding: 10px 14px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 8px;
  color: #fff;
  font-size: 0.95rem;
  outline: none;
  transition: border-color 0.2s;
}}
.field input:focus {{
  border-color: #6366f1;
}}
.btn {{
  width: 100%;
  padding: 12px;
  background: #6366f1;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
  margin-top: 8px;
  transition: background 0.2s;
}}
.btn:hover {{ background: #4f46e5; }}
.btn:disabled {{
  background: #333;
  cursor: not-allowed;
}}
.status {{
  margin-top: 16px;
  text-align: center;
  font-size: 0.9rem;
  min-height: 24px;
}}
.status.ok {{ color: #4ade80; }}
.status.err {{ color: #f87171; }}
.lock-icon {{
  text-align: center;
  font-size: 2rem;
  margin-bottom: 12px;
}}
</style>
</head>
<body>
<div class="card">
  <div class="lock-icon">&#128274;</div>
  <h1>{title}</h1>
  <p class="subtitle">BreadMind</p>
  <form id="credForm">
    {fields_html}
    <input type="hidden" name="_csrf" value="{csrf}">
    <button type="submit" class="btn" id="submitBtn">Submit</button>
  </form>
  <div class="status" id="status"></div>
</div>
<script>
document.getElementById('credForm').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('submitBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  btn.textContent = 'Submitting...';
  status.textContent = '';
  status.className = 'status';

  const fields = [];
  document.querySelectorAll('#credForm input[name]:not([name="_csrf"])').forEach(inp => {{
    fields.push({{
      name: inp.name,
      value: inp.value,
      type: inp.dataset.fieldType || 'text'
    }});
  }});

  try {{
    const res = await fetch('/api/vault/submit-external/{token}', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{
        csrf_token: '{csrf}',
        fields: fields
      }})
    }});
    const data = await res.json();
    if (res.ok && data.success) {{
      status.textContent = 'Submitted successfully. You can close this page.';
      status.className = 'status ok';
      btn.textContent = 'Done';
    }} else {{
      status.textContent = data.error || 'Submission failed.';
      status.className = 'status err';
      btn.disabled = false;
      btn.textContent = 'Submit';
    }}
  }} catch (err) {{
    status.textContent = 'Network error. Please try again.';
    status.className = 'status err';
    btn.disabled = false;
    btn.textContent = 'Submit';
  }}
}});
</script>
</body>
</html>"""


def _render_error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BreadMind</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: #0a0a0f; color: #e0e0e0;
  display: flex; justify-content: center; align-items: center;
  min-height: 100vh;
}}
.card {{
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 16px; padding: 32px;
  max-width: 420px; width: 100%; text-align: center;
}}
.card h1 {{ font-size: 1.2rem; color: #f87171; margin-bottom: 12px; }}
.card p {{ color: #888; }}
</style>
</head>
<body>
<div class="card">
  <h1>{message}</h1>
  <p>Please request a new link from BreadMind.</p>
</div>
</body>
</html>"""


# ── Routes ───────────────────────────────────────────────────────────

def setup_credential_input_routes(r: APIRouter, app_state):
    """Register external credential input routes."""

    @r.get("/credential-input/{token}")
    async def credential_input_page(token: str):
        """Serve the standalone credential input form."""
        store = get_token_store()
        entry = store.validate(token)
        if not entry:
            return HTMLResponse(
                _render_error_page("Link expired or invalid"),
                status_code=410,
            )
        return HTMLResponse(_render_form_page(entry, token))

    @r.post("/api/vault/submit-external/{token}")
    async def submit_external_credential(token: str, body: _ExtSubmitRequest, request: Request):
        """Validate token, store credentials, notify callback channel."""
        store = get_token_store()
        entry = store.validate(token)
        if not entry:
            return JSONResponse(
                status_code=410,
                content={"error": "token_expired", "success": False},
            )

        # CSRF check
        if body.csrf_token != entry.csrf_token:
            return JSONResponse(
                status_code=403,
                content={"error": "csrf_mismatch", "success": False},
            )

        # Validate fields match expected schema
        expected_names = {f["name"] for f in entry.form.get("fields", [])}
        submitted_names = {f.name for f in body.fields}
        if not expected_names.issubset(submitted_names):
            missing = expected_names - submitted_names
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_fields",
                    "detail": f"Missing fields: {', '.join(missing)}",
                    "success": False,
                },
            )

        # Store credentials in vault
        vault = getattr(request.app.state, "credential_vault", None)
        if not vault:
            return JSONResponse(
                status_code=500,
                content={"error": "storage_error", "detail": "Vault not available", "success": False},
            )

        form_id = entry.form.get("id", "external")
        refs: dict[str, str] = {}

        try:
            for f in body.fields:
                if f.type == "password":
                    cred_id = f"ext:{form_id}:{f.name}"
                    await vault.store(cred_id, f.value)
                    refs[f.name] = vault.make_ref(cred_id)
        except Exception:
            logger.exception("Failed to store credential in vault")
            return JSONResponse(
                status_code=500,
                content={"error": "storage_error", "success": False},
            )

        # Mark token as used
        store.mark_used(token)

        # Send callback notification (fire-and-forget)
        callback = entry.callback
        if callback and callback.get("platform") and callback.get("channel_id"):
            try:
                message_router = getattr(app_state, "_message_router", None)
                if message_router:
                    msg = callback.get("message", "Credentials submitted successfully.")
                    await message_router.send_message(
                        callback["platform"],
                        callback["channel_id"],
                        msg,
                    )
            except Exception:
                logger.warning("Failed to send callback notification", exc_info=True)

        return {"success": True, "refs": refs}
