"""Tests for the CrewAI compilation target."""

import ast

import yaml

from cortex_protocol.targets.crewai import CrewAITarget


def test_generates_five_files(basic_spec):
    target = CrewAITarget()
    files = target.compile(basic_spec)
    assert len(files) == 5
    paths = {f.path for f in files}
    assert "config/agents.yaml" in paths
    assert "config/tasks.yaml" in paths
    assert "crew.py" in paths
    assert "requirements.txt" in paths
    assert "test_crew.py" in paths


def test_agents_yaml_valid(basic_spec):
    target = CrewAITarget()
    files = target.compile(basic_spec)
    agents_yaml = next(f for f in files if f.path == "config/agents.yaml")
    data = yaml.safe_load(agents_yaml.content)
    assert "support_agent" in data
    assert data["support_agent"]["role"] == "support-agent"


def test_agents_yaml_has_tools(basic_spec):
    target = CrewAITarget()
    files = target.compile(basic_spec)
    agents_yaml = next(f for f in files if f.path == "config/agents.yaml")
    data = yaml.safe_load(agents_yaml.content)
    tools = data["support_agent"]["tools"]
    assert "lookup-order" in tools
    assert "process-refund" in tools
    assert "send-email" in tools


def test_tasks_yaml_valid(basic_spec):
    target = CrewAITarget()
    files = target.compile(basic_spec)
    tasks_yaml = next(f for f in files if f.path == "config/tasks.yaml")
    data = yaml.safe_load(tasks_yaml.content)
    assert "support_agent_task" in data
    assert data["support_agent_task"]["agent"] == "support_agent"


def test_crew_py_valid_python(basic_spec):
    target = CrewAITarget()
    files = target.compile(basic_spec)
    crew_py = next(f for f in files if f.path == "crew.py")
    ast.parse(crew_py.content)


def test_max_iter_from_policy(policy_spec):
    target = CrewAITarget()
    files = target.compile(policy_spec)
    agents_yaml = next(f for f in files if f.path == "config/agents.yaml")
    data = yaml.safe_load(agents_yaml.content)
    assert data["incident_commander"]["max_iter"] == 8


def test_policy_agent_compiles(policy_spec):
    target = CrewAITarget()
    files = target.compile(policy_spec)
    crew_py = next(f for f in files if f.path == "crew.py")
    ast.parse(crew_py.content)
