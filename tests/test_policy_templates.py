"""Tests for policy templates."""
from __future__ import annotations

import pytest

from cortex_protocol.models import PolicySpec
from cortex_protocol.governance.templates import (
    resolve_policy_template,
    list_templates,
    BUILTIN_TEMPLATES,
)


def test_resolve_strict_template():
    policy = PolicySpec(from_template="strict")
    resolved = resolve_policy_template(policy)
    assert resolved.max_turns == 10
    assert "*" in resolved.require_approval
    assert "share credentials" in resolved.forbidden_actions


def test_resolve_payment_safe_template():
    policy = PolicySpec(from_template="payment-safe")
    resolved = resolve_policy_template(policy)
    assert resolved.max_turns == 15
    assert "process-payment" in resolved.require_approval
    assert "share PII" in resolved.forbidden_actions


def test_template_with_max_turns_override():
    policy = PolicySpec(from_template="strict", max_turns=3)
    resolved = resolve_policy_template(policy)
    assert resolved.max_turns == 3  # override wins


def test_template_with_extra_forbidden_actions_union():
    policy = PolicySpec(
        from_template="strict",
        forbidden_actions=["custom-ban"],
    )
    resolved = resolve_policy_template(policy)
    # Should have both template and custom
    assert "share credentials" in resolved.forbidden_actions
    assert "custom-ban" in resolved.forbidden_actions


def test_unknown_template_returns_original():
    policy = PolicySpec(from_template="nonexistent-template")
    resolved = resolve_policy_template(policy)
    assert resolved.from_template == "nonexistent-template"


def test_from_template_cleared_after_resolution():
    policy = PolicySpec(from_template="minimal")
    resolved = resolve_policy_template(policy)
    assert resolved.from_template is None


def test_list_templates_returns_all_builtins():
    templates = list_templates()
    assert "strict" in templates
    assert "read-only" in templates
    assert "payment-safe" in templates
    assert "hipaa" in templates
    assert "minimal" in templates
    for name, info in templates.items():
        assert "max_turns" in info
        assert "require_approval" in info
        assert "forbidden_actions" in info


# ---------------------------------------------------------------------------
# Template composition (list of templates)
# ---------------------------------------------------------------------------

def test_list_composition_unions_both():
    from cortex_protocol.governance.templates import register_template, unregister_template
    policy = PolicySpec(from_template=["read-only", "payment-safe"])
    resolved = resolve_policy_template(policy)
    # read-only has forbidden: write, delete, create, etc.
    # payment-safe has require_approval: process-payment, etc.
    assert "process-payment" in resolved.require_approval
    assert "write" in resolved.forbidden_actions or "delete" in resolved.forbidden_actions
    assert resolved.from_template is None


# ---------------------------------------------------------------------------
# Custom template registry
# ---------------------------------------------------------------------------

def test_custom_template_registered_and_resolved():
    from cortex_protocol.governance.templates import register_template, unregister_template
    try:
        custom = PolicySpec(max_turns=7, forbidden_actions=["custom-ban"])
        register_template("my-custom", custom)
        policy = PolicySpec(from_template="my-custom")
        resolved = resolve_policy_template(policy)
        assert resolved.max_turns == 7
        assert "custom-ban" in resolved.forbidden_actions
    finally:
        unregister_template("my-custom")


def test_custom_overrides_builtin():
    from cortex_protocol.governance.templates import register_template, unregister_template
    try:
        custom_strict = PolicySpec(max_turns=99, require_approval=["custom-tool"])
        register_template("strict", custom_strict)
        policy = PolicySpec(from_template="strict")
        resolved = resolve_policy_template(policy)
        assert resolved.max_turns == 99
        assert "custom-tool" in resolved.require_approval
    finally:
        unregister_template("strict")


def test_list_templates_includes_custom():
    from cortex_protocol.governance.templates import register_template, unregister_template
    try:
        register_template("my-test-template", PolicySpec(max_turns=5))
        templates = list_templates()
        assert "my-test-template" in templates
    finally:
        unregister_template("my-test-template")


def test_unregister_removes_custom():
    from cortex_protocol.governance.templates import register_template, unregister_template, get_template
    register_template("temp-tmpl", PolicySpec(max_turns=3))
    assert get_template("temp-tmpl") is not None
    unregister_template("temp-tmpl")
    assert get_template("temp-tmpl") is None
