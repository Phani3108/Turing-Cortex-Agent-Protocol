"""Runtime policy enforcement engine for Cortex Protocol.

PolicyEnforcer intercepts tool calls and LLM responses, checks them
against the governance policies in an AgentSpec, and logs every decision
to an AuditLog. It is framework-agnostic — it never imports any agent
framework. All inputs and outputs are plain strings and dicts.

Design:
- Fail-closed: if a blocking policy can't be evaluated, the action is blocked.
- Audit everything: every check writes an AuditEvent, whether allowed or not.
- Framework-agnostic: tool calls are (name: str, input: dict), responses are str.
"""

from __future__ import annotations

import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..models import AgentSpec
from .audit import AuditEvent, AuditLog
from .exceptions import (
    MaxTurnsExceeded,
    ApprovalRequired,
    ForbiddenActionDetected,
)


def _matches_approval_pattern(tool_name: str, patterns: list[str]) -> bool:
    """Check if tool_name matches any approval pattern.

    Patterns:
      "*"         - matches everything
      "db-*"      - fnmatch glob
      "/^regex/"  - regex (between / delimiters)
      "exact"     - exact string match
    """
    for pattern in patterns:
        if pattern == "*":
            return True
        if pattern.startswith("/") and pattern.endswith("/") and len(pattern) > 2:
            import re
            if re.match(pattern[1:-1], tool_name):
                return True
        elif "*" in pattern or "?" in pattern or "[" in pattern:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        elif tool_name == pattern:
            return True
    return False


@dataclass
class EnforcementResult:
    """The result of a single policy check."""

    allowed: bool
    violations: list[Exception] = field(default_factory=list)
    turn: int = 0
    run_id: str = ""
    event_type: str = ""
    detail: str = ""


class PolicyEnforcer:
    """Runtime policy enforcement for an agent spec.

    Usage:
        enforcer = PolicyEnforcer(spec)

        # At the start of each turn:
        enforcer.increment_turn()     # raises MaxTurnsExceeded at limit

        # Before executing a tool:
        enforcer.check_tool_call("send-email", {"to": "user@example.com"})
        # raises ApprovalRequired if gated

        # After getting an LLM response:
        enforcer.check_response("I'll process the refund now.")
        # logs if forbidden action detected (raises if strict_forbidden=True)

    Every check writes to the audit log regardless of outcome.
    """

    def __init__(
        self,
        spec: AgentSpec,
        *,
        audit_log: Optional[AuditLog] = None,
        strict_forbidden: bool = False,
        approval_handler: Optional[Callable[[str, dict, dict], bool]] = None,
    ):
        self._spec = spec
        self._audit = audit_log or AuditLog()
        self._strict_forbidden = strict_forbidden
        self._approval_handler = approval_handler
        self._run_id = uuid.uuid4().hex[:12]
        self._turn = 0

    @property
    def turn_count(self) -> int:
        return self._turn

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def audit_log(self) -> AuditLog:
        return self._audit

    # ------------------------------------------------------------------
    # max_turns — BLOCKING
    # ------------------------------------------------------------------

    def increment_turn(self) -> EnforcementResult:
        """Increment the turn counter. Raises MaxTurnsExceeded at the limit."""
        self._turn += 1
        max_turns = self._spec.policies.max_turns if self._spec.policies else None

        if max_turns is not None and self._turn > max_turns:
            violation = MaxTurnsExceeded(
                policy="max_turns",
                detail=f"Turn {self._turn} exceeds max_turns={max_turns}",
                run_id=self._run_id,
                turn=self._turn,
                max_turns=max_turns,
            )
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="max_turns",
                allowed=False,
                policy="max_turns",
                detail=f"Turn {self._turn} exceeds limit of {max_turns}",
            ))
            raise violation

        self._audit.write(AuditEvent.now(
            run_id=self._run_id,
            agent=self._spec.agent.name,
            turn=self._turn,
            event_type="turn_start",
            allowed=True,
            detail=f"Turn {self._turn}" + (f" of {max_turns}" if max_turns else ""),
        ))

        return EnforcementResult(
            allowed=True,
            turn=self._turn,
            run_id=self._run_id,
            event_type="turn_start",
        )

    # ------------------------------------------------------------------
    # require_approval — BLOCKING
    # ------------------------------------------------------------------

    def check_tool_call(self, tool_name: str, tool_input: dict | None = None) -> EnforcementResult:
        """Check whether a tool call is permitted.

        Raises ApprovalRequired if the tool is in require_approval.
        Logs the check regardless.
        """
        tool_input = tool_input or {}
        require_approval = (
            self._spec.policies.require_approval
            if self._spec.policies
            else []
        )

        if _matches_approval_pattern(tool_name, require_approval):
            if self._approval_handler is not None:
                context = {
                    "run_id": self._run_id,
                    "turn": self._turn,
                    "agent": self._spec.agent.name,
                }
                approved = self._approval_handler(tool_name, tool_input, context)
                if approved:
                    self._audit.write(AuditEvent.now(
                        run_id=self._run_id,
                        agent=self._spec.agent.name,
                        turn=self._turn,
                        event_type="tool_approved",
                        allowed=True,
                        policy="require_approval",
                        tool_name=tool_name,
                        tool_input=tool_input,
                        detail=f"Tool '{tool_name}' approved by handler",
                    ))
                    return EnforcementResult(
                        allowed=True,
                        turn=self._turn,
                        run_id=self._run_id,
                        event_type="tool_approved",
                        detail=f"Tool '{tool_name}' approved by handler",
                    )
                else:
                    self._audit.write(AuditEvent.now(
                        run_id=self._run_id,
                        agent=self._spec.agent.name,
                        turn=self._turn,
                        event_type="tool_denied",
                        allowed=False,
                        policy="require_approval",
                        tool_name=tool_name,
                        tool_input=tool_input,
                        detail=f"Tool '{tool_name}' denied by handler",
                    ))
                    raise ApprovalRequired(
                        policy="require_approval",
                        detail=f"Tool '{tool_name}' denied by approval handler",
                        run_id=self._run_id,
                        turn=self._turn,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )

            violation = ApprovalRequired(
                policy="require_approval",
                detail=f"Tool '{tool_name}' requires human approval before execution",
                run_id=self._run_id,
                turn=self._turn,
                tool_name=tool_name,
                tool_input=tool_input,
            )
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="tool_blocked",
                allowed=False,
                policy="require_approval",
                tool_name=tool_name,
                tool_input=tool_input,
                detail=f"Approval required for '{tool_name}'",
            ))
            raise violation

        # Tool call allowed
        self._audit.write(AuditEvent.now(
            run_id=self._run_id,
            agent=self._spec.agent.name,
            turn=self._turn,
            event_type="tool_call",
            allowed=True,
            tool_name=tool_name,
            tool_input=tool_input,
            detail=f"Tool '{tool_name}' executed",
        ))

        return EnforcementResult(
            allowed=True,
            turn=self._turn,
            run_id=self._run_id,
            event_type="tool_call",
            detail=f"Tool '{tool_name}' allowed",
        )

    # ------------------------------------------------------------------
    # async require_approval — BLOCKING
    # ------------------------------------------------------------------

    async def async_check_tool_call(self, tool_name: str, tool_input: dict | None = None) -> EnforcementResult:
        """Async version of check_tool_call. Awaits async approval handlers."""
        import asyncio

        tool_input = tool_input or {}
        require_approval = (
            self._spec.policies.require_approval
            if self._spec.policies
            else []
        )

        if not _matches_approval_pattern(tool_name, require_approval):
            event = AuditEvent.now(
                run_id=self._run_id, agent=self._spec.agent.name, turn=self._turn,
                event_type="tool_call", tool_name=tool_name, tool_input=tool_input,
                allowed=True, detail=f"Tool {tool_name} allowed",
            )
            self._audit.write(event)
            return EnforcementResult(allowed=True, turn=self._turn, run_id=self._run_id, event_type="tool_call")

        if self._approval_handler:
            context = {"run_id": self._run_id, "turn": self._turn, "agent": self._spec.agent.name}
            if asyncio.iscoroutinefunction(self._approval_handler):
                approved = await self._approval_handler(tool_name, tool_input, context)
            else:
                approved = self._approval_handler(tool_name, tool_input, context)

            if approved:
                event = AuditEvent.now(
                    run_id=self._run_id, agent=self._spec.agent.name, turn=self._turn,
                    event_type="tool_approved", tool_name=tool_name, tool_input=tool_input,
                    allowed=True, detail=f"Tool {tool_name} approved by handler",
                )
                self._audit.write(event)
                return EnforcementResult(allowed=True, turn=self._turn, run_id=self._run_id, event_type="tool_approved")
            else:
                event = AuditEvent.now(
                    run_id=self._run_id, agent=self._spec.agent.name, turn=self._turn,
                    event_type="tool_denied", tool_name=tool_name, tool_input=tool_input,
                    policy="require_approval", allowed=False,
                    detail=f"Tool {tool_name} denied by handler",
                )
                self._audit.write(event)
                raise ApprovalRequired(
                    policy="require_approval",
                    detail=f"Tool '{tool_name}' denied by approval handler",
                    run_id=self._run_id, turn=self._turn,
                    tool_name=tool_name, tool_input=tool_input,
                )

        event = AuditEvent.now(
            run_id=self._run_id, agent=self._spec.agent.name, turn=self._turn,
            event_type="tool_blocked", tool_name=tool_name, tool_input=tool_input,
            policy="require_approval", allowed=False,
            detail=f"Tool {tool_name} requires approval (no handler)",
        )
        self._audit.write(event)
        raise ApprovalRequired(
            policy="require_approval",
            detail=f"Tool '{tool_name}' requires human approval",
            run_id=self._run_id, turn=self._turn,
            tool_name=tool_name, tool_input=tool_input or {},
        )

    # ------------------------------------------------------------------
    # forbidden_actions — ADVISORY (optionally BLOCKING)
    # ------------------------------------------------------------------

    def check_response(self, response_text: str) -> EnforcementResult:
        """Check an LLM response against forbidden_actions.

        By default, violations are logged but not blocking.
        Set strict_forbidden=True in the constructor to make them blocking.
        """
        forbidden = (
            self._spec.policies.forbidden_actions
            if self._spec.policies
            else []
        )

        violations = []
        for action in forbidden:
            # Case-insensitive substring match
            if action.lower() in response_text.lower():
                violations.append(
                    ForbiddenActionDetected(
                        policy="forbidden_actions",
                        detail=f"Response matches forbidden action: '{action}'",
                        run_id=self._run_id,
                        turn=self._turn,
                        action=action,
                        response_text=response_text[:500],  # truncate for log
                    )
                )

        if violations:
            for v in violations:
                self._audit.write(AuditEvent.now(
                    run_id=self._run_id,
                    agent=self._spec.agent.name,
                    turn=self._turn,
                    event_type="forbidden_action",
                    allowed=not self._strict_forbidden,
                    policy="forbidden_actions",
                    detail=v.detail,
                ))

            if self._strict_forbidden:
                raise violations[0]

            return EnforcementResult(
                allowed=True,  # advisory: allowed but flagged
                violations=violations,
                turn=self._turn,
                run_id=self._run_id,
                event_type="forbidden_action",
                detail=f"{len(violations)} forbidden action(s) detected (advisory)",
            )

        # Clean response
        self._audit.write(AuditEvent.now(
            run_id=self._run_id,
            agent=self._spec.agent.name,
            turn=self._turn,
            event_type="response",
            allowed=True,
            detail="Response checked — no violations",
        ))

        return EnforcementResult(
            allowed=True,
            turn=self._turn,
            run_id=self._run_id,
            event_type="response",
        )

    # ------------------------------------------------------------------
    # escalation — ADVISORY
    # ------------------------------------------------------------------

    def check_escalation(self, context: dict | None = None) -> EnforcementResult:
        """Check whether escalation conditions are met.

        This is advisory only — the enforcer logs the match but doesn't
        own the routing. The caller decides what to do.
        """
        context = context or {}
        escalation = (
            self._spec.policies.escalation
            if self._spec.policies
            else None
        )

        if not escalation or not escalation.trigger:
            return EnforcementResult(
                allowed=True,
                turn=self._turn,
                run_id=self._run_id,
                event_type="escalation",
                detail="No escalation trigger configured",
            )

        # Simple keyword match: check if trigger keywords appear in context values
        trigger_lower = escalation.trigger.lower()
        context_text = " ".join(str(v) for v in context.values()).lower()
        matched = any(
            keyword in context_text
            for keyword in trigger_lower.split()
            if len(keyword) > 3  # skip short words like "is", "or", "and"
        )

        if matched:
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="escalation",
                allowed=True,  # advisory — not blocking
                policy="escalation",
                detail=f"Escalation trigger matched: '{escalation.trigger}' → target: {escalation.target}",
            ))
            return EnforcementResult(
                allowed=True,
                turn=self._turn,
                run_id=self._run_id,
                event_type="escalation",
                detail=f"Escalation recommended to {escalation.target}",
            )

        return EnforcementResult(
            allowed=True,
            turn=self._turn,
            run_id=self._run_id,
            event_type="escalation",
            detail="No escalation trigger matched",
        )
