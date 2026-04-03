"""LangGraph adapter: governance wrappers for graph nodes."""
from __future__ import annotations
from typing import Any, Callable

from ...models import AgentSpec
from ..enforcer import PolicyEnforcer
from ..audit import AuditLog


def governed_tool_node(
    spec: AgentSpec,
    *,
    audit_log: AuditLog | None = None,
    approval_handler=None,
) -> Callable:
    """Decorator: wraps a LangGraph tool function with check_tool_call."""
    enforcer = PolicyEnforcer(spec, audit_log=audit_log, approval_handler=approval_handler)

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            tool_name = getattr(fn, "name", fn.__name__)
            tool_input = kwargs if kwargs else ({"input": args[0]} if args else {})
            enforcer.check_tool_call(tool_name, tool_input)
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__wrapped__ = fn
        wrapper._enforcer = enforcer
        return wrapper
    return decorator


def governed_agent_node(
    spec: AgentSpec,
    *,
    audit_log: AuditLog | None = None,
    strict_forbidden: bool = False,
) -> Callable:
    """Decorator: wraps a LangGraph agent node with turn + response enforcement."""
    enforcer = PolicyEnforcer(spec, audit_log=audit_log, strict_forbidden=strict_forbidden)

    def decorator(fn: Callable) -> Callable:
        def wrapper(state: dict) -> dict:
            enforcer.increment_turn()
            result = fn(state)
            # Check last message if present
            messages = result.get("messages", [])
            if messages:
                last = messages[-1]
                text = getattr(last, "content", str(last))
                enforcer.check_response(text)
            return result
        wrapper.__name__ = fn.__name__
        wrapper.__wrapped__ = fn
        wrapper._enforcer = enforcer
        return wrapper
    return decorator
