"""Tests for RotatingAuditLog and audit exporters."""
from __future__ import annotations

import tempfile
from pathlib import Path

from cortex_protocol.governance.audit import AuditLog, AuditEvent, RotatingAuditLog
from cortex_protocol.governance.audit_export import (
    StdoutExporter, JsonlFileExporter, CallbackExporter, AuditExporter,
)


def _event(run_id="r1", agent="test", turn=1):
    return AuditEvent.now(
        run_id=run_id, agent=agent, turn=turn,
        event_type="tool_call", allowed=True,
    )


# ---------------------------------------------------------------------------
# RotatingAuditLog
# ---------------------------------------------------------------------------

class TestRotatingAuditLog:
    def test_rotates_when_size_exceeded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            log = RotatingAuditLog(path, max_bytes=100, backup_count=3)
            # Write enough events to exceed 100 bytes
            for i in range(20):
                log.write(_event(run_id=f"r{i}"))
            assert path.exists()
            assert Path(f"{path}.1").exists()

    def test_creates_numbered_backups(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            log = RotatingAuditLog(path, max_bytes=50, backup_count=5)
            for i in range(50):
                log.write(_event(run_id=f"run-{i}"))
            assert Path(f"{path}.1").exists()
            assert Path(f"{path}.2").exists()

    def test_backup_count_limits_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "audit.jsonl"
            log = RotatingAuditLog(path, max_bytes=50, backup_count=2)
            for i in range(100):
                log.write(_event(run_id=f"run-{i}"))
            # Should not have more than backup_count + 1 files
            assert not Path(f"{path}.4").exists()


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------

class TestStdoutExporter:
    def test_prints_event(self, capsys):
        exporter = StdoutExporter()
        event = _event()
        exporter.export_event(event)
        captured = capsys.readouterr()
        assert "r1" in captured.out
        assert "tool_call" in captured.out


class TestJsonlFileExporter:
    def test_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "export.jsonl"
            exporter = JsonlFileExporter(path)
            exporter.export_event(_event())
            exporter.export_event(_event(run_id="r2"))
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2


class TestCallbackExporter:
    def test_calls_callback(self):
        events_received = []
        exporter = CallbackExporter(lambda e: events_received.append(e))
        event = _event()
        exporter.export_event(event)
        assert len(events_received) == 1
        assert events_received[0] is event


class TestExporterProtocol:
    def test_stdout_is_exporter(self):
        assert isinstance(StdoutExporter(), AuditExporter)

    def test_jsonl_is_exporter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            assert isinstance(JsonlFileExporter(Path(tmpdir) / "x.jsonl"), AuditExporter)

    def test_callback_is_exporter(self):
        assert isinstance(CallbackExporter(lambda e: None), AuditExporter)


# ---------------------------------------------------------------------------
# AuditLog with exporters
# ---------------------------------------------------------------------------

class TestAuditLogExporters:
    def test_fans_out_to_all_exporters(self):
        events_a = []
        events_b = []
        exporter_a = CallbackExporter(lambda e: events_a.append(e))
        exporter_b = CallbackExporter(lambda e: events_b.append(e))
        log = AuditLog(exporters=[exporter_a, exporter_b])
        log.write(_event())
        log.write(_event(run_id="r2"))
        assert len(events_a) == 2
        assert len(events_b) == 2
