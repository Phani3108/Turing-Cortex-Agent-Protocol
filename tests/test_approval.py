"""Tests for approval delegation API."""
from __future__ import annotations

import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.enforcer import PolicyEnforcer
from cortex_protocol.governance.audit import AuditLog
from cortex_protocol.governance.exceptions import ApprovalRequired
from cortex_protocol.governance.approval import (
    always_approve,
    always_deny,
    allowlist_handler,
    log_and_approve,
)


def _spec_with_approval():
    return AgentSpec.from_yaml_str("""
version: "0.1"
agent:
  name: test-agent
  description: Test
  instructions: Test
tools:
  - name: send-email
    description: Send email
  - name: delete-user
    description: Delete user
  - name: search
    description: Search
policies:
  max_turns: 10
  require_approval:
    - send-email
    - delete-user
""")


def test_always_approve_allows_gated_tool():
    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=always_approve)
    result = enforcer.check_tool_call("send-email", {"to": "a@b.com"})
    assert result.allowed is True


def test_always_deny_blocks_gated_tool():
    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=always_deny)
    with pytest.raises(ApprovalRequired):
        enforcer.check_tool_call("send-email", {"to": "a@b.com"})


def test_allowlist_handler_allows_listed_tool():
    spec = _spec_with_approval()
    audit = AuditLog()
    handler = allowlist_handler("send-email")
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=handler)
    result = enforcer.check_tool_call("send-email", {})
    assert result.allowed is True


def test_allowlist_handler_blocks_unlisted_tool():
    spec = _spec_with_approval()
    audit = AuditLog()
    handler = allowlist_handler("send-email")
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=handler)
    with pytest.raises(ApprovalRequired):
        enforcer.check_tool_call("delete-user", {})


def test_no_handler_raises_approval_required():
    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit)
    with pytest.raises(ApprovalRequired):
        enforcer.check_tool_call("send-email", {})


def test_handler_decision_logged_in_audit():
    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=always_approve)
    enforcer.check_tool_call("send-email", {})
    events = audit.events()
    assert len(events) == 1
    assert events[0].event_type == "tool_approved"
    assert events[0].allowed is True


def test_handler_receives_correct_context():
    captured = {}

    def capture_handler(tool_name, tool_input, context):
        captured.update(context)
        return True

    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=capture_handler)
    enforcer.check_tool_call("send-email", {"to": "x@y.com"})
    assert "run_id" in captured
    assert "turn" in captured
    assert captured["agent"] == "test-agent"


def test_log_and_approve_calls_log_function():
    messages = []
    handler = log_and_approve(messages.append)
    spec = _spec_with_approval()
    audit = AuditLog()
    enforcer = PolicyEnforcer(spec, audit_log=audit, approval_handler=handler)
    enforcer.check_tool_call("send-email", {})
    assert len(messages) == 1
    assert "Auto-approved: send-email" in messages[0]
