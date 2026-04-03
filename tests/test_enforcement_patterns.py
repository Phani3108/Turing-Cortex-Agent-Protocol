"""Tests for wildcard/glob/regex approval patterns, webhook handler, and async check."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch, MagicMock
from http.client import HTTPResponse
from io import BytesIO

import pytest

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, PolicySpec, ModelConfig, ToolSpec, ToolParameter,
)
from cortex_protocol.governance.enforcer import (
    PolicyEnforcer, EnforcementResult, _matches_approval_pattern,
)
from cortex_protocol.governance.approval import webhook_handler
from cortex_protocol.governance.audit import AuditLog
from cortex_protocol.governance.exceptions import ApprovalRequired


def _spec(require_approval=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name="test-agent", description="Test", instructions="Test agent instructions here."),
        tools=[ToolSpec(name="search", description="s", parameters=ToolParameter())],
        policies=PolicySpec(require_approval=require_approval or []),
        model=ModelConfig(),
    )


# ---------------------------------------------------------------------------
# _matches_approval_pattern
# ---------------------------------------------------------------------------

class TestMatchesApprovalPattern:
    def test_star_matches_everything(self):
        assert _matches_approval_pattern("anything", ["*"])
        assert _matches_approval_pattern("db-query", ["*"])

    def test_glob_matches(self):
        assert _matches_approval_pattern("db-query", ["db-*"])
        assert not _matches_approval_pattern("send-email", ["db-*"])

    def test_regex_matches(self):
        assert _matches_approval_pattern("process-refund", ["/^process-.*/"])
        assert not _matches_approval_pattern("delete-user", ["/^process-.*/"])

    def test_exact_match_backward_compat(self):
        assert _matches_approval_pattern("send-email", ["send-email"])
        assert not _matches_approval_pattern("send-sms", ["send-email"])

    def test_mixed_patterns(self):
        patterns = ["send-email", "db-*", "*-admin"]
        assert _matches_approval_pattern("send-email", patterns)
        assert _matches_approval_pattern("db-query", patterns)
        assert _matches_approval_pattern("super-admin", patterns)
        assert not _matches_approval_pattern("search", patterns)

    def test_question_mark_glob(self):
        assert _matches_approval_pattern("db-x", ["db-?"])
        assert not _matches_approval_pattern("db-xy", ["db-?"])

    def test_bracket_glob(self):
        assert _matches_approval_pattern("db-a", ["db-[abc]"])
        assert not _matches_approval_pattern("db-d", ["db-[abc]"])

    def test_empty_patterns(self):
        assert not _matches_approval_pattern("anything", [])


# ---------------------------------------------------------------------------
# webhook_handler
# ---------------------------------------------------------------------------

class TestWebhookHandler:
    def test_approved_response(self):
        handler = webhook_handler("https://example.com/approve")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"approved": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = handler("send-email", {}, {})
        assert result is True

    def test_denied_response(self):
        handler = webhook_handler("https://example.com/approve")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"approved": False}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = handler("send-email", {}, {})
        assert result is False

    def test_on_error_deny(self):
        handler = webhook_handler("https://example.com/approve", on_error="deny")
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = handler("send-email", {}, {})
        assert result is False

    def test_on_error_allow(self):
        handler = webhook_handler("https://example.com/approve", on_error="allow")
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = handler("send-email", {}, {})
        assert result is True

    def test_on_error_raise(self):
        handler = webhook_handler("https://example.com/approve", on_error="raise")
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            with pytest.raises(Exception, match="timeout"):
                handler("send-email", {}, {})


# ---------------------------------------------------------------------------
# async_check_tool_call
# ---------------------------------------------------------------------------

class TestAsyncCheckToolCall:
    def test_sync_handler_works(self):
        def sync_handler(tool_name, tool_input, context):
            return True

        e = PolicyEnforcer(_spec(require_approval=["send-email"]), approval_handler=sync_handler)
        result = asyncio.run(
            e.async_check_tool_call("send-email", {})
        )
        assert result.allowed

    def test_async_handler_works(self):
        async def async_handler(tool_name, tool_input, context):
            return True

        e = PolicyEnforcer(_spec(require_approval=["send-email"]), approval_handler=async_handler)
        result = asyncio.run(
            e.async_check_tool_call("send-email", {})
        )
        assert result.allowed

    def test_async_handler_deny(self):
        async def async_handler(tool_name, tool_input, context):
            return False

        e = PolicyEnforcer(_spec(require_approval=["send-email"]), approval_handler=async_handler)
        with pytest.raises(ApprovalRequired):
            asyncio.run(
                e.async_check_tool_call("send-email", {})
            )

    def test_no_handler_raises(self):
        e = PolicyEnforcer(_spec(require_approval=["send-email"]))
        with pytest.raises(ApprovalRequired):
            asyncio.run(
                e.async_check_tool_call("send-email", {})
            )

    def test_allowed_tool_no_approval_needed(self):
        e = PolicyEnforcer(_spec(require_approval=["send-email"]))
        result = asyncio.run(
            e.async_check_tool_call("search", {})
        )
        assert result.allowed
