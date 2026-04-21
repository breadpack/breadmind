"""Slack Bolt interactive handlers for KB review queue actions."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_WEB_BASE = "https://breadmind.local"  # override via settings in production


def build_candidate_blocks(
    *,
    candidate_id: int,
    title: str,
    body: str,
    category: str,
    confidence: float,
) -> list[dict]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"KB candidate #{candidate_id}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Title*\n{title}"},
                {"type": "mrkdwn", "text": f"*Category*\n`{category}`"},
                {"type": "mrkdwn", "text": f"*Confidence*\n{confidence:.2f}"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": body[:2800]}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "승인"},
                    "style": "primary",
                    "action_id": f"kb_review_approve:{candidate_id}",
                    "value": str(candidate_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "거부"},
                    "style": "danger",
                    "action_id": f"kb_review_reject:{candidate_id}",
                    "value": str(candidate_id),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "수정 후 승인(웹)"},
                    "url": f"{_WEB_BASE}/review/{candidate_id}",
                    "action_id": f"kb_review_web_edit:{candidate_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "기각-이유"},
                    "action_id": f"kb_review_needs_edit:{candidate_id}",
                    "value": str(candidate_id),
                },
            ],
        },
    ]


def _candidate_id_from_action(body: dict) -> int:
    action_id = body["actions"][0]["action_id"]
    return int(action_id.rsplit(":", 1)[1])


async def handle_approve_action(*, ack, body, client, queue) -> None:
    await ack()
    candidate_id = _candidate_id_from_action(body)
    reviewer = body["user"]["id"]
    try:
        await queue.approve(candidate_id, reviewer=reviewer)
    except Exception as exc:  # noqa: BLE001
        logger.warning("approve failed for %s: %s", candidate_id, exc)


async def handle_reject_open_modal(*, ack, body, client) -> None:
    await ack()
    candidate_id = _candidate_id_from_action(body)
    view = {
        "type": "modal",
        "callback_id": "kb_review_reject_modal",
        "private_metadata": str(candidate_id),
        "title": {"type": "plain_text", "text": "Reject candidate"},
        "submit": {"type": "plain_text", "text": "Reject"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "reason_block",
                "label": {"type": "plain_text", "text": "Reason"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason_input",
                    "multiline": True,
                },
            }
        ],
    }
    await client.views_open(trigger_id=body["trigger_id"], view=view)


async def handle_reject_submit(*, ack, body, view, queue) -> None:
    await ack()
    try:
        candidate_id = int(view["private_metadata"])
        reason = view["state"]["values"]["reason_block"]["reason_input"]["value"]
        reviewer = body["user"]["id"]
        await queue.reject(candidate_id, reviewer=reviewer, reason=reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reject submit failed: %s", exc)


async def handle_needs_edit_action(*, ack, body, client, queue) -> None:
    """For the '기각-이유' button we treat as ``needs_edit`` with empty body
    (lead will edit in web UI). This keeps the candidate visible to leads.
    """
    await ack()
    candidate_id = _candidate_id_from_action(body)
    reviewer = body["user"]["id"]
    try:
        await queue.needs_edit(candidate_id, reviewer=reviewer, new_body="")
    except Exception as exc:  # noqa: BLE001
        logger.warning("needs_edit failed: %s", exc)


def register_review_handlers(app, *, queue) -> None:
    """Wire handlers onto a slack_bolt AsyncApp. Call at gateway startup."""
    @app.action(lambda payload: payload.get("action_id", "").startswith("kb_review_approve:"))
    async def _on_approve(ack, body, client):
        await handle_approve_action(ack=ack, body=body, client=client, queue=queue)

    @app.action(lambda payload: payload.get("action_id", "").startswith("kb_review_reject:"))
    async def _on_reject(ack, body, client):
        await handle_reject_open_modal(ack=ack, body=body, client=client)

    @app.view("kb_review_reject_modal")
    async def _on_reject_submit(ack, body, view):
        await handle_reject_submit(ack=ack, body=body, view=view, queue=queue)

    @app.action(lambda payload: payload.get("action_id", "").startswith("kb_review_needs_edit:"))
    async def _on_needs_edit(ack, body, client):
        await handle_needs_edit_action(ack=ack, body=body, client=client, queue=queue)
