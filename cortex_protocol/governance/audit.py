"""Audit log for runtime policy enforcement.

Every enforcement decision — allowed or blocked — is recorded as an
AuditEvent. Events are stored in JSONL format (one JSON object per line),
which is greppable, streamable, and shippable to any SIEM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class AuditEvent:
    """A single enforcement decision."""

    timestamp: str                       # ISO 8601
    run_id: str                          # unique per enforcement session
    agent: str                           # agent name from spec
    turn: int                            # which turn in the run
    event_type: str                      # tool_call | tool_blocked | response |
                                         # forbidden_action | max_turns | escalation
    allowed: bool                        # was the action permitted?
    detail: str = ""                     # human-readable explanation
    policy: Optional[str] = None         # which policy field triggered
    tool_name: Optional[str] = None      # for tool events
    tool_input: Optional[dict] = None    # for tool events

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop None values for compact JSONL
        return {k: v for k, v in d.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def now(cls, **kwargs) -> AuditEvent:
        """Create an event with the current UTC timestamp."""
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            **kwargs,
        )


class AuditLog:
    """Collects AuditEvents in memory and optionally writes to a JSONL file.

    Usage:
        # In-memory only
        log = AuditLog()

        # Persist to file
        log = AuditLog(path=Path("./audit.jsonl"))

        # Write events
        log.write(AuditEvent.now(run_id="abc", agent="my-agent", ...))

        # Query
        log.events()            # all events
        log.violations()        # only blocked events
        log.summary()           # aggregate stats
    """

    def __init__(self, path: Optional[Path] = None, exporters: list | None = None):
        self._path = path
        self._events: list[AuditEvent] = []
        self._exporters = exporters or []

        # If the file exists, load existing events
        if path and path.exists():
            self._load_existing()

    def _load_existing(self):
        """Load events from an existing JSONL file."""
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    self._events.append(AuditEvent(**data))

    def write(self, event: AuditEvent) -> None:
        """Record an audit event."""
        self._events.append(event)
        if self._path:
            with open(self._path, "a") as f:
                f.write(event.to_json() + "\n")
        for exporter in self._exporters:
            exporter.export_event(event)

    def events(self) -> list[AuditEvent]:
        """Return all recorded events."""
        return list(self._events)

    def violations(self) -> list[AuditEvent]:
        """Return only events where the action was blocked."""
        return [e for e in self._events if not e.allowed]

    def events_for_run(self, run_id: str) -> list[AuditEvent]:
        """Filter events for a specific run."""
        return [e for e in self._events if e.run_id == run_id]

    def to_jsonl(self) -> str:
        """Serialize all events to a JSONL string."""
        return "\n".join(e.to_json() for e in self._events) + "\n" if self._events else ""

    def summary(self) -> dict:
        """Aggregate stats for the audit log."""
        total = len(self._events)
        violations = len(self.violations())
        run_ids = {e.run_id for e in self._events}
        tools_called = {e.tool_name for e in self._events if e.tool_name}
        policies_triggered = {e.policy for e in self._events if e.policy and not e.allowed}

        return {
            "total_events": total,
            "violations": violations,
            "allowed": total - violations,
            "runs": len(run_ids),
            "tools_called": sorted(tools_called),
            "policies_triggered": sorted(policies_triggered),
        }

    @classmethod
    def from_jsonl(cls, content: str) -> AuditLog:
        """Create an AuditLog from a JSONL string."""
        log = cls()
        for line in content.strip().split("\n"):
            line = line.strip()
            if line:
                data = json.loads(line)
                log._events.append(AuditEvent(**data))
        return log

    @classmethod
    def from_file(cls, path: Path) -> AuditLog:
        """Load an AuditLog from an existing JSONL file (read-only)."""
        log = cls()
        log._path = None  # don't write back
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    log._events.append(AuditEvent(**data))
        return log


class RotatingAuditLog(AuditLog):
    """AuditLog with file rotation when size exceeds max_bytes."""

    def __init__(self, path: Path, *, max_bytes: int = 10_000_000, backup_count: int = 5):
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        super().__init__(path=path)

    def write(self, event: AuditEvent) -> None:
        super().write(event)
        if self._path and self._path.exists() and self._path.stat().st_size > self._max_bytes:
            self._rotate()

    def _rotate(self) -> None:
        for i in range(self._backup_count, 0, -1):
            src = Path(f"{self._path}.{i}")
            dst = Path(f"{self._path}.{i + 1}")
            if i == self._backup_count and src.exists():
                src.unlink()
            elif src.exists():
                src.rename(dst)
        if self._path.exists():
            self._path.rename(Path(f"{self._path}.1"))
            self._path.touch()
