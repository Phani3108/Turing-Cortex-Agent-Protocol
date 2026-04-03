"""Tests for drift detection."""
from __future__ import annotations

import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.audit import AuditLog, AuditEvent
from cortex_protocol.governance.drift import detect_drift, DriftReport


def _spec():
    return AgentSpec.from_yaml_str("""
version: "0.1"
agent:
  name: test-agent
  description: Test
  instructions: Test
tools:
  - name: search
    description: Search
  - name: read-file
    description: Read file
policies:
  max_turns: 5
  require_approval:
    - send-email
  forbidden_actions:
    - share credentials
""")


def _event(run_id="run1", turn=1, event_type="tool_call", allowed=True,
           tool_name=None, policy=None, agent="test-agent"):
    return AuditEvent.now(
        run_id=run_id, agent=agent, turn=turn,
        event_type=event_type, allowed=allowed,
        tool_name=tool_name, policy=policy,
    )


def test_empty_audit_perfect_score():
    spec = _spec()
    audit = AuditLog()
    report = detect_drift(spec, audit)
    assert report.compliance_score == 1.0
    assert report.total_events == 0


def test_clean_audit_perfect_score():
    spec = _spec()
    audit = AuditLog()
    audit.write(_event(tool_name="search"))
    audit.write(_event(tool_name="read-file", turn=2))
    report = detect_drift(spec, audit)
    assert report.compliance_score == 1.0
    assert report.undeclared_tools == []


def test_undeclared_tool_detected():
    spec = _spec()
    audit = AuditLog()
    audit.write(_event(tool_name="search"))
    audit.write(_event(tool_name="hack-database"))
    report = detect_drift(spec, audit)
    assert "hack-database" in report.undeclared_tools


def test_max_turns_exceeded_counted():
    spec = _spec()
    audit = AuditLog()
    # Run with turn > 5 (max_turns)
    audit.write(_event(run_id="r1", turn=6, tool_name="search"))
    # Run within limits
    audit.write(_event(run_id="r2", turn=3, tool_name="search"))
    report = detect_drift(spec, audit)
    assert report.max_turns_exceeded == 1


def test_forbidden_action_counted():
    spec = _spec()
    audit = AuditLog()
    audit.write(_event(event_type="forbidden_action", allowed=False, policy="forbidden_actions"))
    audit.write(_event(event_type="forbidden_action", allowed=False, policy="forbidden_actions"))
    report = detect_drift(spec, audit)
    assert report.forbidden_action_triggers == 2


def test_approval_bypass_detected():
    spec = _spec()
    audit = AuditLog()
    # A gated tool (send-email) was called and allowed (bypass)
    audit.write(_event(event_type="tool_call", tool_name="send-email", allowed=True))
    report = detect_drift(spec, audit)
    assert report.approval_bypasses == 1


def test_compliance_score_calculation():
    spec = _spec()
    audit = AuditLog()
    audit.write(_event(allowed=True))
    audit.write(_event(allowed=True))
    audit.write(_event(allowed=False))
    audit.write(_event(allowed=False))
    report = detect_drift(spec, audit)
    assert report.compliance_score == 0.5


def test_to_dict_structure():
    spec = _spec()
    audit = AuditLog()
    audit.write(_event(tool_name="search"))
    report = detect_drift(spec, audit)
    d = report.to_dict()
    assert "agent_name" in d
    assert "spec_version" in d
    assert "compliance_score" in d
    assert "undeclared_tools" in d
    assert "details" in d
    assert isinstance(d["details"], list)
