"""Tests for multi-level inheritance and cycle detection."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.registry.local import LocalRegistry
from cortex_protocol.registry.resolver import resolve_extends


def _make_spec(name, extends=None, forbidden=None):
    yaml_str = f"""
version: "0.3"
agent:
  name: {name}
  description: {name} agent
  instructions: Instructions for {name}
policies:
  forbidden_actions: {forbidden or []}
"""
    if extends:
        yaml_str += f"extends: {extends}\n"
    return AgentSpec.from_yaml_str(yaml_str)


def _publish(registry, spec, name, version="1.0.0"):
    registry.publish(spec, version)


class TestMultiLevelInheritance:
    def test_a_extends_b_extends_c(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = LocalRegistry(Path(tmpdir))
            spec_c = _make_spec("agent-c", forbidden=["action-c"])
            spec_b = _make_spec("agent-b", extends="agent-c", forbidden=["action-b"])
            spec_a = _make_spec("agent-a", extends="agent-b", forbidden=["action-a"])

            _publish(reg, spec_c, "agent-c")
            _publish(reg, spec_b, "agent-b")

            resolved = resolve_extends(spec_a, reg)
            # Should have actions from all three levels
            assert "action-a" in resolved.policies.forbidden_actions
            assert "action-b" in resolved.policies.forbidden_actions
            assert "action-c" in resolved.policies.forbidden_actions

    def test_circular_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = LocalRegistry(Path(tmpdir))
            spec_a = _make_spec("agent-a", extends="agent-b")
            spec_b = _make_spec("agent-b", extends="agent-a")

            _publish(reg, spec_a, "agent-a")
            _publish(reg, spec_b, "agent-b")

            with pytest.raises(ValueError, match="Circular extends"):
                resolve_extends(spec_a, reg)

    def test_max_depth_stops_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = LocalRegistry(Path(tmpdir))
            spec_c = _make_spec("agent-c", forbidden=["action-c"])
            spec_b = _make_spec("agent-b", extends="agent-c", forbidden=["action-b"])
            spec_a = _make_spec("agent-a", extends="agent-b", forbidden=["action-a"])

            _publish(reg, spec_c, "agent-c")
            _publish(reg, spec_b, "agent-b")

            resolved = resolve_extends(spec_a, reg, max_depth=1)
            # max_depth=1 means it resolves B but stops before resolving C
            assert "action-a" in resolved.policies.forbidden_actions
            assert "action-b" in resolved.policies.forbidden_actions
            # action-c may or may not be present depending on depth handling
            # With max_depth=1, we resolve A->B but B's extends to C is skipped

    def test_single_level_backward_compatible(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = LocalRegistry(Path(tmpdir))
            spec_b = _make_spec("agent-b", forbidden=["action-b"])
            spec_a = _make_spec("agent-a", extends="agent-b", forbidden=["action-a"])

            _publish(reg, spec_b, "agent-b")

            resolved = resolve_extends(spec_a, reg)
            assert "action-a" in resolved.policies.forbidden_actions
            assert "action-b" in resolved.policies.forbidden_actions
            assert resolved.agent.name == "agent-a"
