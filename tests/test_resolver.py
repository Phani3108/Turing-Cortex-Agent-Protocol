"""Tests for version resolution and semver matching."""

import pytest

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, PolicySpec, ModelConfig,
)
from cortex_protocol.registry.local import LocalRegistry
from cortex_protocol.registry.resolver import version_matches, resolve_version


# ---------------------------------------------------------------------------
# version_matches
# ---------------------------------------------------------------------------

class TestVersionMatches:
    # exact
    def test_exact_match(self):
        assert version_matches("1.2.3", "1.2.3")

    def test_exact_no_match(self):
        assert not version_matches("1.2.4", "1.2.3")

    # caret ^
    def test_caret_same(self):
        assert version_matches("1.2.3", "^1.2.3")

    def test_caret_higher_minor(self):
        assert version_matches("1.5.0", "^1.2.3")

    def test_caret_higher_patch(self):
        assert version_matches("1.2.9", "^1.2.3")

    def test_caret_next_major_fails(self):
        assert not version_matches("2.0.0", "^1.2.3")

    def test_caret_lower_fails(self):
        assert not version_matches("1.2.2", "^1.2.3")

    def test_caret_zero_major(self):
        assert version_matches("0.2.5", "^0.2.3")
        assert not version_matches("0.3.0", "^0.2.3")

    # tilde ~
    def test_tilde_same(self):
        assert version_matches("1.2.3", "~1.2.3")

    def test_tilde_higher_patch(self):
        assert version_matches("1.2.9", "~1.2.3")

    def test_tilde_next_minor_fails(self):
        assert not version_matches("1.3.0", "~1.2.3")

    def test_tilde_lower_fails(self):
        assert not version_matches("1.2.2", "~1.2.3")

    # >=
    def test_gte(self):
        assert version_matches("1.2.3", ">=1.2.3")
        assert version_matches("2.0.0", ">=1.2.3")
        assert not version_matches("1.2.2", ">=1.2.3")


# ---------------------------------------------------------------------------
# resolve_version
# ---------------------------------------------------------------------------

def _spec(name="test-agent"):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name=name, description="Test", instructions="Test " * 10),
        tools=[ToolSpec(name="search", description="Search")],
        policies=PolicySpec(max_turns=10, forbidden_actions=["bad"]),
        model=ModelConfig(preferred="gpt-4o"),
    )


class TestResolveVersion:
    def test_latest(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "1.1.0")
        assert resolve_version(reg, "test-agent", "latest") == "1.1.0"

    def test_exact(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "2.0.0")
        assert resolve_version(reg, "test-agent", "1.0.0") == "1.0.0"

    def test_caret_resolves_highest(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "1.2.0")
        reg.publish(_spec(), "1.5.0")
        reg.publish(_spec(), "2.0.0")
        assert resolve_version(reg, "test-agent", "^1.0.0") == "1.5.0"

    def test_tilde_resolves_highest_patch(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.2.0")
        reg.publish(_spec(), "1.2.5")
        reg.publish(_spec(), "1.3.0")
        assert resolve_version(reg, "test-agent", "~1.2.0") == "1.2.5"

    def test_no_match_returns_none(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        assert resolve_version(reg, "test-agent", "^2.0.0") is None

    def test_nonexistent_agent(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert resolve_version(reg, "nope", "latest") is None


# ---------------------------------------------------------------------------
# Schema v0.3: metadata + mcp fields
# ---------------------------------------------------------------------------

class TestSchemaV03:
    def test_metadata_round_trip(self):
        spec = AgentSpec(
            version="0.1",
            agent=AgentIdentity(name="a", description="d", instructions="i " * 10),
            metadata={"owner": "team-x", "tags": ["payment"], "compliance": ["pci-dss"]},
        )
        yaml_str = spec.to_yaml()
        loaded = AgentSpec.from_yaml_str(yaml_str)
        assert loaded.metadata.owner == "team-x"
        assert "payment" in loaded.metadata.tags
        assert "pci-dss" in loaded.metadata.compliance

    def test_mcp_on_tool(self):
        spec = AgentSpec(
            version="0.1",
            agent=AgentIdentity(name="a", description="d", instructions="i " * 10),
            tools=[ToolSpec(name="jira", description="Jira", mcp="mcp-server-atlassian@2.1.0")],
        )
        yaml_str = spec.to_yaml()
        loaded = AgentSpec.from_yaml_str(yaml_str)
        assert loaded.tools[0].mcp == "mcp-server-atlassian@2.1.0"

    def test_extends_field(self):
        spec = AgentSpec(
            version="0.1",
            agent=AgentIdentity(name="a", description="d", instructions="i " * 10),
            extends="@org/base-agent@^2.0",
        )
        yaml_str = spec.to_yaml()
        loaded = AgentSpec.from_yaml_str(yaml_str)
        assert loaded.extends == "@org/base-agent@^2.0"

    def test_backward_compat_no_metadata(self):
        """v0.1 specs without metadata still parse fine."""
        yaml_str = """
version: "0.1"
agent:
  name: old-agent
  description: Old agent
  instructions: This is a basic agent.
tools: []
"""
        spec = AgentSpec.from_yaml_str(yaml_str)
        assert spec.metadata is None
        assert spec.extends is None

    def test_backward_compat_no_mcp(self):
        yaml_str = """
version: "0.1"
agent:
  name: old-agent
  description: Old agent
  instructions: Basic instructions here.
tools:
  - name: search
    description: Search
"""
        spec = AgentSpec.from_yaml_str(yaml_str)
        assert spec.tools[0].mcp is None
