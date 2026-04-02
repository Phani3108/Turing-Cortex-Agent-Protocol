"""Tests for the validator module."""

from pathlib import Path

from cortex_protocol.validator import validate_data, validate_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_valid_basic_agent():
    spec, errors = validate_file(FIXTURES / "basic_agent.yaml")
    assert spec is not None
    assert errors == []


def test_valid_policy_agent():
    spec, errors = validate_file(FIXTURES / "policy_agent.yaml")
    assert spec is not None
    assert errors == []


def test_missing_file():
    spec, errors = validate_file("/nonexistent/agent.yaml")
    assert spec is None
    assert len(errors) == 1
    assert "not found" in errors[0].lower()


def test_missing_agent_name():
    spec, errors = validate_data({
        "agent": {
            "description": "No name",
            "instructions": "Do stuff",
        }
    })
    assert spec is None
    assert any("name" in e.lower() for e in errors)


def test_missing_agent_block():
    spec, errors = validate_data({"tools": []})
    assert spec is None
    assert len(errors) > 0


def test_unknown_tool_in_approval():
    spec, errors = validate_data({
        "agent": {
            "name": "test",
            "description": "test",
            "instructions": "test",
        },
        "tools": [
            {"name": "search", "description": "Search things"},
        ],
        "policies": {
            "require_approval": ["nonexistent-tool"],
        },
    })
    assert spec is None
    assert any("nonexistent-tool" in e for e in errors)


def test_invalid_temperature():
    spec, errors = validate_data({
        "agent": {
            "name": "test",
            "description": "test",
            "instructions": "test",
        },
        "model": {
            "temperature": 5.0,
        },
    })
    assert spec is None
    assert any("temperature" in e for e in errors)


def test_invalid_max_turns():
    spec, errors = validate_data({
        "agent": {
            "name": "test",
            "description": "test",
            "instructions": "test",
        },
        "policies": {
            "max_turns": 0,
        },
    })
    assert spec is None
    assert any("max_turns" in e for e in errors)
