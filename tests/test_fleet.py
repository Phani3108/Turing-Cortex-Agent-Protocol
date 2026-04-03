"""Tests for fleet-level audit aggregation."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cortex_protocol.governance.audit import AuditLog, AuditEvent
from cortex_protocol.governance.fleet import (
    aggregate_fleet_logs,
    generate_fleet_report,
    FleetSummary,
)


def _write_log(path: Path, events: list[AuditEvent]):
    log = AuditLog(path=path)
    for e in events:
        log.write(e)


def _event(agent="agent-a", run_id="r1", turn=1, event_type="tool_call",
           allowed=True, tool_name=None, policy=None):
    return AuditEvent.now(
        run_id=run_id, agent=agent, turn=turn,
        event_type=event_type, allowed=allowed,
        tool_name=tool_name, policy=policy,
    )


def test_single_log_aggregation():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "agent_a.jsonl"
        _write_log(log_path, [
            _event(agent="agent-a", run_id="r1"),
            _event(agent="agent-a", run_id="r2"),
        ])
        summary = aggregate_fleet_logs([log_path])
        assert summary.total_agents == 1
        assert summary.total_events == 2
        assert summary.total_runs == 2


def test_multiple_logs_different_agents():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_a = Path(tmpdir) / "a.jsonl"
        log_b = Path(tmpdir) / "b.jsonl"
        _write_log(log_a, [_event(agent="agent-a")])
        _write_log(log_b, [_event(agent="agent-b")])
        summary = aggregate_fleet_logs([log_a, log_b])
        assert summary.total_agents == 2


def test_top_violators_sorted():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_a = Path(tmpdir) / "a.jsonl"
        log_b = Path(tmpdir) / "b.jsonl"
        _write_log(log_a, [
            _event(agent="agent-a", allowed=False),
            _event(agent="agent-a", allowed=False),
            _event(agent="agent-a", allowed=False),
        ])
        _write_log(log_b, [
            _event(agent="agent-b", allowed=False),
        ])
        summary = aggregate_fleet_logs([log_a, log_b])
        assert summary.top_violators[0].name == "agent-a"
        assert summary.top_violators[0].violations == 3


def test_fleet_compliance_score():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.jsonl"
        _write_log(log_path, [
            _event(allowed=True),
            _event(allowed=True),
            _event(allowed=False),
            _event(allowed=False),
        ])
        summary = aggregate_fleet_logs([log_path])
        assert summary.fleet_compliance_score == 0.5


def test_fleet_report_has_markdown_headers():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.jsonl"
        _write_log(log_path, [_event()])
        report = generate_fleet_report([log_path])
        assert "# Fleet Compliance Report" in report
        assert "## Agent Breakdown" in report


def test_soc2_report_has_cc6_references():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.jsonl"
        _write_log(log_path, [_event()])
        report = generate_fleet_report([log_path], standard="soc2")
        assert "CC6.1" in report
        assert "CC6.6" in report


def test_gdpr_report_has_article_references():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.jsonl"
        _write_log(log_path, [_event()])
        report = generate_fleet_report([log_path], standard="gdpr")
        assert "Art. 25" in report
        assert "Art. 30" in report


def test_to_dict_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "log.jsonl"
        _write_log(log_path, [_event()])
        summary = aggregate_fleet_logs([log_path])
        d = summary.to_dict()
        assert "total_agents" in d
        assert "fleet_compliance_score" in d
        assert "agents" in d
        assert "top_violators" in d
        assert "policies_triggered" in d
