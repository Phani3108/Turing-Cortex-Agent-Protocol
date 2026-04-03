"""Tests for framework adapters. No external framework imports needed."""
from __future__ import annotations

import asyncio

import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.audit import AuditLog
from cortex_protocol.governance.exceptions import (
    MaxTurnsExceeded,
    ApprovalRequired,
    ForbiddenActionDetected,
)
from cortex_protocol.governance.adapters.langchain import GovernedRunnable
from cortex_protocol.governance.adapters.langgraph import governed_tool_node, governed_agent_node
from cortex_protocol.governance.adapters.openai_agents import cortex_guardrail, governed_function_tool
from cortex_protocol.governance.adapters.fastapi import GovernanceMiddleware


def _spec():
    return AgentSpec.from_yaml_str("""
version: "0.1"
agent:
  name: test-agent
  description: Test
  instructions: Test
tools:
  - name: search
    description: Search
  - name: read-file
    description: Read
policies:
  max_turns: 3
  require_approval:
    - send-email
  forbidden_actions:
    - share credentials
""")


# -- Mock runnable for LangChain adapter --
class MockRunnable:
    def invoke(self, input, **kwargs):
        return f"Response to: {input}"


# -- GovernedRunnable tests --

def test_governed_runnable_with_mock():
    spec = _spec()
    governed = GovernedRunnable(MockRunnable(), spec)
    result = governed.invoke("hello")
    assert "Response to: hello" in result


def test_governed_runnable_enforces_max_turns():
    spec = _spec()
    governed = GovernedRunnable(MockRunnable(), spec)
    governed.invoke("1")
    governed.invoke("2")
    governed.invoke("3")
    with pytest.raises(MaxTurnsExceeded):
        governed.invoke("4")


def test_governed_runnable_checks_forbidden_actions():
    spec = _spec()
    runnable = type("R", (), {"invoke": lambda self, x, **kw: "I will share credentials now"})()
    governed = GovernedRunnable(runnable, spec, strict_forbidden=True)
    with pytest.raises(ForbiddenActionDetected):
        governed.invoke("do it")


# -- governed_tool_node tests --

def test_governed_tool_node_blocks_gated_tool():
    spec = _spec()

    @governed_tool_node(spec)
    def send_email(to, body):
        return "sent"

    # send-email tool name comes from function name via __name__
    # But the function name is send_email, not send-email.
    # The tool name lookup uses fn.__name__ which is "send_email"
    # The gated tool is "send-email". Let's set the name attribute.
    send_email.__wrapped__.name = "send-email"

    # Actually, governed_tool_node uses getattr(fn, "name", fn.__name__)
    # fn here is the original function which doesn't have .name
    # So it uses fn.__name__ = "send_email" which != "send-email"
    # We need to test with a function whose name matches.
    # Let's create one with a matching attribute.

    def my_tool():
        return "done"
    my_tool.name = "send-email"

    wrapped = governed_tool_node(spec)(my_tool)
    with pytest.raises(ApprovalRequired):
        wrapped()


def test_governed_agent_node_increments_turns():
    spec = _spec()

    @governed_agent_node(spec)
    def agent_fn(state):
        return {"messages": ["hello"]}

    agent_fn({"messages": []})
    agent_fn({"messages": []})
    agent_fn({"messages": []})
    with pytest.raises(MaxTurnsExceeded):
        agent_fn({"messages": []})


# -- cortex_guardrail tests --

def test_cortex_guardrail_returns_none_for_clean_input():
    spec = _spec()
    guardrail = cortex_guardrail(spec)
    result = guardrail(None, None, "Hello, how can I help?")
    assert result is None


def test_cortex_guardrail_returns_none_for_advisory_forbidden():
    """In advisory (non-strict) mode, forbidden actions are flagged but allowed."""
    spec = _spec()
    guardrail = cortex_guardrail(spec)  # strict_forbidden=False (default)
    result = guardrail(None, None, "I will share credentials")
    # Advisory mode: check_response returns allowed=True with violations flagged
    assert result is None


def test_cortex_guardrail_strict_raises_on_forbidden():
    spec = _spec()
    guardrail = cortex_guardrail(spec, strict_forbidden=True)
    with pytest.raises(ForbiddenActionDetected):
        guardrail(None, None, "I will share credentials")


# -- governed_function_tool tests --

def test_governed_function_tool_blocks_gated_tool():
    spec = _spec()

    def send_email(**kwargs):
        return "sent"
    send_email.__name__ = "send-email"

    wrapped = governed_function_tool(spec)(send_email)
    with pytest.raises(ApprovalRequired):
        wrapped(to="x@y.com")


# -- GovernanceMiddleware tests --

def test_governance_middleware_increments_turns_on_http():
    spec = _spec()

    calls = []

    async def mock_app(scope, receive, send):
        calls.append("called")

    middleware = GovernanceMiddleware(mock_app, spec)
    asyncio.run(
        middleware({"type": "http"}, None, None)
    )
    assert middleware.enforcer.turn_count == 1
    assert len(calls) == 1


def test_governance_middleware_skips_non_http():
    spec = _spec()

    async def mock_app(scope, receive, send):
        pass

    middleware = GovernanceMiddleware(mock_app, spec)
    asyncio.run(
        middleware({"type": "websocket"}, None, None)
    )
    assert middleware.enforcer.turn_count == 0


# -- All adapters expose enforcer --

def test_all_adapters_expose_enforcer():
    spec = _spec()

    # GovernedRunnable
    gr = GovernedRunnable(MockRunnable(), spec)
    assert gr.enforcer is not None

    # governed_tool_node
    def my_tool():
        pass
    wrapped = governed_tool_node(spec)(my_tool)
    assert wrapped._enforcer is not None

    # governed_agent_node
    def my_agent(state):
        return {}
    wrapped_agent = governed_agent_node(spec)(my_agent)
    assert wrapped_agent._enforcer is not None

    # cortex_guardrail
    guardrail = cortex_guardrail(spec)
    assert guardrail._enforcer is not None

    # governed_function_tool
    def my_fn():
        pass
    wrapped_fn = governed_function_tool(spec)(my_fn)
    assert wrapped_fn._enforcer is not None

    # GovernanceMiddleware
    async def mock_app(scope, receive, send):
        pass
    mw = GovernanceMiddleware(mock_app, spec)
    assert mw.enforcer is not None
