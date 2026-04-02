"""Tests for the versioned local registry."""

import json
import pytest

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, PolicySpec,
    EscalationPolicy, ModelConfig, ToolParameter, AgentMetadata,
)
from cortex_protocol.registry.local import LocalRegistry, _parse_semver


def _spec(name="test-agent", tags=None, owner="", compliance=None):
    metadata = None
    if tags or owner or compliance:
        metadata = AgentMetadata(
            owner=owner,
            tags=tags or [],
            compliance=compliance or [],
        )
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name=name, description=f"Agent {name}", instructions="Test " * 10),
        tools=[ToolSpec(name="search", description="Search")],
        policies=PolicySpec(max_turns=10, forbidden_actions=["bad"]),
        model=ModelConfig(preferred="gpt-4o"),
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# semver parsing
# ---------------------------------------------------------------------------

class TestSemver:
    def test_valid(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_zero(self):
        assert _parse_semver("0.0.0") == (0, 0, 0)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_semver("not-a-version")

    def test_incomplete_raises(self):
        with pytest.raises(ValueError):
            _parse_semver("1.2")


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------

class TestPublish:
    def test_publish_creates_files(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        spec = _spec()
        path = reg.publish(spec, "1.0.0")
        assert path.exists()
        assert "1.0.0.yaml" in path.name

    def test_publish_creates_meta(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        meta = reg.get_meta("test-agent")
        assert meta is not None
        assert meta.latest == "1.0.0"
        assert len(meta.versions) == 1

    def test_publish_multiple_versions(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "1.1.0")
        reg.publish(_spec(), "2.0.0")
        assert reg.list_versions("test-agent") == ["1.0.0", "1.1.0", "2.0.0"]
        assert reg.get_meta("test-agent").latest == "2.0.0"

    def test_duplicate_version_raises(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        with pytest.raises(ValueError, match="already exists"):
            reg.publish(_spec(), "1.0.0")

    def test_lower_version_raises(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "2.0.0")
        with pytest.raises(ValueError, match="must be greater"):
            reg.publish(_spec(), "1.0.0")

    def test_invalid_semver_raises(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        with pytest.raises(ValueError, match="Invalid semver"):
            reg.publish(_spec(), "not-valid")


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_specific_version(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "2.0.0")
        spec = reg.get("test-agent", "1.0.0")
        assert spec is not None
        assert spec.agent.name == "test-agent"

    def test_get_latest(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "1.1.0")
        spec = reg.get_latest("test-agent")
        assert spec is not None

    def test_get_nonexistent_returns_none(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert reg.get("nope", "1.0.0") is None

    def test_get_latest_nonexistent_returns_none(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert reg.get_latest("nope") is None


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    def test_list_empty(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert reg.list_agents() == []

    def test_list_agents(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("alpha"), "1.0.0")
        reg.publish(_spec("beta"), "1.0.0")
        agents = reg.list_agents()
        names = [a.name for a in agents]
        assert "alpha" in names
        assert "beta" in names

    def test_list_versions(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        reg.publish(_spec(), "1.1.0")
        assert reg.list_versions("test-agent") == ["1.0.0", "1.1.0"]

    def test_list_versions_empty(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert reg.list_versions("nope") == []


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_by_tag(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("pay-agent", tags=["payment", "pii"]), "1.0.0")
        reg.publish(_spec("search-agent", tags=["search"]), "1.0.0")
        results = reg.search(tags=["payment"])
        assert len(results) == 1
        assert results[0][0].name == "pay-agent"

    def test_search_by_compliance(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("hipaa-agent", compliance=["hipaa"]), "1.0.0")
        reg.publish(_spec("plain-agent"), "1.0.0")
        results = reg.search(compliance=["hipaa"])
        assert len(results) == 1

    def test_search_by_owner(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("a", owner="team-a"), "1.0.0")
        reg.publish(_spec("b", owner="team-b"), "1.0.0")
        results = reg.search(owner="team-a")
        assert len(results) == 1
        assert results[0][0].name == "a"

    def test_search_by_name(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("incident-commander"), "1.0.0")
        reg.publish(_spec("support-agent"), "1.0.0")
        results = reg.search(name_contains="incident")
        assert len(results) == 1

    def test_search_multiple_criteria(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("a", tags=["payment"], owner="team-x"), "1.0.0")
        reg.publish(_spec("b", tags=["payment"], owner="team-y"), "1.0.0")
        results = reg.search(tags=["payment"], owner="team-x")
        assert len(results) == 1
        assert results[0][0].name == "a"

    def test_search_no_results(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec("a"), "1.0.0")
        results = reg.search(tags=["nonexistent"])
        assert len(results) == 0


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_agent(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        reg.publish(_spec(), "1.0.0")
        assert reg.delete_agent("test-agent")
        assert reg.get_latest("test-agent") is None

    def test_delete_nonexistent(self, tmp_path):
        reg = LocalRegistry(tmp_path)
        assert not reg.delete_agent("nope")
