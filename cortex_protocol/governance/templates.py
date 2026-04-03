"""Built-in and registry-stored policy templates."""
from __future__ import annotations
from typing import Optional
from ..models import PolicySpec, EscalationPolicy


_CUSTOM_TEMPLATES: dict[str, PolicySpec] = {}


def register_template(name: str, policy: PolicySpec) -> None:
    _CUSTOM_TEMPLATES[name] = policy


def unregister_template(name: str) -> None:
    _CUSTOM_TEMPLATES.pop(name, None)


def get_template(name: str) -> PolicySpec | None:
    return _CUSTOM_TEMPLATES.get(name) or BUILTIN_TEMPLATES.get(name)


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
    Supports a single template name or a list of template names.
    """
    if not policy.from_template:
        return policy

    templates_to_merge = []
    if isinstance(policy.from_template, str):
        templates_to_merge = [policy.from_template]
    else:
        templates_to_merge = list(policy.from_template)

    # Start with empty base, merge each template in order
    merged = PolicySpec()
    found_any = False
    for template_ref in templates_to_merge:
        clean_name = template_ref.split("@")[0].split("/")[-1] if "/" in template_ref else template_ref.split("@")[0]
        template = _CUSTOM_TEMPLATES.get(clean_name) or BUILTIN_TEMPLATES.get(clean_name)
        if template:
            found_any = True
            merged = PolicySpec(
                max_turns=template.max_turns if merged.max_turns is None else merged.max_turns,
                require_approval=list(set(merged.require_approval) | set(template.require_approval)),
                forbidden_actions=list(set(merged.forbidden_actions) | set(template.forbidden_actions)),
                escalation=template.escalation if template.escalation.trigger and not merged.escalation.trigger else merged.escalation,
            )

    if not found_any:
        return policy  # Unknown template(s), return as-is

    # Apply local overrides on top
    final = PolicySpec(
        max_turns=policy.max_turns if policy.max_turns is not None else merged.max_turns,
        require_approval=list(set(merged.require_approval) | set(policy.require_approval)),
        forbidden_actions=list(set(merged.forbidden_actions) | set(policy.forbidden_actions)),
        escalation=policy.escalation if policy.escalation.trigger else merged.escalation,
        from_template=None,
    )
    return final


def list_templates() -> dict[str, dict]:
    """Return all built-in and custom templates as dicts for display."""
    all_templates = {**BUILTIN_TEMPLATES, **_CUSTOM_TEMPLATES}
    return {
        name: {
            "max_turns": t.max_turns,
            "require_approval": t.require_approval,
            "forbidden_actions": t.forbidden_actions,
        }
        for name, t in all_templates.items()
    }
