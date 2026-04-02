"""Tests for the system prompt compilation target."""

import ast

from cortex_protocol.targets.system_prompt import SystemPromptTarget


def test_generates_one_file(basic_spec):
    target = SystemPromptTarget()
    files = target.compile(basic_spec)
    assert len(files) == 1
    assert files[0].path == "system_prompt.md"


def test_prompt_contains_identity(basic_spec):
    target = SystemPromptTarget()
    files = target.compile(basic_spec)
    assert "support-agent" in files[0].content


def test_model_override():
    """Model hint overrides the spec's preferred model."""
    from cortex_protocol.models import AgentSpec

    spec = AgentSpec.model_validate({
        "agent": {"name": "test", "description": "test", "instructions": "test"},
        "model": {"preferred": "gpt-4o"},
    })

    # With Claude override, should use XML
    target = SystemPromptTarget(model_hint="claude-sonnet-4")
    files = target.compile(spec)
    assert "<identity>" in files[0].content

    # With GPT override, should use numbered lists
    target = SystemPromptTarget(model_hint="gpt-4o")
    files = target.compile(spec)
    assert "## Identity" in files[0].content or "1." in files[0].content


def test_policies_in_prompt(policy_spec):
    target = SystemPromptTarget()
    files = target.compile(policy_spec)
    content = files[0].content
    assert "pager" in content  # require_approval
    assert "NEVER" in content  # forbidden_actions
    assert "vp-engineering" in content  # escalation


def test_mcp_tool_annotated_in_system_prompt():
    from cortex_protocol.models import AgentSpec
    spec = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: mcp-sys-agent
  description: Agent with MCP
  instructions: Test
tools:
  - name: gh-search
    description: Search GitHub
    mcp: "mcp-server-github@1.0.0"
""")
    target = SystemPromptTarget()
    files = target.compile(spec)
    assert "via MCP" in files[0].content
    assert "mcp-server-github" in files[0].content
