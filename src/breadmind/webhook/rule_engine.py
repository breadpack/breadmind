"""Safe condition evaluator and rule matching engine for webhook automation."""

from __future__ import annotations

import ast
from typing import Any

from breadmind.webhook.models import PipelineContext, WebhookRule

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class ConditionError(Exception):
    """Raised when a condition expression is unsafe, invalid, or fails at runtime."""


# ---------------------------------------------------------------------------
# AST safety checker
# ---------------------------------------------------------------------------

_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "__import__",
        "exec",
        "eval",
        "compile",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "breakpoint",
        "input",
    }
)

_ALLOWED_NODE_TYPES: frozenset[type] = frozenset(
    {
        ast.Expression,
        ast.BoolOp,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.IfExp,
        ast.Call,
        ast.Constant,
        ast.Attribute,
        ast.Subscript,
        ast.Name,
        ast.Load,
        ast.Tuple,
        ast.List,
        ast.Dict,
        ast.Set,
        ast.Slice,
        ast.Starred,
        # Operators
        ast.And,
        ast.Or,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.LShift,
        ast.RShift,
        ast.BitOr,
        ast.BitXor,
        ast.BitAnd,
        ast.MatMult,
        ast.Invert,
        ast.Not,
        ast.UAdd,
        ast.USub,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Is,
        ast.IsNot,
        ast.In,
        ast.NotIn,
        # Comprehensions
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.comprehension,
        # F-strings
        ast.JoinedStr,
        ast.FormattedValue,
        # Store/Del contexts (needed for comprehension targets)
        ast.Store,
        ast.Del,
    }
)

# Add ast.Index if it exists (removed in Python 3.9+)
try:
    _ALLOWED_NODE_TYPES = _ALLOWED_NODE_TYPES | {ast.Index}  # type: ignore[attr-defined]
except AttributeError:
    pass


def _check_ast(expression: str) -> ast.Expression:
    """Parse and walk the AST; raise ConditionError if unsafe patterns are found."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"Invalid syntax in condition: {exc}") from exc

    for node in ast.walk(tree):
        node_type = type(node)

        if node_type not in _ALLOWED_NODE_TYPES:
            raise ConditionError(
                f"forbidden AST node type: {node_type.__name__}"
            )

        # Block forbidden builtin names
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise ConditionError(
                f"forbidden name in condition: '{node.id}'"
            )

        # Block dunder attribute access (e.g. __class__, __bases__)
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__") and node.attr.endswith("__")
        ):
            raise ConditionError(
                f"forbidden dunder attribute access: '{node.attr}'"
            )

        # Block calls whose function is a forbidden name
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
                raise ConditionError(
                    f"forbidden function call: '{func.id}'"
                )

    return tree


# ---------------------------------------------------------------------------
# Safe builtins
# ---------------------------------------------------------------------------

_SAFE_BUILTINS: dict[str, Any] = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "min": min,
    "max": max,
    "abs": abs,
    "sorted": sorted,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "True": True,
    "False": False,
    "None": None,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
}


# ---------------------------------------------------------------------------
# RuleEngine
# ---------------------------------------------------------------------------


class RuleEngine:
    """Safely evaluates condition expressions and matches webhook rules."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_condition(
        self,
        condition: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> bool:
        """Evaluate *condition* against *payload* and *headers*, returning a bool.

        Raises:
            ConditionError: if the expression is forbidden, syntactically invalid,
                            or raises an exception at runtime.
        """
        result = self.evaluate_expression(condition, payload=payload, headers=headers)
        return bool(result)

    def match_rules(
        self,
        rules: list[WebhookRule],
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> WebhookRule | None:
        """Return the first enabled rule (sorted by priority ascending) whose condition is True.

        Rules with ``enabled=False`` are skipped.  If a condition raises
        :class:`ConditionError` the rule is skipped (treated as non-matching).
        """
        sorted_rules = sorted(rules, key=lambda r: r.priority)
        for rule in sorted_rules:
            if not rule.enabled:
                continue
            try:
                if self.evaluate_condition(rule.condition, payload=payload, headers=headers):
                    return rule
            except ConditionError:
                continue
        return None

    def evaluate_expression(
        self,
        expression: str,
        ctx: PipelineContext | None = None,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Evaluate *expression* and return the raw (non-coerced) result.

        If *ctx* is provided, ``payload``, ``headers``, ``steps`` and
        ``secrets`` are exposed from the context.  Otherwise the *payload* and
        *headers* kwargs are used directly.

        Raises:
            ConditionError: for forbidden patterns, invalid syntax, or runtime errors.
        """
        tree = _check_ast(expression)

        if ctx is not None:
            ns: dict[str, Any] = {
                "payload": ctx.payload,
                "headers": ctx.headers,
                "steps": ctx.steps,
                "secrets": ctx.secrets,
            }
        else:
            ns = {
                "payload": payload if payload is not None else {},
                "headers": headers if headers is not None else {},
            }

        eval_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
        eval_globals.update(_SAFE_BUILTINS)

        try:
            return eval(  # noqa: S307  (intentional sandboxed eval)
                compile(tree, filename="<condition>", mode="eval"),
                eval_globals,
                ns,
            )
        except ConditionError:
            raise
        except Exception as exc:
            raise ConditionError(f"Runtime error evaluating condition: {exc}") from exc
