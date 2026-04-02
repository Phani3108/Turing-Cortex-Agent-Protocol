"""Tests for the audit log module."""

import json
from pathlib import Path

import pytest

from cortex_protocol.governance.audit import AuditEvent, AuditLog


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------

class TestAuditEvent:
    def test_create_with_now(self):
        event = AuditEvent.now(
            run_id="abc123",
            agent="test-agent",
            turn=1,
            event_type="tool_call",
            allowed=True,
            detail="Test event",
        )
        assert event.run_id == "abc123"
        assert event.agent == "test-agent"
        assert event.timestamp  # not empty

    def test_to_dict_drops_none(self):
        event = AuditEvent.now(
            run_id="abc123",
            agent="test-agent",
            turn=1,
            event_type="response",
            allowed=True,
        )
        d = event.to_dict()
        assert "tool_name" not in d
        assert "tool_input" not in d

    def test_to_dict_keeps_values(self):
        event = AuditEvent.now(
            run_id="abc",
            agent="agent",
            turn=2,
            event_type="tool_blocked",
            allowed=False,
            tool_name="send-email",
            tool_input={"to": "user@example.com"},
            policy="require_approval",
        )
        d = event.to_dict()
        assert d["tool_name"] == "send-email"
        assert d["policy"] == "require_approval"
        assert d["allowed"] is False

    def test_to_json_is_valid_json(self):
        event = AuditEvent.now(
            run_id="abc", agent="a", turn=1,
            event_type="response", allowed=True,
        )
        parsed = json.loads(event.to_json())
        assert parsed["run_id"] == "abc"


# ---------------------------------------------------------------------------
# AuditLog — in-memory
# ---------------------------------------------------------------------------

class TestAuditLogInMemory:
    def test_empty_log(self):
        log = AuditLog()
        assert log.events() == []
        assert log.violations() == []

    def test_write_and_read(self):
        log = AuditLog()
        log.write(AuditEvent.now(
            run_id="r1", agent="a", turn=1,
            event_type="response", allowed=True,
        ))
        assert len(log.events()) == 1

    def test_violations_filter(self):
        log = AuditLog()
        log.write(AuditEvent.now(
            run_id="r1", agent="a", turn=1,
            event_type="tool_call", allowed=True,
        ))
        log.write(AuditEvent.now(
            run_id="r1", agent="a", turn=1,
            event_type="tool_blocked", allowed=False,
            policy="require_approval",
        ))
        assert len(log.events()) == 2
        assert len(log.violations()) == 1

    def test_events_for_run_filter(self):
        log = AuditLog()
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                  event_type="response", allowed=True))
        log.write(AuditEvent.now(run_id="r2", agent="a", turn=1,
                                  event_type="response", allowed=True))
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=2,
                                  event_type="response", allowed=True))
        assert len(log.events_for_run("r1")) == 2
        assert len(log.events_for_run("r2")) == 1
        assert len(log.events_for_run("r3")) == 0

    def test_to_jsonl(self):
        log = AuditLog()
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                  event_type="response", allowed=True))
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=2,
                                  event_type="tool_call", allowed=True))
        jsonl = log.to_jsonl()
        lines = [l for l in jsonl.strip().split("\n") if l]
        assert len(lines) == 2
        # Each line is valid JSON
        for line in lines:
            json.loads(line)

    def test_empty_jsonl(self):
        log = AuditLog()
        assert log.to_jsonl() == ""

    def test_summary_structure(self):
        log = AuditLog()
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                  event_type="tool_call", allowed=True,
                                  tool_name="search"))
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                  event_type="tool_blocked", allowed=False,
                                  tool_name="send-email",
                                  policy="require_approval"))
        summary = log.summary()
        assert summary["total_events"] == 2
        assert summary["violations"] == 1
        assert summary["allowed"] == 1
        assert summary["runs"] == 1
        assert "search" in summary["tools_called"]
        assert "send-email" in summary["tools_called"]
        assert "require_approval" in summary["policies_triggered"]


# ---------------------------------------------------------------------------
# AuditLog — file persistence
# ---------------------------------------------------------------------------

class TestAuditLogFile:
    def test_write_to_file(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        log = AuditLog(path=log_file)
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                  event_type="response", allowed=True))
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=2,
                                  event_type="tool_call", allowed=True))
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_read_from_existing_file(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        # Write first
        log1 = AuditLog(path=log_file)
        log1.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                   event_type="response", allowed=True))
        # Read back
        log2 = AuditLog(path=log_file)
        assert len(log2.events()) == 1

    def test_append_to_existing_file(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        log1 = AuditLog(path=log_file)
        log1.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                   event_type="response", allowed=True))

        log2 = AuditLog(path=log_file)
        log2.write(AuditEvent.now(run_id="r2", agent="a", turn=1,
                                   event_type="response", allowed=True))

        # log2 loaded r1's event + wrote r2's event
        assert len(log2.events()) == 2
        # File has both
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_from_file_readonly(self, tmp_path):
        log_file = tmp_path / "audit.jsonl"
        log1 = AuditLog(path=log_file)
        log1.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                   event_type="response", allowed=True))

        log2 = AuditLog.from_file(log_file)
        assert len(log2.events()) == 1
        # Writing to log2 should NOT touch the file
        log2.write(AuditEvent.now(run_id="r2", agent="a", turn=1,
                                   event_type="response", allowed=True))
        assert len(log2.events()) == 2
        # File still has only 1 event
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_from_jsonl_string(self):
        event = AuditEvent.now(run_id="r1", agent="a", turn=1,
                               event_type="response", allowed=True, detail="test")
        jsonl = event.to_json()
        log = AuditLog.from_jsonl(jsonl)
        assert len(log.events()) == 1
        assert log.events()[0].detail == "test"
