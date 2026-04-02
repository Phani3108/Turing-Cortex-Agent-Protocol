"""Tests for the OpenAI Agent SDK compilation target."""

import ast

import pytest

from cortex_protocol.models import AgentSpec, ToolSpec
from cortex_protocol.targets.openai_sdk import OpenAISDKTarget


def test_generates_three_files(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    assert len(files) == 3
    paths = {f.path for f in files}
    assert "agent.py" in paths
    assert "requirements.txt" in paths
    assert "test_agent.py" in paths


def test_agent_py_valid_python(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    # Should parse without syntax errors
    ast.parse(agent_py.content)


def test_agent_py_contains_tools(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "lookup_order" in agent_py.content
    assert "process_refund" in agent_py.content
    assert "send_email" in agent_py.content


def test_agent_py_contains_name(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "support-agent" in agent_py.content


def test_test_stub_valid_python(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    test_py = next(f for f in files if f.path == "test_agent.py")
    ast.parse(test_py.content)


def test_requirements_has_openai(basic_spec):
    target = OpenAISDKTarget()
    files = target.compile(basic_spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "openai" in reqs.content


def test_policy_agent_compiles(policy_spec):
    target = OpenAISDKTarget()
    files = target.compile(policy_spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    ast.parse(agent_py.content)
    assert "incident-commander" in agent_py.content


def _make_mcp_spec():
    return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: mcp-test-agent
  description: Test agent with MCP tools
  instructions: Test instructions
tools:
  - name: github-search
    description: Search GitHub
    mcp: "mcp-server-github@1.0.0"
  - name: local-tool
    description: A local tool
""")


def test_mcp_tool_generates_mcp_server_setup():
    spec = _make_mcp_spec()
    target = OpenAISDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "MCPServerStdio" in agent_py.content
    assert "mcp-server-github" in agent_py.content


def test_mcp_tool_no_function_tool_decorator():
    spec = _make_mcp_spec()
    target = OpenAISDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    # MCP tool should not generate a @function_tool wrapper
    assert "mcp_servers=" in agent_py.content


def test_non_mcp_tool_still_gets_todo_stub():
    spec = _make_mcp_spec()
    target = OpenAISDKTarget()
    files = target.compile(spec)
    agent_py = next(f for f in files if f.path == "agent.py")
    assert "# TODO: Implement local-tool" in agent_py.content


def test_mcp_requirements_has_mcp_package():
    spec = _make_mcp_spec()
    target = OpenAISDKTarget()
    files = target.compile(spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "openai-agents[mcp]" in reqs.content


def test_no_mcp_requirements_no_mcp_extra():
    target = OpenAISDKTarget()
    files = target.compile(AgentSpec.from_yaml_str("""
version: "0.1"
agent:
  name: no-mcp-agent
  description: Agent without MCP
  instructions: Do stuff
"""))
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "[mcp]" not in reqs.content
