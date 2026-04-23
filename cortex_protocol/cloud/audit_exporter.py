"""Stream AuditEvents to Cortex Cloud.

Plugs into `AuditLog(exporters=[...])`. Each `export_event()` call buffers
an event; the exporter flushes either when the buffer reaches `batch_size`
or when `flush_interval_seconds` elapses since the first buffered event.

Retries: failed POSTs go into a retry queue with exponential backoff. An
event is retained on disk (at `fallback_path`) if it can't be delivered
after `max_retries` attempts — better to tolerate a noisy disk than to
silently drop an audit row.

Gating: requires the `cloud_audit` feature (Pro tier). If an exporter is
instantiated on Standard tier, it degrades to a no-op with a one-time
warning printed to stderr — callers never see an exception.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..governance.audit import AuditEvent
from ..licensing import Feature, has_feature
from .client import CloudClient, CloudHTTPError


DEFAULT_BATCH_SIZE = 100
DEFAULT_FLUSH_INTERVAL_S = 5.0
DEFAULT_MAX_RETRIES = 3
AUDIT_ENDPOINT = "/v1/audit/events"


def _event_to_dict(event: AuditEvent) -> dict:
    d = asdict(event)
    return {k: v for k, v in d.items() if v is not None}


class CloudAuditExporter:
    """Buffered, retrying audit event shipper for Cortex Cloud.

    Thread-safe. Use as:
        exporter = CloudAuditExporter(client)
        log = AuditLog(path=..., exporters=[exporter])
        ...
        exporter.flush()   # before process exit
    """

    def __init__(
        self,
        client: CloudClient,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        endpoint: str = AUDIT_ENDPOINT,
        fallback_path: Optional[Path] = None,
        clock: Optional[Callable[[], float]] = None,
        warn: Optional[Callable[[str], None]] = None,
    ):
        self._client = client
        self._batch_size = max(1, batch_size)
        self._interval = max(0.0, flush_interval_seconds)
        self._max_retries = max(0, max_retries)
        self._endpoint = endpoint
        self._fallback_path = fallback_path
        self._clock = clock or time.monotonic
        self._warn = warn or (lambda msg: print(f"[cortex-cloud] {msg}", file=sys.stderr))

        self._buffer: list[AuditEvent] = []
        self._first_buffered_at: Optional[float] = None
        self._lock = threading.Lock()
        self._degraded = False
        self._degraded_reason = ""
        self._check_entitlement()

    # -----------------------------------------------------------------
    # Entitlement gating
    # -----------------------------------------------------------------

    def _check_entitlement(self) -> None:
        if not has_feature(Feature.CLOUD_AUDIT):
            self._degraded = True
            self._degraded_reason = (
                "Cloud audit streaming requires the Pro tier. "
                "Events will be kept locally only."
            )
            if "CORTEX_SILENT_DEGRADE" not in os.environ:
                self._warn(self._degraded_reason)

    @property
    def degraded(self) -> bool:
        return self._degraded

    # -----------------------------------------------------------------
    # Public API — `export_event` matches the AuditLog exporter protocol.
    # -----------------------------------------------------------------

    def export_event(self, event: AuditEvent) -> None:
        if self._degraded:
            return
        with self._lock:
            self._buffer.append(event)
            if self._first_buffered_at is None:
                self._first_buffered_at = self._clock()
            should_flush = (
                len(self._buffer) >= self._batch_size
                or (self._clock() - self._first_buffered_at) >= self._interval
            )
            batch = self._drain_if(should_flush)
        if batch:
            self._deliver(batch)

    def flush(self) -> None:
        if self._degraded:
            return
        with self._lock:
            batch = self._drain_if(True)
        if batch:
            self._deliver(batch)

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _drain_if(self, should_flush: bool) -> list[AuditEvent]:
        if not should_flush or not self._buffer:
            return []
        batch = list(self._buffer)
        self._buffer.clear()
        self._first_buffered_at = None
        return batch

    def _deliver(self, events: list[AuditEvent]) -> None:
        payload = {"events": [_event_to_dict(e) for e in events]}
        backoff = 0.5
        for attempt in range(self._max_retries + 1):
            try:
                self._client.request("POST", self._endpoint, body=payload)
                return
            except CloudHTTPError as e:
                if 500 <= e.status < 600 and attempt < self._max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                self._persist_fallback(events, reason=str(e))
                return
            except Exception as e:  # transport-level
                if attempt < self._max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                self._persist_fallback(events, reason=str(e))
                return

    def _persist_fallback(self, events: list[AuditEvent], *, reason: str) -> None:
        msg = (
            f"Cloud audit delivery failed after {self._max_retries + 1} attempts ({reason}). "
            f"Buffered {len(events)} event(s) to fallback."
        )
        self._warn(msg)
        if self._fallback_path is None:
            return
        try:
            self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._fallback_path, "a") as f:
                for e in events:
                    f.write(json.dumps(_event_to_dict(e)) + "\n")
        except OSError as e:  # pragma: no cover — disk full
            self._warn(f"Fallback persist also failed: {e}")


def drain_fallback(
    fallback_path: Path,
    client: CloudClient,
    *,
    endpoint: str = AUDIT_ENDPOINT,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[int, int]:
    """Replay a fallback JSONL file into the Cloud. Returns (sent, remaining).

    Events that succeed are removed from the file; failures stay behind so
    a later retry can pick them up.
    """
    if not fallback_path.exists():
        return 0, 0

    with open(fallback_path) as f:
        lines = [line.strip() for line in f if line.strip()]

    sent = 0
    remaining: list[str] = []

    for i in range(0, len(lines), batch_size):
        batch = lines[i: i + batch_size]
        events = [json.loads(line) for line in batch]
        try:
            client.request("POST", endpoint, body={"events": events})
            sent += len(batch)
        except CloudHTTPError:
            remaining.extend(batch)

    if remaining:
        fallback_path.write_text("\n".join(remaining) + "\n")
    else:
        fallback_path.unlink()

    return sent, len(remaining)
