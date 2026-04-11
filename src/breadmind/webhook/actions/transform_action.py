"""Action handler that evaluates safe expressions to transform pipeline data."""

from __future__ import annotations

from breadmind.webhook.actions.base import ActionHandler, ActionResult
from breadmind.webhook.models import PipelineAction, PipelineContext
from breadmind.webhook.rule_engine import ConditionError, RuleEngine

_rule_engine = RuleEngine()


class TransformActionHandler(ActionHandler):
    """Evaluate a safe expression and store the result in the pipeline context.

    Uses :class:`~breadmind.webhook.rule_engine.RuleEngine` to safely evaluate
    the expression, blocking forbidden patterns such as ``__import__``.

    Config keys:
        expression (str): A safe Python expression to evaluate.
        output_variable (str): Key under which to store the result in ``ctx.steps``.
    """

    async def execute(self, action: PipelineAction, ctx: PipelineContext) -> ActionResult:
        """Evaluate *expression* and store in ``ctx.steps[output_variable]``."""
        expression: str = action.config.get("expression", "")
        output_variable: str = action.config.get("output_variable", "")

        try:
            result = _rule_engine.evaluate_expression(expression, ctx=ctx)
        except ConditionError as exc:
            return ActionResult(success=False, error=f"Forbidden or invalid expression: {exc}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

        if output_variable:
            ctx.steps[output_variable] = result

        return ActionResult(success=True, output=str(result))
