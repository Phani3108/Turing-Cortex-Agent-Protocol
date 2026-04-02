"""Tests for Pydantic models and schema validation."""

import json

import yaml

from cortex_protocol.models import AgentSpec, ToolSpec, PolicySpec


def test_parse_basic_yaml(basic_spec):
    assert basic_spec.agent.name == "support-agent"
    assert len(basic_spec.tools) == 3
    assert basic_spec.model.preferred == "claude-sonnet-4"


def test_parse_policy_yaml(policy_spec):
    assert policy_spec.agent.name == "incident-commander"
    assert policy_spec.policies.max_turns == 8
    assert "pager" in policy_spec.policies.require_approval
    assert len(policy_spec.policies.forbidden_actions) == 3


def test_tool_parameters(basic_spec):
    refund_tool = next(t for t in basic_spec.tools if t.name == "process-refund")
    assert "order_id" in refund_tool.parameters.properties
    assert "amount" in refund_tool.parameters.properties
    assert "order_id" in refund_tool.parameters.required


def test_round_trip_yaml(basic_spec):
    """YAML -> Pydantic -> YAML -> Pydantic preserves data."""
    yaml_str = basic_spec.to_yaml()
    reparsed = AgentSpec.from_yaml_str(yaml_str)
    assert reparsed.agent.name == basic_spec.agent.name
    assert len(reparsed.tools) == len(basic_spec.tools)
    assert reparsed.policies.max_turns == basic_spec.policies.max_turns


def test_round_trip_json(basic_spec):
    """Pydantic -> JSON -> Pydantic preserves data."""
    json_str = basic_spec.model_dump_json()
    reparsed = AgentSpec.model_validate_json(json_str)
    assert reparsed.agent.name == basic_spec.agent.name
    assert len(reparsed.tools) == len(basic_spec.tools)


def test_minimal_spec():
    """Minimal valid spec — just name, description, instructions."""
    data = {
        "agent": {
            "name": "minimal",
            "description": "A minimal agent",
            "instructions": "Do the thing.",
        }
    }
    spec = AgentSpec.model_validate(data)
    assert spec.agent.name == "minimal"
    assert spec.tools == []
    assert spec.policies.max_turns is None


def test_json_schema_export():
    """JSON Schema can be generated from the model."""
    schema = AgentSpec.model_json_schema()
    assert schema["type"] == "object"
    assert "agent" in schema.get("required", []) or "agent" in schema.get("properties", {})
