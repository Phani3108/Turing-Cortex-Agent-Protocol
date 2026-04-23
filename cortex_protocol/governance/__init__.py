"""Cortex Protocol — Runtime Governance Engine.

Provides runtime policy enforcement, audit logging, and compliance tooling
for agent specs. The linter (linter.py) checks specs at build time; this
package enforces policies at run time.
"""

from .exceptions import (
    PolicyViolation,
    MaxTurnsExceeded,
    ApprovalRequired,
    ForbiddenActionDetected,
    BudgetExceeded,
    RuleDenied,
)
from .dsl import (
    Predicate, RuleError, RuleAction, RuleDecision, RuleSet,
    compile_expression, compile_rule, evaluate_rules,
)
from .audit import AuditEvent, AuditLog
from .signed_audit import (
    ChainVerificationError,
    SignedAuditLog,
    event_hash,
    verify_chain,
    verify_event_signature,
)
from .evidence import (
    PacketBuildResult,
    PacketVerifyResult,
    build_evidence_packet,
    verify_evidence_packet,
)
from .replay import (
    ReplayDecision,
    ReplayReport,
    replay,
)
from .redaction import (
    BUILTIN_PACKS as REDACTION_PACKS,
    RedactingExporter,
    RedactionPipeline,
    RegexRedactor,
    combine_packs,
    gdpr_pack,
    hipaa_pack,
    pci_pack,
    redact_event,
    redact_text,
    secrets_pack,
)
from .cost import (
    CostTracker,
    CostSnapshot,
    ModelPricing,
    ModelPrice,
    UsageSample,
    aggregate_samples,
)
from .enforcer import PolicyEnforcer, EnforcementResult
from .enforce import enforce
from .approval import always_approve, always_deny, allowlist_handler, log_and_approve

__all__ = [
    "PolicyViolation",
    "MaxTurnsExceeded",
    "ApprovalRequired",
    "ForbiddenActionDetected",
    "BudgetExceeded",
    "RuleDenied",
    "Predicate", "RuleError", "RuleAction", "RuleDecision", "RuleSet",
    "compile_expression", "compile_rule", "evaluate_rules",
    "AuditEvent",
    "AuditLog",
    "SignedAuditLog",
    "ChainVerificationError",
    "event_hash",
    "verify_chain",
    "verify_event_signature",
    "PacketBuildResult",
    "PacketVerifyResult",
    "build_evidence_packet",
    "verify_evidence_packet",
    "REDACTION_PACKS",
    "RedactingExporter",
    "RedactionPipeline",
    "RegexRedactor",
    "combine_packs",
    "gdpr_pack", "hipaa_pack", "pci_pack", "secrets_pack",
    "redact_event", "redact_text",
    "ReplayDecision", "ReplayReport", "replay",
    "CostTracker",
    "CostSnapshot",
    "ModelPricing",
    "ModelPrice",
    "UsageSample",
    "aggregate_samples",
    "PolicyEnforcer",
    "EnforcementResult",
    "enforce",
    "always_approve",
    "always_deny",
    "allowlist_handler",
    "log_and_approve",
]
