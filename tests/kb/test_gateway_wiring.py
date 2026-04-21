"""Tests for Slack gateway + worker KB wiring (Task 17).

Invariant: ``register_review_handlers`` + ``register_feedback_handlers`` together
register at least 4 actions + 1 view. Uses a ``FakeApp`` to record registrations
without requiring a real slack_bolt AsyncApp.
"""
from __future__ import annotations


async def test_gateway_registers_review_and_feedback_handlers(
    db, seeded_project, fake_slack_client,
):
    """Counts handler registrations on a fake slack_bolt app.

    Actual shape, per sources in ``breadmind.kb.slack_review_handlers`` and
    ``breadmind.kb.feedback``:

    * ``register_review_handlers``: 3 ``@app.action`` + 1 ``@app.view`` = 4
    * ``register_feedback_handlers``: 1 ``@app.action`` = 1
    * Total: 4 actions + 1 view = 5 registrations
    """
    registered: list[tuple] = []

    class FakeApp:
        def action(self, matcher):
            def decorator(func):
                registered.append(("action", matcher, func))
                return func
            return decorator

        def view(self, callback_id: str):
            def decorator(func):
                registered.append(("view", callback_id, func))
                return func
            return decorator

    from breadmind.kb.feedback import FeedbackHandler, register_feedback_handlers
    from breadmind.kb.review_queue import ReviewQueue
    from breadmind.kb.slack_review_handlers import register_review_handlers

    app = FakeApp()
    queue = ReviewQueue(db, fake_slack_client)
    register_review_handlers(app, queue=queue)
    register_feedback_handlers(app, handler=FeedbackHandler(db, fake_slack_client))

    action_count = sum(1 for k, _, _ in registered if k == "action")
    view_count = sum(1 for k, _, _ in registered if k == "view")
    # Flexible assertion: verifies handlers are registered, not an exact count.
    assert action_count + view_count >= 5
    assert view_count >= 1
    assert action_count >= 4


def test_slack_gateway_accepts_kb_db_kwarg():
    """``SlackGateway.__init__`` must accept ``kb_db`` without breaking the
    existing 3-arg constructor contract (``bot_token``, ``app_token``,
    ``on_message``). No event loop needed — we only exercise ``__init__``.
    """
    from breadmind.messenger.slack import SlackGateway

    gw_no_kb = SlackGateway(bot_token="xoxb-test")
    assert getattr(gw_no_kb, "_kb_db", "MISSING") is None

    sentinel = object()
    gw_with_kb = SlackGateway(bot_token="xoxb-test", kb_db=sentinel)
    assert gw_with_kb._kb_db is sentinel


def test_worker_bootstrap_exposes_slack_client_global():
    """The worker module must expose a ``_slack_client`` module-level global
    so downstream KB helpers (digests, DMs) can import it.
    """
    from breadmind.tasks import worker

    assert hasattr(worker, "_slack_client")
