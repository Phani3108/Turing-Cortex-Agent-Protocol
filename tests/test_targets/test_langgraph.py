"""Tests for the LangGraph compilation target."""

import ast

from cortex_protocol.models import AgentSpec
from cortex_protocol.targets.langgraph import LangGraphTarget


def test_generates_three_files(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    assert len(files) == 3
    paths = {f.path for f in files}
    assert "agent_graph.py" in paths
    assert "requirements.txt" in paths
    assert "test_graph.py" in paths


def test_agent_graph_valid_python(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    ast.parse(graph_py.content)


def test_graph_has_state_class(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "class AgentState" in graph_py.content
    assert "messages" in graph_py.content


def test_graph_has_tools(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "lookup_order" in graph_py.content
    assert "process_refund" in graph_py.content
    assert "send_email" in graph_py.content


def test_graph_has_routing(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "should_continue" in graph_py.content
    assert "ToolNode" in graph_py.content


def test_claude_model_uses_anthropic_import(policy_spec):
    """When model is claude, should import ChatAnthropic... but policy_spec uses gpt-4o."""
    # policy_spec uses gpt-4o, so it should use ChatOpenAI
    target = LangGraphTarget()
    files = target.compile(policy_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "ChatOpenAI" in graph_py.content


def test_claude_model_import(basic_spec):
    """basic_spec uses claude-sonnet-4, should use ChatAnthropic."""
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "ChatAnthropic" in graph_py.content


def test_requirements_match_model(basic_spec, policy_spec):
    target = LangGraphTarget()

    # basic uses claude
    files = target.compile(basic_spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "langchain-anthropic" in reqs.content

    # policy uses gpt
    files = target.compile(policy_spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "langchain-openai" in reqs.content


def test_approval_policy_noted(policy_spec):
    target = LangGraphTarget()
    files = target.compile(policy_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "interrupt" in graph_py.content.lower() or "approval" in graph_py.content.lower()


def test_test_stub_valid_python(basic_spec):
    target = LangGraphTarget()
    files = target.compile(basic_spec)
    test_py = next(f for f in files if f.path == "test_graph.py")
    ast.parse(test_py.content)


def test_policy_agent_compiles(policy_spec):
    target = LangGraphTarget()
    files = target.compile(policy_spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    ast.parse(graph_py.content)


def _make_mcp_spec():
    return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: mcp-lang-agent
  description: LangGraph agent with MCP
  instructions: Test
tools:
  - name: gh-search
    description: GitHub search via MCP
    mcp: "mcp-server-github@1.0.0"
  - name: local-op
    description: Local operation
""")


def test_mcp_adds_mcp_client_import():
    spec = _make_mcp_spec()
    target = LangGraphTarget()
    files = target.compile(spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "MultiServerMCPClient" in graph_py.content


def test_mcp_server_name_in_output():
    spec = _make_mcp_spec()
    target = LangGraphTarget()
    files = target.compile(spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "mcp-server-github" in graph_py.content


def test_non_mcp_tool_still_gets_todo():
    spec = _make_mcp_spec()
    target = LangGraphTarget()
    files = target.compile(spec)
    graph_py = next(f for f in files if f.path == "agent_graph.py")
    assert "# TODO: Implement local-op" in graph_py.content


def test_mcp_requirements_has_adapter():
    spec = _make_mcp_spec()
    target = LangGraphTarget()
    files = target.compile(spec)
    reqs = next(f for f in files if f.path == "requirements.txt")
    assert "langchain-mcp-adapters" in reqs.content
