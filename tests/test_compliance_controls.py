"""Tests for structured compliance control evaluators."""
from __future__ import annotations

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, PolicySpec, ModelConfig, ToolSpec, ToolParameter,
)
from cortex_protocol.governance.audit import AuditLog, AuditEvent
from cortex_protocol.governance.compliance import (
    evaluate_soc2, evaluate_hipaa, evaluate_pci_dss,
    ControlStatus, ControlResult,
    generate_compliance_report, export_compliance_json,
)


def _log_with_events(events_data):
    log = AuditLog()
    for e in events_data:
        log.write(AuditEvent.now(**e))
    return log


def _spec(**kwargs):
    policies = kwargs.pop("policies", None) or PolicySpec(
        require_approval=["send-email"],
        forbidden_actions=["share PII"],
    )
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name="test-agent", description="Test", instructions="Test instructions."),
        tools=[ToolSpec(name="search", description="s", parameters=ToolParameter())],
        policies=policies,
        model=ModelConfig(),
        **kwargs,
    )


def _basic_events():
    return [
        {"run_id": "r1", "agent": "test-agent", "turn": 1, "event_type": "tool_call", "allowed": True, "tool_name": "search"},
        {"run_id": "r1", "agent": "test-agent", "turn": 2, "event_type": "tool_blocked", "allowed": False, "tool_name": "delete", "policy": "require_approval"},
    ]


# ---------------------------------------------------------------------------
# SOC2
# ---------------------------------------------------------------------------

class TestEvaluateSOC2:
    def test_returns_6_controls(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log)
        assert len(results) == 6

    def test_correct_control_ids(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log)
        ids = [r.control_id for r in results]
        assert "CC6.1" in ids
        assert "CC6.2" in ids
        assert "CC6.3" in ids
        assert "CC7.1" in ids
        assert "CC7.2" in ids
        assert "CC8.1" in ids

    def test_cc6_1_pass_with_identity(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log)
        cc61 = [r for r in results if r.control_id == "CC6.1"][0]
        assert cc61.status == ControlStatus.PASS

    def test_cc7_2_partial_with_violations(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log)
        cc72 = [r for r in results if r.control_id == "CC7.2"][0]
        assert cc72.status == ControlStatus.PARTIAL

    def test_cc8_1_pass_with_spec(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log, spec=_spec())
        cc81 = [r for r in results if r.control_id == "CC8.1"][0]
        assert cc81.status == ControlStatus.PASS

    def test_cc8_1_na_without_spec(self):
        log = _log_with_events(_basic_events())
        results = evaluate_soc2(log, spec=None)
        cc81 = [r for r in results if r.control_id == "CC8.1"][0]
        assert cc81.status == ControlStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# HIPAA
# ---------------------------------------------------------------------------

class TestEvaluateHIPAA:
    def test_returns_5_controls(self):
        log = _log_with_events(_basic_events())
        results = evaluate_hipaa(log)
        assert len(results) == 5

    def test_audit_controls_pass_with_events(self):
        log = _log_with_events(_basic_events())
        results = evaluate_hipaa(log)
        audit_ctrl = [r for r in results if r.control_id == "164.312(b)"][0]
        assert audit_ctrl.status == ControlStatus.PASS

    def test_audit_controls_fail_empty(self):
        log = AuditLog()
        results = evaluate_hipaa(log)
        audit_ctrl = [r for r in results if r.control_id == "164.312(b)"][0]
        assert audit_ctrl.status == ControlStatus.FAIL


# ---------------------------------------------------------------------------
# PCI-DSS
# ---------------------------------------------------------------------------

class TestEvaluatePCIDSS:
    def test_returns_4_controls(self):
        log = _log_with_events(_basic_events())
        results = evaluate_pci_dss(log)
        assert len(results) == 4

    def test_pci_10_1_fail_no_events(self):
        log = AuditLog()
        results = evaluate_pci_dss(log)
        pci101 = [r for r in results if r.control_id == "PCI-10.1"][0]
        assert pci101.status == ControlStatus.FAIL

    def test_pci_10_1_pass_with_events(self):
        log = _log_with_events(_basic_events())
        results = evaluate_pci_dss(log)
        pci101 = [r for r in results if r.control_id == "PCI-10.1"][0]
        assert pci101.status == ControlStatus.PASS


# ---------------------------------------------------------------------------
# Report integration
# ---------------------------------------------------------------------------

def test_hipaa_report_contains_control_table():
    log = _log_with_events(_basic_events())
    report = generate_compliance_report(log, standard="hipaa")
    assert "HIPAA Control Evaluation" in report
    assert "164.312(b)" in report
    assert "| Control |" in report


def test_pci_report_contains_control_table():
    log = _log_with_events(_basic_events())
    report = generate_compliance_report(log, standard="pci-dss")
    assert "PCI-DSS Control Evaluation" in report
    assert "PCI-10.1" in report


def test_export_json_includes_control_results():
    log = _log_with_events(_basic_events())
    result = export_compliance_json(log, standard="soc2")
    assert "control_results" in result
    assert len(result["control_results"]) == 6
    assert result["control_results"][0]["control_id"] == "CC6.1"


def test_export_json_no_controls_for_general():
    log = _log_with_events(_basic_events())
    result = export_compliance_json(log, standard="general")
    assert "control_results" not in result
