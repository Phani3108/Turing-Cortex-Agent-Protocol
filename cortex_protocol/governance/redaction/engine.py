"""Core redaction primitives — regex detectors, pipelines, and an
`AuditLog.exporters`-compatible wrapper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Optional

from ..audit import AuditEvent


@dataclass
class RedactionResult:
    """The outcome of running a single redactor on a string."""

    text: str
    hits: list[str] = field(default_factory=list)   # detector ids that matched

    @property
    def redacted(self) -> bool:
        return bool(self.hits)


class Redactor:
    """Interface. Subclasses must expose an `id` attribute and `apply(text)`."""

    id: str

    def apply(self, text: str) -> RedactionResult:  # pragma: no cover - ABC
        raise NotImplementedError


@dataclass
class RegexRedactor(Redactor):
    """Replace every regex match with a deterministic placeholder.

    Example:
        RegexRedactor(id="email",
                       pattern=r"[\\w.+-]+@[\\w-]+\\.[\\w.-]+",
                       replacement="<EMAIL_REDACTED>")
    """

    id: str
    pattern: str
    replacement: str = ""
    flags: int = 0

    def __post_init__(self):
        self._re = re.compile(self.pattern, self.flags)
        if not self.replacement:
            self.replacement = f"<{self.id.upper()}_REDACTED>"

    def apply(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text=text)
        new_text, count = self._re.subn(self.replacement, text)
        if count == 0:
            return RedactionResult(text=text)
        return RedactionResult(text=new_text, hits=[self.id] * count)


class RedactionPipeline:
    """An ordered collection of redactors, applied in sequence."""

    def __init__(self, redactors: Optional[Iterable[Redactor]] = None):
        self._redactors: list[Redactor] = list(redactors or [])

    def add(self, r: Redactor) -> "RedactionPipeline":
        self._redactors.append(r)
        return self

    def extend(self, redactors: Iterable[Redactor]) -> "RedactionPipeline":
        self._redactors.extend(redactors)
        return self

    @property
    def redactors(self) -> list[Redactor]:
        return list(self._redactors)

    def apply(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text=text)
        hits: list[str] = []
        out = text
        for r in self._redactors:
            result = r.apply(out)
            if result.redacted:
                hits.extend(result.hits)
                out = result.text
        return RedactionResult(text=out, hits=hits)


# ---------------------------------------------------------------------------
# Event-level helpers
# ---------------------------------------------------------------------------

def redact_text(text: str, pipeline: RedactionPipeline) -> str:
    return pipeline.apply(text).text


def _redact_value(value: Any, pipeline: RedactionPipeline) -> tuple[Any, list[str]]:
    """Recursively redact strings anywhere inside a JSON-ish value."""
    if isinstance(value, str):
        result = pipeline.apply(value)
        return result.text, result.hits
    if isinstance(value, dict):
        hits: list[str] = []
        out = {}
        for k, v in value.items():
            new_v, h = _redact_value(v, pipeline)
            hits.extend(h)
            out[k] = new_v
        return out, hits
    if isinstance(value, list):
        hits = []
        out_list = []
        for item in value:
            new_item, h = _redact_value(item, pipeline)
            hits.extend(h)
            out_list.append(new_item)
        return out_list, hits
    return value, []


def redact_event(event: AuditEvent, pipeline: RedactionPipeline) -> tuple[AuditEvent, list[str]]:
    """Return a redacted copy of `event` plus the list of detector ids that fired.

    Fields redacted:
      - `detail`           (free-text)
      - `tool_input`       (value strings only — keys are left alone)

    Fields preserved verbatim (policy signal):
      - event_type, allowed, policy, tool_name, run_id, agent, turn,
        timestamp, chain_index, prev_hash, signature, cost_usd, tokens,
        model
    """
    all_hits: list[str] = []

    detail, hits1 = _redact_value(event.detail or "", pipeline)
    all_hits.extend(hits1)

    tool_input = event.tool_input
    if tool_input is not None:
        tool_input, hits2 = _redact_value(tool_input, pipeline)
        all_hits.extend(hits2)

    return replace(event, detail=detail, tool_input=tool_input), all_hits


# ---------------------------------------------------------------------------
# Exporter adapter — slot this into AuditLog(exporters=[...])
# ---------------------------------------------------------------------------

class RedactingExporter:
    """Wraps a downstream exporter and redacts events before handing them off.

    Usage:
        downstream = CloudAuditExporter(client)
        log = AuditLog(exporters=[RedactingExporter(downstream, pipeline)])

    The wrapped exporter sees only redacted events; the on-disk JSONL
    (owned by `AuditLog` itself) is *not* affected — redaction is for
    downstream sinks only. To redact the on-disk copy, use a
    `RedactingAuditLog` (subclass below) instead.
    """

    def __init__(
        self,
        downstream: Any,
        pipeline: RedactionPipeline,
        *,
        on_hit: Optional[Callable[[AuditEvent, list[str]], None]] = None,
    ):
        self._downstream = downstream
        self._pipeline = pipeline
        self._on_hit = on_hit

    def export_event(self, event: AuditEvent) -> None:
        redacted, hits = redact_event(event, self._pipeline)
        if hits and self._on_hit:
            self._on_hit(redacted, hits)
        self._downstream.export_event(redacted)


class RedactingAuditLog:
    """Drop-in `AuditLog`-shaped wrapper that redacts *on the way in*.

    Useful when the persisted JSONL should never carry raw PII.
    Delegates everything to the wrapped log except `write`, which
    redacts first.
    """

    def __init__(self, log, pipeline: RedactionPipeline,
                 on_hit: Optional[Callable[[AuditEvent, list[str]], None]] = None):
        self._log = log
        self._pipeline = pipeline
        self._on_hit = on_hit

    def write(self, event: AuditEvent) -> None:
        redacted, hits = redact_event(event, self._pipeline)
        if hits and self._on_hit:
            self._on_hit(redacted, hits)
        self._log.write(redacted)

    def __getattr__(self, name):
        return getattr(self._log, name)
