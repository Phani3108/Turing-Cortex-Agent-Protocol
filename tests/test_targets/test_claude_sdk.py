"""Tests for the Claude Agent SDK compilation target."""

import ast

from cortex_protocol.models import AgentSpec
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


def _make_mcp_spec():
    return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: mcp-claude-agent
  description: Claude agent with MCP
  instructions: Test
tools:
  - name: github-tool
    description: GitHub via MCP
    mcp: "mcp-server-github@1.0.0"
  - name: local-handler
    description: A local tool
""")


def test_mcp_generates_handler_with_mcp_call():
    spec = _make_mcp_spec()
    target = ClaudeSDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "mcp-server-github" in agent_py.content
    assert "handle_github_tool" in agent_py.content


def test_non_mcp_tool_still_gets_todo_stub():
    spec = _make_mcp_spec()
    target = ClaudeSDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "# TODO: Implement local-handler" in agent_py.content


def test_mcp_setup_block_present():
    spec = _make_mcp_spec()
    target = ClaudeSDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "MCP Setup" in agent_py.content or "MCP server" in agent_py.content
