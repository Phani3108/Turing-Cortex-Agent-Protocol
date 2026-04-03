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
