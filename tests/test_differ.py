"""Tests for the spec differ."""

import pytest

from cortex_protocol.differ import diff_specs, SpecDiff
from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, PolicySpec,
    EscalationPolicy, ModelConfig, ToolParameter,
)


def _base_spec(name="agent-v1"):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(
            name=name,
            description="Test agent",
            instructions="You are a helpful assistant.",
        ),
        tools=[
            ToolSpec(
                name="search",
                description="Search the web",
                parameters=ToolParameter(
                    type="object",
                    properties={"query": {"type": "string"}},
                    required=["query"],
                ),
            ),
            ToolSpec(
                name="jira",
                description="Create Jira tickets",
                parameters=ToolParameter(
                    type="object",
                    properties={"summary": {"type": "string"}},
                    required=["summary"],
                ),
            ),
        ],
        policies=PolicySpec(
            max_turns=10,
            require_approval=["jira"],
            forbidden_actions=["Do not share PII"],
            escalation=EscalationPolicy(trigger="on failure", target="human"),
        ),
        model=ModelConfig(preferred="claude-sonnet-4", fallback="gpt-4o", temperature=0.5),
    )


# ---------------------------------------------------------------------------
# No diff
# ---------------------------------------------------------------------------

class TestNoDiff:
    def test_identical_specs_no_diff(self):
        spec = _base_spec()
        result = diff_specs(spec, spec)
        assert result.is_empty

    def test_empty_diff_has_no_breaking_changes(self):
        spec = _base_spec()
        result = diff_specs(spec, spec)
        assert not result.has_breaking_changes


# ---------------------------------------------------------------------------
# Tool changes
# ---------------------------------------------------------------------------

class TestToolChanges:
    def test_added_tool_detected(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools = spec_b.tools + [
            ToolSpec(name="slack", description="Send Slack message",
                     parameters=ToolParameter(type="object", properties={}, required=[]))
        ]
        result = diff_specs(spec_a, spec_b)
        assert "slack" in result.tools_added
        assert not result.has_breaking_changes

    def test_removed_tool_is_breaking(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools = [t for t in spec_b.tools if t.name != "jira"]
        result = diff_specs(spec_a, spec_b)
        assert "jira" in result.tools_removed
        assert result.has_breaking_changes

    def test_modified_tool_description(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools[0] = ToolSpec(
            name="search",
            description="Updated description",
            parameters=spec_a.tools[0].parameters,
        )
        result = diff_specs(spec_a, spec_b)
        assert any(t.name == "search" for t in result.tools_modified)
        mod = next(t for t in result.tools_modified if t.name == "search")
        assert "description" in mod.detail

    def test_modified_tool_parameters(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools[0] = ToolSpec(
            name="search",
            description=spec_a.tools[0].description,
            parameters=ToolParameter(
                type="object",
                properties={"query": {"type": "string"}, "limit": {"type": "integer"}},
                required=["query"],
            ),
        )
        result = diff_specs(spec_a, spec_b)
        assert any(t.name == "search" for t in result.tools_modified)
        mod = next(t for t in result.tools_modified if t.name == "search")
        assert "parameters" in mod.detail


# ---------------------------------------------------------------------------
# Policy changes
# ---------------------------------------------------------------------------

class TestPolicyChanges:
    def test_max_turns_change_detected(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.policies.max_turns = 20
        result = diff_specs(spec_a, spec_b)
        turns_change = next((c for c in result.policy_changes if c.field == "max_turns"), None)
        assert turns_change is not None
        assert turns_change.old_value == 10
        assert turns_change.new_value == 20

    def test_require_approval_change_detected(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.policies.require_approval = ["jira", "slack"]
        result = diff_specs(spec_a, spec_b)
        assert any(c.field == "require_approval" for c in result.policy_changes)

    def test_removed_approval_requirement_is_breaking(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.policies.require_approval = []
        result = diff_specs(spec_a, spec_b)
        # policy changes = breaking
        assert result.has_breaking_changes

    def test_forbidden_actions_change(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.policies.forbidden_actions = ["Do not share PII", "Do not make promises"]
        result = diff_specs(spec_a, spec_b)
        assert any(c.field == "forbidden_actions" for c in result.policy_changes)

    def test_escalation_change(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.policies.escalation = EscalationPolicy(trigger="on timeout", target="vp-engineering")
        result = diff_specs(spec_a, spec_b)
        assert any(c.field == "escalation" for c in result.policy_changes)


# ---------------------------------------------------------------------------
# Model changes
# ---------------------------------------------------------------------------

class TestModelChanges:
    def test_model_preferred_change(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.model.preferred = "gpt-4o"
        result = diff_specs(spec_a, spec_b)
        assert any(c.field == "preferred" for c in result.model_changes)

    def test_temperature_change(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.model.temperature = 0.9
        result = diff_specs(spec_a, spec_b)
        assert any(c.field == "temperature" for c in result.model_changes)

    def test_model_changes_not_breaking(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.model.preferred = "gpt-4o"
        result = diff_specs(spec_a, spec_b)
        # model changes alone are not breaking
        assert not result.has_breaking_changes


# ---------------------------------------------------------------------------
# Identity changes
# ---------------------------------------------------------------------------

class TestIdentityChanges:
    def test_instructions_change_detected(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.agent.instructions = "You are a specialized assistant for incident response."
        result = diff_specs(spec_a, spec_b)
        assert result.instructions_changed

    def test_description_change_detected(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.agent.description = "Updated description"
        result = diff_specs(spec_a, spec_b)
        assert result.description_changed

    def test_unchanged_identity(self):
        spec = _base_spec()
        result = diff_specs(spec, spec)
        assert not result.instructions_changed
        assert not result.description_changed


# ---------------------------------------------------------------------------
# to_dict / summary_lines
# ---------------------------------------------------------------------------

class TestOutput:
    def test_to_dict_structure(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools.append(
            ToolSpec(name="new-tool", description="A new tool",
                     parameters=ToolParameter(type="object", properties={}, required=[]))
        )
        result = diff_specs(spec_a, spec_b)
        d = result.to_dict()
        assert "a" in d
        assert "b" in d
        assert "tools" in d
        assert "policies" in d
        assert "model" in d
        assert "identity" in d
        assert "breaking" in d

    def test_summary_lines_no_diff(self):
        spec = _base_spec()
        result = diff_specs(spec, spec)
        lines = result.summary_lines()
        assert any("No differences" in l for l in lines)

    def test_summary_lines_with_changes(self):
        spec_a = _base_spec()
        spec_b = _base_spec(name="agent-v2")
        spec_b.tools = [t for t in spec_b.tools if t.name != "jira"]
        result = diff_specs(spec_a, spec_b)
        lines = result.summary_lines()
        assert any("- tool: jira" in l for l in lines)
