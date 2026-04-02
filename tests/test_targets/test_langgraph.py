"""Tests for the LangGraph compilation target."""

import ast

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
