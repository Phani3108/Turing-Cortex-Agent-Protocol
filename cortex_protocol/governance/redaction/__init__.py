"""PII redaction for audit events.

Deterministic, rule-based redaction (no LLM, no network) so it can run
inside `AuditLog.write()` without slowing the hot path. The engine is a
pipeline of `Redactor` objects, each of which scans a string and returns
either the original or a redacted copy.

Packs (GDPR, HIPAA, PCI) compose a reasonable default set of detectors
for common domains. Callers can mix-and-match or add custom regexes.

Integration patterns:

    log = AuditLog(path=..., exporters=[RedactingExporter(real_exporter)])
    # OR redact *in place* before write:
    log = AuditLog(path=..., exporters=[ChainExporter([redactor_filter, real_exporter])])

The redactor operates on `AuditEvent.detail`, `AuditEvent.tool_input`
(values only), and — when enabled — `AuditEvent.run_id` / `agent`. It
never touches policy metadata (`event_type`, `allowed`, `policy`) so the
compliance / drift layers keep their signal.
"""

from __future__ import annotations

from .engine import (
    Redactor,
    RedactionResult,
    RegexRedactor,
    RedactionPipeline,
    RedactingExporter,
    redact_event,
    redact_text,
)
from .packs import (
    BUILTIN_PACKS,
    gdpr_pack,
    hipaa_pack,
    pci_pack,
    secrets_pack,
    combine_packs,
)

__all__ = [
    "Redactor",
    "RedactionResult",
    "RegexRedactor",
    "RedactionPipeline",
    "RedactingExporter",
    "redact_event",
    "redact_text",
    "BUILTIN_PACKS",
    "gdpr_pack",
    "hipaa_pack",
    "pci_pack",
    "secrets_pack",
    "combine_packs",
]
