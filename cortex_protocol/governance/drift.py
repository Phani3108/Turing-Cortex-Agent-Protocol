"""Drift detection: compare agent behavior (audit log) against its spec."""
from __future__ import annotations
from dataclasses import dataclass, field
from ..models import AgentSpec
from .audit import AuditLog


@dataclass
class DriftReport:
    agent_name: str
    spec_version: str
    total_runs: int
    total_events: int
    undeclared_tools: list[str]
    max_turns_exceeded: int
    forbidden_action_triggers: int
    approval_bypasses: int
    compliance_score: float  # 0.0 to 1.0
    details: list[str]

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "spec_version": self.spec_version,
            "total_runs": self.total_runs,
            "total_events": self.total_events,
            "undeclared_tools": self.undeclared_tools,
            "max_turns_exceeded": self.max_turns_exceeded,
            "forbidden_action_triggers": self.forbidden_action_triggers,
            "approval_bypasses": self.approval_bypasses,
            "compliance_score": self.compliance_score,
            "details": self.details,
        }


def detect_drift(spec: AgentSpec, audit_log: AuditLog) -> DriftReport:
    """Compare actual agent behavior against its spec."""
    events = audit_log.events()
    if not events:
        return DriftReport(
            agent_name=spec.agent.name,
            spec_version=spec.version,
            total_runs=0, total_events=0,
            undeclared_tools=[], max_turns_exceeded=0,
            forbidden_action_triggers=0, approval_bypasses=0,
            compliance_score=1.0, details=["No audit events found."],
        )

    spec_tool_names = {t.name for t in spec.tools}
    gated_tools = set(spec.policies.require_approval)
    max_turns = spec.policies.max_turns

    # Unique runs
    run_ids = {e.run_id for e in events}

    # Undeclared tools
    audit_tools = {e.tool_name for e in events if e.tool_name}
    undeclared = sorted(audit_tools - spec_tool_names - {None, ""})

    # Max turns exceeded: count runs where any event has turn > max_turns
    max_turns_exceeded = 0
    if max_turns:
        for run_id in run_ids:
            run_events = [e for e in events if e.run_id == run_id]
            max_turn_in_run = max((e.turn for e in run_events), default=0)
            if max_turn_in_run > max_turns:
                max_turns_exceeded += 1

    # Forbidden action triggers
    forbidden_count = sum(1 for e in events if e.event_type == "forbidden_action")

    # Approval bypasses: tool_call events for gated tools that were allowed=True
    approval_bypasses = sum(
        1 for e in events
        if e.event_type == "tool_call" and e.tool_name in gated_tools and e.allowed
    )

    # Compliance score
    violation_events = sum(1 for e in events if not e.allowed)
    total = len(events)
    score = 1.0 - (violation_events / total) if total > 0 else 1.0
    score = max(0.0, min(1.0, score))

    # Build details
    details = []
    if undeclared:
        details.append(f"Undeclared tools used: {', '.join(undeclared)}")
    if max_turns_exceeded:
        details.append(f"Max turns ({max_turns}) exceeded in {max_turns_exceeded}/{len(run_ids)} runs")
    if forbidden_count:
        details.append(f"Forbidden actions triggered {forbidden_count} times")
    if approval_bypasses:
        details.append(f"Gated tools called without approval {approval_bypasses} times")
    if not details:
        details.append("No drift detected. Agent behavior matches spec.")

    return DriftReport(
        agent_name=spec.agent.name,
        spec_version=spec.version,
        total_runs=len(run_ids),
        total_events=total,
        undeclared_tools=undeclared,
        max_turns_exceeded=max_turns_exceeded,
        forbidden_action_triggers=forbidden_count,
        approval_bypasses=approval_bypasses,
        compliance_score=round(score, 3),
        details=details,
    )
