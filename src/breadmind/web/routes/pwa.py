"""PWA push notification routes."""
from __future__ import annotations

import json
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def setup_pwa_routes(app: FastAPI, app_state):
    """Register push notification API routes."""

    @app.get("/api/push/vapid-key")
    async def get_vapid_key():
        """Return the VAPID public key for push subscriptions."""
        db = app_state._db
        if not db:
            return JSONResponse(status_code=503, content={"error": "Database not available"})

        vapid_keys = await db.get_setting("vapid_keys")
        if not vapid_keys:
            # Generate VAPID key pair on first request
            try:
                vapid_keys = _generate_vapid_keys()
                await db.set_setting("vapid_keys", vapid_keys)
            except Exception as e:
                logger.error("Failed to generate VAPID keys: %s", e)
                return JSONResponse(status_code=500, content={"error": "Failed to generate VAPID keys"})

        return {"publicKey": vapid_keys["publicKey"]}

    @app.post("/api/push/subscribe")
    async def push_subscribe(request: Request):
        """Store a push subscription."""
        db = app_state._db
        if not db:
            return JSONResponse(status_code=503, content={"error": "Database not available"})

        body = await request.json()
        endpoint = body.get("endpoint")
        keys = body.get("keys", {})

        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            return JSONResponse(status_code=400, content={"error": "Invalid subscription data"})

        subscription = {
            "endpoint": endpoint,
            "keys": {
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
            },
        }

        # Store subscriptions as a list in DB settings
        subscriptions = await db.get_setting("push_subscriptions") or []
        # Avoid duplicates by endpoint
        subscriptions = [s for s in subscriptions if s.get("endpoint") != endpoint]
        subscriptions.append(subscription)
        await db.set_setting("push_subscriptions", subscriptions)

        return {"status": "ok"}

    @app.delete("/api/push/subscribe")
    async def push_unsubscribe(request: Request):
        """Remove a push subscription."""
        db = app_state._db
        if not db:
            return JSONResponse(status_code=503, content={"error": "Database not available"})

        body = await request.json()
        endpoint = body.get("endpoint")
        if not endpoint:
            return JSONResponse(status_code=400, content={"error": "Missing endpoint"})

        subscriptions = await db.get_setting("push_subscriptions") or []
        subscriptions = [s for s in subscriptions if s.get("endpoint") != endpoint]
        await db.set_setting("push_subscriptions", subscriptions)

        return {"status": "ok"}


def _generate_vapid_keys() -> dict:
    """Generate a VAPID key pair using cryptography library."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    import base64

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_bytes = private_key.private_numbers().private_value.to_bytes(32, byteorder="big")
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)

    return {
        "publicKey": base64.urlsafe_b64encode(public_bytes).rstrip(b"=").decode("ascii"),
        "privateKey": base64.urlsafe_b64encode(private_bytes).rstrip(b"=").decode("ascii"),
    }


async def send_push(db, title: str, body: str, url: str = "/", tag: str | None = None):
    """Send push notification to all subscribed devices.

    This is a helper function that can be called from other modules.
    Requires pywebpush to be installed.
    """
    if not db:
        return

    subscriptions = await db.get_setting("push_subscriptions") or []
    if not subscriptions:
        return

    vapid_keys = await db.get_setting("vapid_keys")
    if not vapid_keys:
        return

    try:
        from pywebpush import webpush, WebPushException  # noqa: F401
    except ImportError:
        logger.debug("pywebpush not installed, skipping push notification")
        return

    payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag or "breadmind"})
    vapid_claims = {"sub": "mailto:admin@breadmind.local"}

    failed = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=vapid_keys["privateKey"],
                vapid_claims=vapid_claims,
            )
        except Exception as e:
            logger.debug("Push failed for %s: %s", sub.get("endpoint", "?")[:50], e)
            # Mark expired subscriptions for removal
            if "410" in str(e) or "404" in str(e):
                failed.append(sub.get("endpoint"))

    # Clean up expired subscriptions
    if failed:
        subscriptions = [s for s in subscriptions if s.get("endpoint") not in failed]
        await db.set_setting("push_subscriptions", subscriptions)
