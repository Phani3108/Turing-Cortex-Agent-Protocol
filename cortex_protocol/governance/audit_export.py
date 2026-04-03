"""Audit event export protocol for SIEM/observability integration."""
from __future__ import annotations
from pathlib import Path
from typing import Protocol, runtime_checkable
from .audit import AuditEvent


@runtime_checkable
class AuditExporter(Protocol):
    def export_event(self, event: AuditEvent) -> None: ...
    def flush(self) -> None: ...


class StdoutExporter:
    """Prints audit events to stdout."""
    def export_event(self, event: AuditEvent) -> None:
        print(event.to_json())
    def flush(self) -> None:
        pass


class JsonlFileExporter:
    """Exports audit events to a separate JSONL file."""
    def __init__(self, path: Path):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def export_event(self, event: AuditEvent) -> None:
        with open(self._path, "a") as f:
            f.write(event.to_json() + "\n")

    def flush(self) -> None:
        pass


class CallbackExporter:
    """Calls a function for each event. Use for custom integrations."""
    def __init__(self, callback):
        self._callback = callback

    def export_event(self, event: AuditEvent) -> None:
        self._callback(event)

    def flush(self) -> None:
        pass
