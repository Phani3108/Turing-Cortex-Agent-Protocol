"""FastAPI adapter: middleware for A2A endpoint governance."""
from __future__ import annotations
from typing import Any, Callable, Optional

from ...models import AgentSpec
from ..enforcer import PolicyEnforcer
from ..audit import AuditLog


class GovernanceMiddleware:
    """ASGI middleware that enforces policies on incoming requests.

    Usage:
        from cortex_protocol.governance.adapters.fastapi import GovernanceMiddleware
        app.add_middleware(GovernanceMiddleware, spec=spec)
    """

    def __init__(
        self,
        app: Any,
        spec: AgentSpec,
        *,
        audit_log: AuditLog | None = None,
        strict_forbidden: bool = False,
    ):
        self.app = app
        self._enforcer = PolicyEnforcer(spec, audit_log=audit_log, strict_forbidden=strict_forbidden)

    async def __call__(self, scope: dict, receive: Callable, send: Callable):
        if scope["type"] == "http":
            self._enforcer.increment_turn()
        await self.app(scope, receive, send)

    @property
    def enforcer(self) -> PolicyEnforcer:
        return self._enforcer
