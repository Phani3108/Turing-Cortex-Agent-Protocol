"""Fleet-level audit aggregation across multiple agents."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import AgentSpec
from .audit import AuditLog
from .drift import detect_drift, DriftReport


@dataclass
class AgentSummary:
    name: str
    total_runs: int
    total_events: int
    violations: int
    compliance_score: float
    top_policies: list[str]
    drift: Optional[DriftReport] = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "total_runs": self.total_runs,
            "total_events": self.total_events,
            "violations": self.violations,
            "compliance_score": self.compliance_score,
            "top_policies": self.top_policies,
        }
        if self.drift:
            d["drift"] = self.drift.to_dict()
        return d


@dataclass
class FleetSummary:
    total_agents: int
    total_runs: int
    total_events: int
    total_violations: int
    fleet_compliance_score: float
    agents: list[AgentSummary]
    top_violators: list[AgentSummary]
    policies_triggered: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "total_agents": self.total_agents,
            "total_runs": self.total_runs,
            "total_events": self.total_events,
            "total_violations": self.total_violations,
            "fleet_compliance_score": self.fleet_compliance_score,
            "agents": [a.to_dict() for a in self.agents],
            "top_violators": [a.to_dict() for a in self.top_violators],
            "policies_triggered": self.policies_triggered,
        }


def aggregate_fleet_logs(log_paths: list[Path]) -> FleetSummary:
    """Read multiple JSONL audit logs and aggregate."""
    agent_data: dict[str, dict] = {}

    for path in log_paths:
        log = AuditLog.from_file(path)
        events = log.events()
        if not events:
            continue

        agent_name = events[0].agent if events else path.stem
        if agent_name not in agent_data:
            agent_data[agent_name] = {"events": [], "log": log}
        agent_data[agent_name]["events"].extend(events)

    agents = []
    total_runs = 0
    total_events = 0
    total_violations = 0
    all_policies: dict[str, int] = {}

    for name, data in agent_data.items():
        evts = data["events"]
        runs = len({e.run_id for e in evts})
        violations = sum(1 for e in evts if not e.allowed)
        score = 1.0 - (violations / len(evts)) if evts else 1.0

        policies = {}
        for e in evts:
            if e.policy:
                policies[e.policy] = policies.get(e.policy, 0) + 1
                all_policies[e.policy] = all_policies.get(e.policy, 0) + 1

        top = sorted(policies.keys(), key=lambda p: policies[p], reverse=True)[:3]

        agents.append(AgentSummary(
            name=name, total_runs=runs, total_events=len(evts),
            violations=violations, compliance_score=round(score, 3), top_policies=top,
        ))

        total_runs += runs
        total_events += len(evts)
        total_violations += violations

    fleet_score = 1.0 - (total_violations / total_events) if total_events else 1.0
    top_violators = sorted(agents, key=lambda a: a.violations, reverse=True)[:5]

    return FleetSummary(
        total_agents=len(agents),
        total_runs=total_runs,
        total_events=total_events,
        total_violations=total_violations,
        fleet_compliance_score=round(fleet_score, 3),
        agents=agents,
        top_violators=top_violators,
        policies_triggered=all_policies,
    )


def generate_fleet_report(
    log_paths: list[Path],
    standard: str = "general",
    specs: dict[str, AgentSpec] | None = None,
) -> str:
    """Generate fleet-wide compliance report as Markdown."""
    summary = aggregate_fleet_logs(log_paths)

    lines = []
    lines.append("# Fleet Compliance Report")
    lines.append("")
    lines.append(f"**Standard:** {standard.upper()}")
    lines.append(f"**Agents:** {summary.total_agents}")
    lines.append(f"**Total Runs:** {summary.total_runs}")
    lines.append(f"**Total Events:** {summary.total_events}")
    lines.append(f"**Fleet Compliance Score:** {summary.fleet_compliance_score:.1%}")
    lines.append("")

    # Per-agent table
    lines.append("## Agent Breakdown")
    lines.append("")
    lines.append("| Agent | Runs | Events | Violations | Score |")
    lines.append("|-------|------|--------|------------|-------|")
    for agent in summary.agents:
        lines.append(f"| {agent.name} | {agent.total_runs} | {agent.total_events} | {agent.violations} | {agent.compliance_score:.1%} |")
    lines.append("")

    # Top violators
    if summary.top_violators and summary.total_violations > 0:
        lines.append("## Top Violators")
        lines.append("")
        for agent in summary.top_violators:
            if agent.violations > 0:
                lines.append(f"- **{agent.name}**: {agent.violations} violations ({agent.compliance_score:.1%} compliance)")
        lines.append("")

    # Policies triggered
    if summary.policies_triggered:
        lines.append("## Policies Triggered (Fleet-wide)")
        lines.append("")
        for policy, count in sorted(summary.policies_triggered.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {policy}: {count} times")
        lines.append("")

    # Drift per agent (if specs provided)
    if specs:
        lines.append("## Drift Analysis")
        lines.append("")
        for agent in summary.agents:
            if agent.name in specs:
                agent_events = []
                for path in log_paths:
                    log = AuditLog.from_file(path)
                    agent_events.extend([e for e in log.events() if e.agent == agent.name])

                temp_log = AuditLog()
                for e in agent_events:
                    temp_log.write(e)

                drift = detect_drift(specs[agent.name], temp_log)
                agent.drift = drift
                lines.append(f"### {agent.name}")
                for detail in drift.details:
                    lines.append(f"- {detail}")
                lines.append("")

    # Standard-specific sections
    if standard == "soc2":
        lines.append("## SOC2 Control Mapping")
        lines.append("")
        lines.append("- **CC6.1 (Logical Access):** All tool calls checked against require_approval policies.")
        lines.append(f"  Approval events: {summary.policies_triggered.get('require_approval', 0)}")
        lines.append("- **CC6.6 (Threat & Vulnerability Management):** Forbidden actions monitored.")
        lines.append(f"  Forbidden action events: {summary.policies_triggered.get('forbidden_actions', 0)}")
        lines.append("")

    if standard == "gdpr":
        lines.append("## GDPR Article Mapping")
        lines.append("")
        lines.append("- **Art. 25 (Data Protection by Design):** Agent policies enforce data access boundaries.")
        lines.append(f"  Total policy enforcement events: {summary.total_events}")
        lines.append("- **Art. 30 (Records of Processing):** All agent actions logged to JSONL audit trail.")
        lines.append(f"  Total audit records: {summary.total_events}")
        lines.append("")

    # JSON summary block
    lines.append("## Machine-Readable Summary")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(summary.to_dict(), indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
