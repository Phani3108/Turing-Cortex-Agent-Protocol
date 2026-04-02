"""Tests for the OpenAI Agent SDK compilation target."""

import ast

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
