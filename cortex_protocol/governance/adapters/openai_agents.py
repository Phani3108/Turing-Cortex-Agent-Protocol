"""OpenAI Agents SDK adapter: guardrails and governed tools."""
from __future__ import annotations
from typing import Any, Callable

from ...models import AgentSpec
from ..enforcer import PolicyEnforcer
from ..audit import AuditLog


def cortex_guardrail(
    spec: AgentSpec,
    *,
    audit_log: AuditLog | None = None,
    strict_forbidden: bool = False,
) -> Callable:
    """Returns a guardrail function compatible with OpenAI Agents SDK.

    Usage:
        guardrail = cortex_guardrail(spec)
        agent = Agent(name="x", guardrails=[guardrail])
    """
    enforcer = PolicyEnforcer(spec, audit_log=audit_log, strict_forbidden=strict_forbidden)

    def guardrail_fn(context: Any, agent: Any, input_text: str) -> str | None:
        enforcer.increment_turn()
        result = enforcer.check_response(input_text)
        if not result.allowed:
            return f"Policy violation: {result.detail}"
        return None  # None = no guardrail tripwire, continue

    guardrail_fn._enforcer = enforcer
    return guardrail_fn


def governed_function_tool(
    spec: AgentSpec,
    *,
    audit_log: AuditLog | None = None,
    approval_handler=None,
) -> Callable:
    """Decorator: wraps a @function_tool with check_tool_call enforcement."""
    enforcer = PolicyEnforcer(spec, audit_log=audit_log, approval_handler=approval_handler)

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            tool_name = getattr(fn, "__name__", "unknown")
            enforcer.check_tool_call(tool_name, kwargs)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__wrapped__ = fn
        wrapper._enforcer = enforcer
        return wrapper
    return decorator
