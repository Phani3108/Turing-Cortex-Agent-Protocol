"""LangChain adapter: GovernedRunnable wraps any Runnable with policy enforcement."""
from __future__ import annotations
from typing import Any, Optional

from ...models import AgentSpec
from ..enforcer import PolicyEnforcer
from ..audit import AuditLog


class GovernedRunnable:
    """Wraps a LangChain Runnable with PolicyEnforcer checks.

    Usage:
        from cortex_protocol.governance.adapters.langchain import GovernedRunnable
        governed = GovernedRunnable(my_chain, spec)
        result = governed.invoke("Hello")
    """

    def __init__(
        self,
        runnable: Any,
        spec: AgentSpec,
        *,
        audit_log: Optional[AuditLog] = None,
        strict_forbidden: bool = False,
        approval_handler=None,
    ):
        self._runnable = runnable
        self._enforcer = PolicyEnforcer(
            spec, audit_log=audit_log,
            strict_forbidden=strict_forbidden,
            approval_handler=approval_handler,
        )

    def invoke(self, input: Any, **kwargs) -> Any:
        self._enforcer.increment_turn()
        result = self._runnable.invoke(input, **kwargs)
        text = str(result) if not isinstance(result, str) else result
        self._enforcer.check_response(text)
        return result

    @property
    def enforcer(self) -> PolicyEnforcer:
        return self._enforcer
