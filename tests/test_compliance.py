"""Tests for compliance report generation."""

import json
import tempfile
from pathlib import Path

from click.testing import CliRunner

from cortex_protocol.governance.audit import AuditLog, AuditEvent
from cortex_protocol.governance.compliance import generate_compliance_report, export_compliance_json
from cortex_protocol.cli import main


def _make_audit_log() -> AuditLog:
    log = AuditLog()
    log.write(AuditEvent.now(
        run_id="run-1", agent="test-agent", turn=1,
        event_type="tool_call", allowed=True,
        tool_name="search", policy=None, detail="allowed",
    ))
    log.write(AuditEvent.now(
        run_id="run-1", agent="test-agent", turn=2,
        event_type="tool_blocked", allowed=False,
        tool_name="delete-user", policy="forbidden_actions",
        detail="Action is forbidden",
    ))
    log.write(AuditEvent.now(
        run_id="run-2", agent="test-agent", turn=1,
        event_type="tool_call", allowed=True,
        tool_name="write", policy=None, detail="allowed",
    ))
    return log


def test_report_contains_agent_name():
    log = _make_audit_log()
    report = generate_compliance_report(log)
    assert "test-agent" in report


def test_report_contains_summary_table():
    log = _make_audit_log()
    report = generate_compliance_report(log)
    assert "Total Events" in report
    assert "Policy Violations" in report


def test_report_contains_timeline():
    log = _make_audit_log()
    report = generate_compliance_report(log)
    assert "Timeline" in report
    assert "BLOCKED" in report


def test_soc2_report_contains_cc6_references():
    log = _make_audit_log()
    report = generate_compliance_report(log, standard="soc2")
    assert "CC6.1" in report
    assert "CC6.6" in report


def test_gdpr_report_contains_art25():
    log = _make_audit_log()
    report = generate_compliance_report(log, standard="gdpr")
    assert "Article 25" in report or "Art. 25" in report


def test_report_contains_json_block():
    log = _make_audit_log()
    report = generate_compliance_report(log)
    assert "```json" in report


def test_report_agent_version_included():
    log = _make_audit_log()
    report = generate_compliance_report(log, agent_version="2.1.0")
    assert "2.1.0" in report


def test_export_compliance_json_structure():
    log = _make_audit_log()
    result = export_compliance_json(log)
    assert "agent" in result
    assert "total_events" in result
    assert "violations" in result
    assert "allowed" in result
    assert "runs" in result
    assert "tools_called" in result
    assert "policies_triggered" in result
    assert "blocked_events" in result
    assert isinstance(result["blocked_events"], list)


def test_export_compliance_json_blocked_events():
    log = _make_audit_log()
    result = export_compliance_json(log)
    assert len(result["blocked_events"]) == 1
    assert result["blocked_events"][0]["tool_name"] == "delete-user"


def test_empty_log_produces_valid_report():
    log = AuditLog()
    report = generate_compliance_report(log)
    assert "Compliance Report" in report
    assert "```json" in report


def test_cli_compliance_report_stdout():
    runner = CliRunner()
    with runner.isolated_filesystem():
        log = _make_audit_log()
        log_content = log.to_jsonl()
        Path("audit.jsonl").write_text(log_content)

        result = runner.invoke(main, ["compliance-report", "audit.jsonl"])
        assert result.exit_code == 0, result.output
        assert "Compliance Report" in result.output


def test_cli_compliance_report_soc2():
    runner = CliRunner()
    with runner.isolated_filesystem():
        log = _make_audit_log()
        Path("audit.jsonl").write_text(log.to_jsonl())

        result = runner.invoke(main, ["compliance-report", "audit.jsonl", "--standard", "soc2"])
        assert result.exit_code == 0, result.output
        assert "CC6" in result.output


def test_cli_compliance_report_output_file():
    runner = CliRunner()
    with runner.isolated_filesystem():
        log = _make_audit_log()
        Path("audit.jsonl").write_text(log.to_jsonl())

        result = runner.invoke(main, ["compliance-report", "audit.jsonl", "--output", "report.md"])
        assert result.exit_code == 0, result.output
        assert Path("report.md").exists()
        assert "Compliance Report" in Path("report.md").read_text()
