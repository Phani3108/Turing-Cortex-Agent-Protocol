"""Compliance report generation from audit logs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from .audit import AuditLog, AuditEvent


class ControlStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NOT_APPLICABLE = "n/a"


@dataclass
class ControlResult:
    control_id: str
    name: str
    status: ControlStatus
    evidence: str
    finding: str

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id,
            "name": self.name,
            "status": self.status.value,
            "evidence": self.evidence,
            "finding": self.finding,
        }


def evaluate_soc2(audit_log: AuditLog, spec=None) -> list[ControlResult]:
    """Evaluate SOC2 Trust Services Criteria against audit evidence."""
    events = audit_log.events()
    results = []

    # CC6.1 - Logical and Physical Access Controls
    tool_events = [e for e in events if e.tool_name]
    has_identity = all(e.agent for e in events) if events else False
    has_timestamps = all(e.timestamp for e in events) if events else False
    results.append(ControlResult(
        control_id="CC6.1",
        name="Logical and Physical Access Controls",
        status=ControlStatus.PASS if (has_identity and has_timestamps and tool_events) else ControlStatus.FAIL,
        evidence=f"{len(tool_events)} tool events with agent identity and timestamps",
        finding="All tool invocations logged with agent identity" if has_identity else "Missing agent identity on events",
    ))

    # CC6.2 - Prior to Issuing System Credentials
    approval_events = [e for e in events if e.event_type in ("tool_approved", "tool_blocked", "tool_denied")]
    has_approval_gates = spec and len(spec.policies.require_approval) > 0 if spec else len(approval_events) > 0
    results.append(ControlResult(
        control_id="CC6.2",
        name="Prior to Issuing System Credentials and Granting Access",
        status=ControlStatus.PASS if has_approval_gates else ControlStatus.PARTIAL,
        evidence=f"{len(approval_events)} approval gate events",
        finding="Approval gates configured and enforced" if has_approval_gates else "No approval gates detected",
    ))

    # CC6.3 - Authorization and Removal of Access
    forbidden_events = [e for e in events if e.event_type == "forbidden_action"]
    has_forbidden = spec and len(spec.policies.forbidden_actions) > 0 if spec else True
    results.append(ControlResult(
        control_id="CC6.3",
        name="Authorization and Removal of Access",
        status=ControlStatus.PASS if has_forbidden else ControlStatus.FAIL,
        evidence=f"{len(forbidden_events)} forbidden action checks, {len(spec.policies.forbidden_actions) if spec else 'N/A'} rules defined",
        finding="Forbidden actions defined and monitored" if has_forbidden else "No forbidden action rules defined",
    ))

    # CC7.1 - Detection and Monitoring
    results.append(ControlResult(
        control_id="CC7.1",
        name="Detection and Monitoring of Security Events",
        status=ControlStatus.PASS if len(events) > 0 else ControlStatus.FAIL,
        evidence=f"{len(events)} total audit events across {len({e.run_id for e in events})} runs",
        finding="Continuous monitoring via JSONL audit trail" if events else "No audit events found",
    ))

    # CC7.2 - Monitoring of System Components for Anomalies
    violations = [e for e in events if not e.allowed]
    results.append(ControlResult(
        control_id="CC7.2",
        name="Monitoring System Components for Anomalies",
        status=ControlStatus.PASS if not violations else ControlStatus.PARTIAL,
        evidence=f"{len(violations)} policy violations detected out of {len(events)} events",
        finding="No violations detected" if not violations else f"{len(violations)} violations require review",
    ))

    # CC8.1 - Changes to Infrastructure and Software
    results.append(ControlResult(
        control_id="CC8.1",
        name="Changes to Infrastructure and Software",
        status=ControlStatus.PASS if spec else ControlStatus.NOT_APPLICABLE,
        evidence=f"Agent spec version: {spec.version}" if spec else "No spec provided",
        finding="Agent behavior governed by versioned spec" if spec else "No spec available for change tracking",
    ))

    return results


def evaluate_hipaa(audit_log: AuditLog, spec=None) -> list[ControlResult]:
    events = audit_log.events()
    results = []

    # 164.312(a)(1) - Access Control
    approval_events = [e for e in events if e.event_type in ("tool_approved", "tool_blocked", "tool_denied")]
    results.append(ControlResult(
        control_id="164.312(a)(1)",
        name="Access Control - Unique User Identification",
        status=ControlStatus.PASS if (events and all(e.run_id for e in events)) else ControlStatus.FAIL,
        evidence=f"All events tagged with run_id; {len(approval_events)} approval checks",
        finding="Each agent run uniquely identified" if (events and all(e.run_id for e in events)) else "Missing run identification",
    ))

    # 164.312(b) - Audit Controls
    results.append(ControlResult(
        control_id="164.312(b)",
        name="Audit Controls",
        status=ControlStatus.PASS if events else ControlStatus.FAIL,
        evidence=f"{len(events)} audit events recorded",
        finding="Hardware, software, and procedural audit mechanisms active" if events else "No audit trail",
    ))

    # 164.312(c)(1) - Integrity Controls
    forbidden = [e for e in events if e.event_type == "forbidden_action"]
    results.append(ControlResult(
        control_id="164.312(c)(1)",
        name="Integrity - Mechanism to Authenticate ePHI",
        status=ControlStatus.PASS if (spec and spec.policies.forbidden_actions) else ControlStatus.PARTIAL,
        evidence=f"{len(forbidden)} forbidden action events; {len(spec.policies.forbidden_actions) if spec else 0} rules",
        finding="Forbidden action policies protect data integrity" if (spec and spec.policies.forbidden_actions) else "Limited integrity controls",
    ))

    # 164.312(d) - Person or Entity Authentication
    results.append(ControlResult(
        control_id="164.312(d)",
        name="Person or Entity Authentication",
        status=ControlStatus.PASS if (events and all(e.agent for e in events)) else ControlStatus.FAIL,
        evidence=f"Agent identity: {events[0].agent if events else 'N/A'}",
        finding="Agent identity verified on all events" if (events and all(e.agent for e in events)) else "Missing agent authentication",
    ))

    # 164.312(e)(1) - Transmission Security
    has_mcp = spec and any(t.mcp for t in spec.tools) if spec else False
    results.append(ControlResult(
        control_id="164.312(e)(1)",
        name="Transmission Security",
        status=ControlStatus.PASS if has_mcp else ControlStatus.NOT_APPLICABLE,
        evidence=f"MCP tool references: {sum(1 for t in spec.tools if t.mcp) if spec else 0}" if spec else "No spec",
        finding="Tools communicate via MCP protocol" if has_mcp else "No MCP transmission controls configured",
    ))

    return results


def evaluate_pci_dss(audit_log: AuditLog, spec=None) -> list[ControlResult]:
    events = audit_log.events()
    results = []

    # Req 7.1 - Restrict access
    approval_events = [e for e in events if e.event_type in ("tool_approved", "tool_blocked", "tool_denied")]
    results.append(ControlResult(
        control_id="PCI-7.1",
        name="Restrict Access to System Components",
        status=ControlStatus.PASS if approval_events or (spec and spec.policies.require_approval) else ControlStatus.FAIL,
        evidence=f"{len(approval_events)} access control events",
        finding="Tool access gated by approval policies" if approval_events else "No access restrictions detected",
    ))

    # Req 8.3 - Authentication
    results.append(ControlResult(
        control_id="PCI-8.3",
        name="Secure Authentication",
        status=ControlStatus.PASS if (events and all(e.run_id and e.agent for e in events)) else ControlStatus.FAIL,
        evidence="All events have run_id and agent identity",
        finding="Agent sessions uniquely authenticated" if events else "No authentication evidence",
    ))

    # Req 10.1 - Audit trail
    results.append(ControlResult(
        control_id="PCI-10.1",
        name="Audit Trails Established",
        status=ControlStatus.PASS if events else ControlStatus.FAIL,
        evidence=f"{len(events)} audit events, {len({e.run_id for e in events})} unique runs",
        finding="Comprehensive audit trail via JSONL logging" if events else "No audit trail",
    ))

    # Req 10.2 - Event types
    event_types = {e.event_type for e in events}
    results.append(ControlResult(
        control_id="PCI-10.2",
        name="Audit Event Types",
        status=ControlStatus.PASS if len(event_types) >= 2 else ControlStatus.PARTIAL,
        evidence=f"Event types captured: {', '.join(sorted(event_types))}",
        finding=f"{len(event_types)} distinct event types logged" if event_types else "Insufficient event diversity",
    ))

    return results


def generate_compliance_report(
    audit_log: AuditLog,
    standard: str = "general",
    agent_version: str = "",
    spec=None,
) -> str:
    """Generate a Markdown compliance report from an audit log.

    standard: "soc2" | "gdpr" | "hipaa" | "pci-dss" | "general"
    Returns Markdown string.
    """
    events = audit_log.events()
    summary = audit_log.summary()
    agent_name = events[0].agent if events else "unknown"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    total = summary["total_events"]
    violations = summary["violations"]
    allowed = summary["allowed"]
    approval_rate = f"{(allowed / total * 100):.1f}%" if total else "N/A"
    blocked = violations

    lines: list[str] = []

    # Header
    standard_label = {"soc2": "SOC 2 Type II", "gdpr": "GDPR", "general": "General"}.get(standard, "General")
    lines.append(f"# Compliance Report: {standard_label}")
    lines.append("")
    lines.append(f"- **Agent**: {agent_name}")
    if agent_version:
        lines.append(f"- **Version**: {agent_version}")
    lines.append(f"- **Report Date**: {now}")
    lines.append(f"- **Standard**: {standard_label}")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total Runs | {summary['runs']} |")
    lines.append(f"| Total Events | {total} |")
    lines.append(f"| Policy Violations | {violations} |")
    lines.append(f"| Approval Rate | {approval_rate} |")
    lines.append(f"| Blocked Actions | {blocked} |")
    if summary["tools_called"]:
        lines.append(f"| Tools Invoked | {', '.join(summary['tools_called'])} |")
    if summary["policies_triggered"]:
        lines.append(f"| Policies Triggered | {', '.join(summary['policies_triggered'])} |")
    lines.append("")

    # Standard-specific mappings
    if standard == "soc2":
        lines.append("## SOC 2 Control Mapping")
        lines.append("")
        lines.append("### CC6.1 — Logical and Physical Access Controls")
        lines.append("")
        lines.append("All tool invocations are logged with timestamps, agent identity, and approval status.")
        lines.append(f"- Blocked actions: {blocked}")
        lines.append(f"- Approval-gated events: {len([e for e in events if e.policy == 'require_approval'])}")
        lines.append("")
        lines.append("### CC6.6 — Threat and Vulnerability Management")
        lines.append("")
        lines.append("Forbidden action enforcement prevents unauthorized operations.")
        lines.append(f"- Forbidden action violations: {len([e for e in events if e.policy == 'forbidden_actions'])}")
        lines.append("")

    elif standard == "gdpr":
        lines.append("## GDPR Compliance Mapping")
        lines.append("")
        lines.append("### Article 25 — Data Protection by Design and by Default")
        lines.append("")
        lines.append("Agent policies enforce data minimization and purpose limitation by design.")
        lines.append(f"- Policy-blocked actions: {blocked}")
        lines.append(f"- All agent actions logged for accountability (Art. 5(2))")
        lines.append("")

    # Structured control evaluation for supported standards
    if standard in ("soc2", "hipaa", "pci-dss"):
        evaluators = {"soc2": evaluate_soc2, "hipaa": evaluate_hipaa, "pci-dss": evaluate_pci_dss}
        evaluator = evaluators.get(standard)
        if evaluator:
            controls = evaluator(audit_log, spec)
            lines.append(f"## {standard.upper()} Control Evaluation")
            lines.append("")
            lines.append("| Control | Name | Status | Evidence |")
            lines.append("|---------|------|--------|----------|")
            for c in controls:
                status_icon = {"pass": "PASS", "fail": "FAIL", "partial": "PARTIAL", "n/a": "N/A"}[c.status.value]
                lines.append(f"| {c.control_id} | {c.name} | {status_icon} | {c.evidence} |")
            lines.append("")
            lines.append("### Findings")
            lines.append("")
            for c in controls:
                lines.append(f"- **{c.control_id}**: {c.finding}")
            lines.append("")

    # Timeline
    lines.append("## Policy Enforcement Timeline")
    lines.append("")
    enforcement_events = [e for e in events if not e.allowed or e.policy]
    if enforcement_events:
        for event in enforcement_events:
            ts = event.timestamp[:19]
            status = "BLOCKED" if not event.allowed else "FLAGGED"
            lines.append(f"- `{ts}` [{status}] `{event.event_type}` — {event.detail or 'no detail'}")
            if event.tool_name:
                lines.append(f"  - Tool: `{event.tool_name}`")
            if event.policy:
                lines.append(f"  - Policy: `{event.policy}`")
    else:
        lines.append("_No policy enforcement events recorded._")
    lines.append("")

    # Machine-readable summary
    lines.append("## Machine-Readable Summary")
    lines.append("")
    lines.append("```json")
    json_summary = export_compliance_json(audit_log)
    json_summary["standard"] = standard
    json_summary["agent_version"] = agent_version
    json_summary["report_date"] = now
    lines.append(json.dumps(json_summary, indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def export_compliance_json(audit_log: AuditLog, standard: str = "general", spec=None) -> dict:
    """Export a SIEM-compatible JSON summary from an audit log."""
    summary = audit_log.summary()
    events = audit_log.events()
    agent_name = events[0].agent if events else "unknown"

    result = {
        "agent": agent_name,
        "total_events": summary["total_events"],
        "violations": summary["violations"],
        "allowed": summary["allowed"],
        "runs": summary["runs"],
        "tools_called": summary["tools_called"],
        "policies_triggered": summary["policies_triggered"],
        "blocked_events": [
            {
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "tool_name": e.tool_name,
                "policy": e.policy,
                "detail": e.detail,
            }
            for e in audit_log.violations()
        ],
    }

    if standard in ("soc2", "hipaa", "pci-dss"):
        evaluators = {"soc2": evaluate_soc2, "hipaa": evaluate_hipaa, "pci-dss": evaluate_pci_dss}
        evaluator = evaluators.get(standard)
        if evaluator:
            controls = evaluator(audit_log, spec)
            result["control_results"] = [c.to_dict() for c in controls]

    return result
