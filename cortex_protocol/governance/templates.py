"""Built-in and registry-stored policy templates."""
from __future__ import annotations
from typing import Optional
from ..models import PolicySpec, EscalationPolicy


BUILTIN_TEMPLATES: dict[str, PolicySpec] = {
    "strict": PolicySpec(
        max_turns=10,
        require_approval=["*"],
        forbidden_actions=["share credentials", "delete data", "modify permissions", "access admin"],
    ),
    "read-only": PolicySpec(
        max_turns=20,
        forbidden_actions=["write", "delete", "create", "update", "modify", "insert", "remove"],
    ),
    "payment-safe": PolicySpec(
        max_turns=15,
        require_approval=["process-payment", "issue-refund", "transfer-funds"],
        forbidden_actions=["access admin", "share PII", "modify account", "share credentials"],
    ),
    "hipaa": PolicySpec(
        max_turns=10,
        require_approval=["access-patient-data", "share-medical-record", "update-health-record"],
        forbidden_actions=["share PHI externally", "store unencrypted data", "access without consent"],
    ),
    "minimal": PolicySpec(
        max_turns=50,
    ),
}


def resolve_policy_template(policy: PolicySpec) -> PolicySpec:
    """Resolve from_template and merge with local overrides.

    Template provides defaults. Explicit fields in policy override.
    """
    if not policy.from_template:
        return policy

    template_name = policy.from_template
    # Strip @ prefix and version for builtin lookup
    clean_name = template_name.split("@")[0].split("/")[-1] if "/" in template_name else template_name.split("@")[0]

    template = BUILTIN_TEMPLATES.get(clean_name)
    if not template:
        return policy  # Unknown template, return as-is

    # Merge: explicit overrides win, lists are unioned
    merged = PolicySpec(
        max_turns=policy.max_turns if policy.max_turns is not None else template.max_turns,
        require_approval=list(set(template.require_approval) | set(policy.require_approval)),
        forbidden_actions=list(set(template.forbidden_actions) | set(policy.forbidden_actions)),
        escalation=policy.escalation if policy.escalation.trigger else template.escalation,
        from_template=None,  # Clear after resolution
    )
    return merged


def list_templates() -> dict[str, dict]:
    """Return all built-in templates as dicts for display."""
    return {
        name: {
            "max_turns": t.max_turns,
            "require_approval": t.require_approval,
            "forbidden_actions": t.forbidden_actions,
        }
        for name, t in BUILTIN_TEMPLATES.items()
    }
