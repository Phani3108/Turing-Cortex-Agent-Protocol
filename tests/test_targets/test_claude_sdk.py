"""Tests for the Claude Agent SDK compilation target."""

import ast

from cortex_protocol.targets.claude_sdk import ClaudeSDKTarget


def test_generates_three_files(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    assert len(files) == 3
    paths = {f.path for f in files}
    assert "agent.py" in paths
    assert "requirements.txt" in paths
    assert "test_agent.py" in paths


def test_agent_py_valid_python(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    ast.parse(agent_py.content)


def test_agent_uses_anthropic(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "import anthropic" in agent_py.content
    assert "anthropic.Anthropic()" in agent_py.content


def test_tools_have_input_schema(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "input_schema" in agent_py.content


def test_tool_dispatch_complete(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "handle_lookup_order" in agent_py.content
    assert "handle_process_refund" in agent_py.content
    assert "handle_send_email" in agent_py.content


def test_test_stub_valid_python(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    test_py = next(f for f in files if f.path == "test_agent.py")
    ast.parse(test_py.content)


def test_requirements_has_anthropic(basic_spec):
    target = ClaudeSDKTarget()
    files = target.compile(basic_spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "anthropic" in reqs.content


def test_policy_agent_compiles(policy_spec):
    target = ClaudeSDKTarget()
    files = target.compile(policy_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    ast.parse(agent_py.content)
