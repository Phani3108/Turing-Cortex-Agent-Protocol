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
from .cost import CostTracker, ModelPricing
from .dsl import RuleAction, RuleSet
from .exceptions import (
    MaxTurnsExceeded,
    ApprovalRequired,
    ForbiddenActionDetected,
    BudgetExceeded,
    RuleDenied,
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
        pricing: Optional[ModelPricing] = None,
        cost_tracker: Optional[CostTracker] = None,
    ):
        self._spec = spec
        self._audit = audit_log or AuditLog()
        self._strict_forbidden = strict_forbidden
        self._approval_handler = approval_handler
        self._run_id = uuid.uuid4().hex[:12]
        self._turn = 0
        self._cost = cost_tracker or CostTracker(pricing=pricing)
        # Compile DSL rules once. Bad rules fail at spec-load time.
        raw_rules = list(spec.policies.rules) if spec.policies else []
        self._rules = RuleSet.from_list(raw_rules)

    @property
    def cost(self) -> CostTracker:
        return self._cost

    @property
    def rules(self) -> RuleSet:
        return self._rules

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
    # cost / token / tool-call budgets — BLOCKING
    # ------------------------------------------------------------------

    def _budget_check(self, *, projected_cost: float = 0.0, projected_tokens: int = 0,
                      projecting_tool_call: bool = False) -> None:
        """Raise BudgetExceeded if the projected call would breach a policy cap."""
        policies = self._spec.policies
        if policies is None:
            return

        if policies.max_cost_usd is not None and self._cost.would_exceed_cost(
            policies.max_cost_usd, projected_cost
        ):
            observed = self._cost.snapshot.total_cost_usd + projected_cost
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="budget_blocked",
                allowed=False,
                policy="max_cost_usd",
                detail=f"Projected cost ${observed:.4f} exceeds cap ${policies.max_cost_usd:.4f}",
                run_cost_usd=self._cost.snapshot.total_cost_usd,
            ))
            raise BudgetExceeded(
                policy="max_cost_usd",
                detail=f"Cost cap ${policies.max_cost_usd:.4f} exceeded (observed ${observed:.4f})",
                run_id=self._run_id, turn=self._turn,
                budget_type="cost_usd",
                limit=policies.max_cost_usd,
                observed=observed,
            )

        if policies.max_tokens_per_run is not None and self._cost.would_exceed_tokens(
            policies.max_tokens_per_run, projected_tokens
        ):
            observed = self._cost.snapshot.total_tokens + projected_tokens
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="budget_blocked",
                allowed=False,
                policy="max_tokens_per_run",
                detail=f"Projected tokens {observed} exceeds cap {policies.max_tokens_per_run}",
                run_cost_usd=self._cost.snapshot.total_cost_usd,
            ))
            raise BudgetExceeded(
                policy="max_tokens_per_run",
                detail=f"Token cap {policies.max_tokens_per_run} exceeded (observed {observed})",
                run_id=self._run_id, turn=self._turn,
                budget_type="tokens",
                limit=float(policies.max_tokens_per_run),
                observed=float(observed),
            )

        if projecting_tool_call and policies.max_tool_calls_per_run is not None \
                and self._cost.would_exceed_tool_calls(policies.max_tool_calls_per_run):
            observed = self._cost.snapshot.total_tool_calls + 1
            self._audit.write(AuditEvent.now(
                run_id=self._run_id,
                agent=self._spec.agent.name,
                turn=self._turn,
                event_type="budget_blocked",
                allowed=False,
                policy="max_tool_calls_per_run",
                detail=f"Projected tool calls {observed} exceeds cap {policies.max_tool_calls_per_run}",
                run_cost_usd=self._cost.snapshot.total_cost_usd,
            ))
            raise BudgetExceeded(
                policy="max_tool_calls_per_run",
                detail=f"Tool-call cap {policies.max_tool_calls_per_run} exceeded (observed {observed})",
                run_id=self._run_id, turn=self._turn,
                budget_type="tool_calls",
                limit=float(policies.max_tool_calls_per_run),
                observed=float(observed),
            )

    def _rule_context(self, tool_name: str, tool_input: dict) -> dict:
        """Snapshot state the DSL can read. Never leak live objects.

        Keys:
          tool_name   : str
          tool_input  : dict
          turn        : int
          run_id      : str
          agent       : str
          env         : str (from agent metadata.environment, if set)
          tags        : list[str] (from agent metadata.tags)
          run_cost_usd, total_tokens, total_tool_calls
        """
        meta = self._spec.metadata
        return {
            "tool_name": tool_name,
            "tool_input": dict(tool_input),
            "turn": self._turn,
            "run_id": self._run_id,
            "agent": self._spec.agent.name,
            "env": meta.environment if meta else "",
            "tags": list(meta.tags) if meta else [],
            "run_cost_usd": self._cost.snapshot.total_cost_usd,
            "total_tokens": self._cost.snapshot.total_tokens,
            "total_tool_calls": self._cost.snapshot.total_tool_calls,
        }

    def _apply_dsl_rules(self, tool_name: str, tool_input: dict) -> bool:
        """Evaluate compiled DSL rules. Returns True iff an `allow` fired.

        Side effects:
          - Raises `RuleDenied` on a `deny` match.
          - Appends to the audit trail.
          - For `require_approval` matches, invokes the approval handler
            (or raises `ApprovalRequired` if none is set).
        """
        if not self._rules.rules:
            return False
        ctx = self._rule_context(tool_name, tool_input)
        decision = self._rules.evaluate(ctx)

        if decision.action is RuleAction.ALLOW:
            if decision.rule_source:
                self._audit.write(AuditEvent.now(
                    run_id=self._run_id, agent=self._spec.agent.name,
                    turn=self._turn, event_type="rule_allow",
                    allowed=True, policy="rule:allow",
                    tool_name=tool_name, tool_input=tool_input,
                    detail=decision.reason or f"allowed by rule: {decision.rule_source}",
                ))
                return True
            return False

        if decision.action is RuleAction.DENY:
            self._audit.write(AuditEvent.now(
                run_id=self._run_id, agent=self._spec.agent.name,
                turn=self._turn, event_type="rule_denied",
                allowed=False, policy="rule:deny",
                tool_name=tool_name, tool_input=tool_input,
                detail=decision.reason or f"denied by rule: {decision.rule_source}",
            ))
            raise RuleDenied(
                policy="rule:deny",
                detail=decision.reason or f"Denied by DSL rule: {decision.rule_source}",
                run_id=self._run_id, turn=self._turn,
                tool_name=tool_name, tool_input=tool_input,
                rule_source=decision.rule_source,
            )

        if decision.action is RuleAction.REQUIRE_APPROVAL:
            if self._approval_handler is None:
                self._audit.write(AuditEvent.now(
                    run_id=self._run_id, agent=self._spec.agent.name,
                    turn=self._turn, event_type="tool_blocked",
                    allowed=False, policy="rule:require_approval",
                    tool_name=tool_name, tool_input=tool_input,
                    detail=decision.reason or f"approval required by rule: {decision.rule_source}",
                ))
                raise ApprovalRequired(
                    policy="rule:require_approval",
                    detail=decision.reason or f"DSL rule requires approval: {decision.rule_source}",
                    run_id=self._run_id, turn=self._turn,
                    tool_name=tool_name, tool_input=tool_input,
                )
            handler_ctx = {"run_id": self._run_id, "turn": self._turn,
                           "agent": self._spec.agent.name,
                           "rule_source": decision.rule_source,
                           "rule_reason": decision.reason}
            approved = self._approval_handler(tool_name, tool_input, handler_ctx)
            event_type = "tool_approved" if approved else "tool_denied"
            self._audit.write(AuditEvent.now(
                run_id=self._run_id, agent=self._spec.agent.name,
                turn=self._turn, event_type=event_type,
                allowed=approved, policy="rule:require_approval",
                tool_name=tool_name, tool_input=tool_input,
                detail=decision.reason or f"rule: {decision.rule_source}",
            ))
            if approved:
                # Don't bump the tool-call counter here — the caller's
                # "Tool call allowed" path does the single canonical record.
                return True
            raise ApprovalRequired(
                policy="rule:require_approval",
                detail=decision.reason or f"Approval denied for rule: {decision.rule_source}",
                run_id=self._run_id, turn=self._turn,
                tool_name=tool_name, tool_input=tool_input,
            )

        return False

    def record_usage(
        self,
        *,
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: Optional[float] = None,
        tool_name: Optional[str] = None,
    ) -> EnforcementResult:
        """Record token + cost consumption after an LLM call or tool invocation.

        Writes a `usage` audit event and raises BudgetExceeded if the newly
        recorded usage tips the run over a configured cap. Call this AFTER
        the model response arrives (or after a tool returns its cost).
        """
        model_name = model or self._spec.model.preferred
        sample = self._cost.record(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tool_name=tool_name,
            turn=self._turn,
        )

        self._audit.write(AuditEvent.now(
            run_id=self._run_id,
            agent=self._spec.agent.name,
            turn=self._turn,
            event_type="usage",
            allowed=True,
            tool_name=tool_name,
            detail=(
                f"Usage: {input_tokens} in + {output_tokens} out tokens, "
                f"${sample.cost_usd:.6f} ({model_name})"
            ),
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=sample.cost_usd,
            run_cost_usd=self._cost.snapshot.total_cost_usd,
        ))

        # After recording, re-check caps. No projection — we're already past.
        self._budget_check()

        return EnforcementResult(
            allowed=True,
            turn=self._turn,
            run_id=self._run_id,
            event_type="usage",
            detail=f"run_cost_usd={self._cost.snapshot.total_cost_usd:.6f}",
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
        # Fail-closed budget check before we honor the call (no spend to record yet;
        # we only care about the tool-call count cap here — cost/token caps are
        # enforced post-hoc via record_usage).
        self._budget_check(projecting_tool_call=True)

        # DSL rules next. A deny raises directly; require_approval promotes
        # this tool into the approval pipeline for the current call; allow
        # short-circuits past the static require_approval list.
        dsl_allow_override = self._apply_dsl_rules(tool_name, tool_input)

        require_approval = (
            self._spec.policies.require_approval
            if self._spec.policies
            else []
        )
        if dsl_allow_override:
            # Treat this tool as explicitly allowed; skip static gating.
            require_approval = []

        if _matches_approval_pattern(tool_name, require_approval):
            if self._approval_handler is not None:
                context = {
                    "run_id": self._run_id,
                    "turn": self._turn,
                    "agent": self._spec.agent.name,
                }
                approved = self._approval_handler(tool_name, tool_input, context)
                if approved:
                    self._cost.record_tool_call(tool_name, turn=self._turn)
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
        self._cost.record_tool_call(tool_name, turn=self._turn)
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
        self._budget_check(projecting_tool_call=True)

        # DSL rules. async path uses the same sync evaluator for now; we
        # don't yet support async DSL builtins or async approval from rules.
        dsl_allow_override = self._apply_dsl_rules(tool_name, tool_input)

        require_approval = (
            self._spec.policies.require_approval
            if self._spec.policies
            else []
        )
        if dsl_allow_override:
            require_approval = []

        if not _matches_approval_pattern(tool_name, require_approval):
            self._cost.record_tool_call(tool_name, turn=self._turn)
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
                self._cost.record_tool_call(tool_name, turn=self._turn)
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
