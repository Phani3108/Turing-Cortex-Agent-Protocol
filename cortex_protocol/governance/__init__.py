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
)
from .audit import AuditEvent, AuditLog
from .enforcer import PolicyEnforcer, EnforcementResult
from .enforce import enforce
from .approval import always_approve, always_deny, allowlist_handler, log_and_approve

__all__ = [
    "PolicyViolation",
    "MaxTurnsExceeded",
    "ApprovalRequired",
    "ForbiddenActionDetected",
    "AuditEvent",
    "AuditLog",
    "PolicyEnforcer",
    "EnforcementResult",
    "enforce",
    "always_approve",
    "always_deny",
    "allowlist_handler",
    "log_and_approve",
]
