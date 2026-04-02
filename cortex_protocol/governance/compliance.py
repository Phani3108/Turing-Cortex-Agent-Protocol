"""Compliance report generation from audit logs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .audit import AuditLog, AuditEvent


def generate_compliance_report(
    audit_log: AuditLog,
    standard: str = "general",
    agent_version: str = "",
) -> str:
    """Generate a Markdown compliance report from an audit log.

    standard: "soc2" | "gdpr" | "general"
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


def export_compliance_json(audit_log: AuditLog) -> dict:
    """Export a SIEM-compatible JSON summary from an audit log."""
    summary = audit_log.summary()
    events = audit_log.events()
    agent_name = events[0].agent if events else "unknown"

    return {
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
