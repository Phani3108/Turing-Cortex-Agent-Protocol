"""Deterministic replay — does today's policy still hold against yesterday's events?

Given an audit log + the current spec, re-run every recorded tool call
through a fresh `PolicyEnforcer` and compare the current decision to
the historical one. Differences fall into three categories:

  - `newly_blocked` : was allowed historically, would be blocked now
  - `newly_allowed` : was blocked historically, would pass now
  - `unchanged`     : same verdict

Useful for:
  - Regression gates: "does tightening max_cost_usd break existing flows?"
  - Policy migration: "will this forbidden_actions pattern catch past
    incidents?"
  - Drift confirmation: combine with drift-check to see *which* events
    drove the compliance score change.

Replay is deterministic, offline, and doesn't make any model or tool
calls — only policy evaluation runs. Approval handlers are short-
circuited to "auto-deny" so gated tools fail closed in the replay view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import AgentSpec
from .audit import AuditEvent, AuditLog
from .cost import CostTracker, ModelPricing
from .enforcer import PolicyEnforcer
from .exceptions import (
    ApprovalRequired,
    BudgetExceeded,
    ForbiddenActionDetected,
    MaxTurnsExceeded,
)


@dataclass
class ReplayDecision:
    run_id: str
    turn: int
    tool_name: Optional[str]
    event_type: str
    historical_allowed: bool
    replay_allowed: bool
    replay_policy: Optional[str] = None   # which policy caught it now
    replay_detail: str = ""

    @property
    def changed(self) -> bool:
        return self.historical_allowed != self.replay_allowed

    @property
    def category(self) -> str:
        if self.historical_allowed and not self.replay_allowed:
            return "newly_blocked"
        if not self.historical_allowed and self.replay_allowed:
            return "newly_allowed"
        return "unchanged"


@dataclass
class ReplayReport:
    total_tool_events: int
    newly_blocked: list[ReplayDecision] = field(default_factory=list)
    newly_allowed: list[ReplayDecision] = field(default_factory=list)
    unchanged: int = 0

    @property
    def regression_count(self) -> int:
        return len(self.newly_blocked) + len(self.newly_allowed)

    def to_dict(self) -> dict:
        return {
            "total_tool_events": self.total_tool_events,
            "newly_blocked": [_decision_dict(d) for d in self.newly_blocked],
            "newly_allowed": [_decision_dict(d) for d in self.newly_allowed],
            "unchanged": self.unchanged,
            "regression_count": self.regression_count,
        }


def _decision_dict(d: ReplayDecision) -> dict:
    return {
        "run_id": d.run_id, "turn": d.turn, "tool_name": d.tool_name,
        "event_type": d.event_type,
        "historical_allowed": d.historical_allowed,
        "replay_allowed": d.replay_allowed,
        "replay_policy": d.replay_policy,
        "replay_detail": d.replay_detail,
    }


def _deny_all(tool_name, tool_input, context):
    """Approval handler used during replay — never approves.

    Rationale: the replay must be deterministic and offline. Treating
    every gated call as "would require approval" produces the correct
    fail-closed verdict for comparison with the historical `tool_blocked`
    event. Historical `tool_approved` events also end up in the
    "would-require-approval-today" bucket, which is the right answer
    for the regression question: "does today's policy still gate this?"
    """
    return False


def replay(
    spec: AgentSpec,
    audit_log: AuditLog,
    *,
    pricing: Optional[ModelPricing] = None,
) -> ReplayReport:
    """Replay an audit log against a fresh enforcer built from `spec`.

    Only events with a `tool_name` participate — replay is about tool
    gating. Cost / token / turn-count state is reconstructed from the
    log where possible so budget caps fire at the same point they would
    have in a live run.
    """
    events = audit_log.events()
    tool_events = [
        e for e in events
        if e.tool_name and e.event_type in {
            "tool_call", "tool_blocked", "tool_approved", "tool_denied",
        }
    ]

    report = ReplayReport(total_tool_events=len(tool_events))

    # One enforcer per run_id so turn/cost counters stay coherent.
    by_run: dict[str, list[AuditEvent]] = {}
    for e in events:
        by_run.setdefault(e.run_id, []).append(e)

    for run_id, run_events in by_run.items():
        enforcer = PolicyEnforcer(
            spec,
            approval_handler=_deny_all,
            pricing=pricing,
        )
        _replay_run(enforcer, run_events, report)

    report.unchanged = report.total_tool_events - report.regression_count
    return report


def _replay_run(enforcer: PolicyEnforcer, events: list[AuditEvent],
                report: ReplayReport) -> None:
    # Ensure each tool check runs "on a turn" so turn-count caps fire
    # at the same place they would have live.
    seen_turns: set[int] = set()
    turn_cap_hit = False
    turn_cap_detail = ""
    turn_cap_policy = "max_turns"

    for e in events:
        # Advance the enforcer's turn counter at turn boundaries.
        if e.turn not in seen_turns:
            if not turn_cap_hit:
                try:
                    enforcer.increment_turn()
                except MaxTurnsExceeded as v:
                    # Live, the agent would have halted here. Record
                    # that fact so subsequent tool calls are marked
                    # newly_blocked against the current policy.
                    turn_cap_hit = True
                    turn_cap_detail = v.detail
            seen_turns.add(e.turn)

        # Feed usage events into the cost tracker so cost/token caps
        # reflect real accumulated spend.
        if e.event_type == "usage":
            try:
                enforcer.record_usage(
                    model=e.model,
                    input_tokens=e.input_tokens or 0,
                    output_tokens=e.output_tokens or 0,
                    cost_usd=e.cost_usd,
                )
            except BudgetExceeded:
                pass
            continue

        if not e.tool_name or e.event_type not in {
            "tool_call", "tool_blocked", "tool_approved", "tool_denied",
        }:
            continue

        if turn_cap_hit:
            decision = ReplayDecision(
                run_id=e.run_id, turn=e.turn, tool_name=e.tool_name,
                event_type=e.event_type,
                historical_allowed=bool(e.allowed),
                replay_allowed=False,
                replay_policy=turn_cap_policy,
                replay_detail=turn_cap_detail or "max_turns exceeded",
            )
        else:
            decision = _decide(enforcer, e)
        if decision.category == "newly_blocked":
            report.newly_blocked.append(decision)
        elif decision.category == "newly_allowed":
            report.newly_allowed.append(decision)


def _decide(enforcer: PolicyEnforcer, event: AuditEvent) -> ReplayDecision:
    try:
        enforcer.check_tool_call(event.tool_name, event.tool_input or {})
        replay_allowed = True
        policy: Optional[str] = None
        detail = "allowed"
    except (ApprovalRequired, BudgetExceeded, ForbiddenActionDetected,
             MaxTurnsExceeded) as v:
        replay_allowed = False
        policy = v.policy
        detail = v.detail

    return ReplayDecision(
        run_id=event.run_id,
        turn=event.turn,
        tool_name=event.tool_name,
        event_type=event.event_type,
        historical_allowed=bool(event.allowed),
        replay_allowed=replay_allowed,
        replay_policy=policy,
        replay_detail=detail,
    )
