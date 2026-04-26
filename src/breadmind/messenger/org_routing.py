"""Tenant-aware messenger → agent dispatch helper (T8).

The Slack gateway only stamps ``IncomingMessage.tenant_native_id`` with the
workspace identifier; resolving it to an internal ``org_projects.id`` UUID
and forwarding the call to ``CoreAgent.handle_message`` lives here so that:

  * the gateway stays decoupled from storage,
  * Discord/Telegram/etc. can reuse the same routing slot once their
    tenant lookups are added,
  * the lookup behaviour (cache, miss-warning, metrics) is unit-testable
    in isolation from slack-bolt and the agent.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from breadmind.messenger.router import IncomingMessage

logger = logging.getLogger(__name__)

# Type alias for ``CoreAgent.handle_message`` (or a compatible coroutine).
AgentHandle = Callable[..., Awaitable[Any]]


async def dispatch_to_agent(
    msg: IncomingMessage,
    db: Any | None,
    agent_handle_message: AgentHandle,
) -> Any:
    """Resolve org_id (Slack only, for now) and forward to the agent.

    .. note::
       (T8 follow-up) This wiring is reachable only after the gateway-side
       ``on_message`` → :meth:`MessageRouter.handle_message` edge is
       connected. Currently :func:`messenger.platforms.create_gateway`
       instantiates gateways with no ``on_message`` callback, so live Slack
       events bypass this dispatcher in production. T8 prepares the
       router-side contract; the gateway-side wiring is tracked separately.

    Behaviour:
      * Non-Slack platforms: skip the lookup, pass ``org_id=None``.
      * Slack with no ``tenant_native_id`` (older payload, malformed event):
        skip the lookup, pass ``org_id=None``.
      * ``db`` is ``None`` (dev/local mode without Postgres): skip the
        lookup, pass ``org_id=None``. No warn log — that path is expected.
      * Otherwise: call ``_lookup_org_id_by_slack_team`` and forward the
        resolved UUID (or ``None`` on miss). The lookup helper handles the
        hit/miss metric + warn-once dedupe internally.
    """
    org_id = None
    if (
        msg.platform == "slack"
        and msg.tenant_native_id
        and db is not None
    ):
        # Imported lazily so the helper stays usable in environments where
        # ``breadmind.memory`` may not be initialized yet (e.g. early
        # bootstrap unit tests).
        from breadmind.memory.runtime import _lookup_org_id_by_slack_team

        org_id = await _lookup_org_id_by_slack_team(msg.tenant_native_id, db)

    return await agent_handle_message(
        msg.text,
        user=msg.user_id,
        channel=msg.channel_id,
        org_id=org_id,
    )
