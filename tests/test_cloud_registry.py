"""Tests for CloudRegistry and the push/pull CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.cloud.client import CloudAuthError, CloudClient, CloudHTTPError
from cortex_protocol.cloud.registry import CloudRegistry, CloudRegistryError
from cortex_protocol.licensing import (
    Tier,
    downgrade_to_standard_for_tests,
    grant_for_tests,
    set_entitlements,
)
from cortex_protocol.models import (
    AgentIdentity,
    AgentMetadata,
    AgentSpec,
    ModelConfig,
    PolicySpec,
    ToolSpec,
    ToolParameter,
)


def _spec(name="reg-test") -> AgentSpec:
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(
            name=name,
            description="A test spec for the cloud registry",
            instructions="You are the test agent. Cite sources. Escalate when unsure.",
        ),
        tools=[ToolSpec(name="search", description="Search",
                         parameters=ToolParameter(type="object"))],
        policies=PolicySpec(max_turns=5),
        model=ModelConfig(preferred="claude-sonnet-4"),
        metadata=AgentMetadata(owner="ops", tags=["payment"], compliance=["soc2"]),
    )


class _Transport:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.routes: dict[tuple[str, str], tuple[int, dict, object]] = {}

    def __call__(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.calls.append((method, url, body))
        # Match by method + URL suffix.
        for (m, suffix), response in self.routes.items():
            if m == method and url.endswith(suffix):
                return response
        return (404, {}, {"error": "not_found", "suffix_looked_for": url})


@pytest.fixture(autouse=True)
def _entitlements():
    grant_for_tests(tier=Tier.PRO)
    yield
    set_entitlements(None)


@pytest.fixture
def client_and_transport():
    transport = _Transport()
    client = CloudClient(base_url="https://cloud.example", token="tok", http=transport)
    return client, transport


class TestCloudRegistry:
    def test_requires_workspace(self, client_and_transport):
        client, _ = client_and_transport
        with pytest.raises(CloudRegistryError):
            CloudRegistry(client, workspace="")

    def test_publish_sends_expected_payload(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("POST", "/v1/registry/ws1/agents/reg-test/versions")] = (
            200, {}, {"url": "https://cloud.example/ws1/reg-test@1.0.0"}
        )
        reg = CloudRegistry(client, workspace="ws1")
        url = reg.publish(_spec(), "1.0.0")
        assert url.endswith("1.0.0")
        # One POST recorded with version + spec_yaml + metadata.
        post = [c for c in transport.calls if c[0] == "POST"][-1]
        body = post[2]
        assert body["version"] == "1.0.0"
        assert "reg-test" in body["spec_yaml"]
        assert body["metadata"]["tags"] == ["payment"]
        assert body["metadata"]["compliance"] == ["soc2"]

    def test_publish_anonymous_raises(self):
        transport = _Transport()
        # Force-unauthenticated client.
        import os
        os.environ.pop("CORTEX_CLOUD_TOKEN", None)
        client = CloudClient(base_url="https://x", token=None, http=transport)
        reg = CloudRegistry(client, workspace="ws")
        with pytest.raises(CloudAuthError):
            reg.publish(_spec(), "1.0.0")

    def test_publish_conflict_409(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("POST", "/v1/registry/ws/agents/reg-test/versions")] = (
            409, {}, {"error": "conflict"}
        )
        reg = CloudRegistry(client, workspace="ws")
        with pytest.raises(CloudRegistryError):
            reg.publish(_spec(), "1.0.0")

    def test_get_returns_spec(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "/v1/registry/ws/agents/reg-test/versions/1.0.0")] = (
            200, {}, {"spec_yaml": _spec().to_yaml()}
        )
        reg = CloudRegistry(client, workspace="ws")
        spec = reg.get("reg-test", "1.0.0")
        assert spec is not None
        assert spec.agent.name == "reg-test"

    def test_get_missing_returns_none(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "/v1/registry/ws/agents/reg-test/versions/9.9.9")] = (
            404, {}, {}
        )
        reg = CloudRegistry(client, workspace="ws")
        assert reg.get("reg-test", "9.9.9") is None

    def test_get_latest(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "/v1/registry/ws/agents/reg-test/latest")] = (
            200, {}, {"spec_yaml": _spec().to_yaml()}
        )
        reg = CloudRegistry(client, workspace="ws")
        spec = reg.get_latest("reg-test")
        assert spec and spec.agent.name == "reg-test"

    def test_list_agents(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "/v1/registry/ws/agents")] = (
            200, {}, {"agents": [
                {"name": "a", "latest": "1.0.0",
                 "versions": [{"version": "1.0.0", "published_at": "", "spec_file": ""}]},
            ]}
        )
        reg = CloudRegistry(client, workspace="ws")
        rows = reg.list_agents()
        assert len(rows) == 1 and rows[0].name == "a"

    def test_search_builds_query(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "ws/agents?tag=payment&compliance=soc2")] = (
            200, {}, {"agents": [
                {"name": "p", "latest": "1.0.0",
                 "versions": [{"version": "1.0.0", "published_at": "", "spec_file": ""}],
                 "latest_spec_yaml": _spec("p").to_yaml()},
            ]}
        )
        reg = CloudRegistry(client, workspace="ws")
        results = reg.search(tags=["payment"], compliance=["soc2"])
        assert len(results) == 1
        meta, spec = results[0]
        assert meta.name == "p" and spec.agent.name == "p"

    def test_list_versions_missing(self, client_and_transport):
        client, transport = client_and_transport
        transport.routes[("GET", "/v1/registry/ws/agents/nope/versions")] = (404, {}, {})
        reg = CloudRegistry(client, workspace="ws")
        assert reg.list_versions("nope") == []


class TestPushPullCLI:
    def test_push_on_standard_is_blocked(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        set_entitlements(None)
        downgrade_to_standard_for_tests()
        spec_path = tmp_path / "agent.yaml"
        spec_path.write_text(_spec().to_yaml())
        runner = CliRunner()
        result = runner.invoke(main, [
            "push", str(spec_path), "--version", "1.0.0",
            "--workspace", "ws",
        ])
        assert result.exit_code != 0
        assert "Pro tier" in result.output

    def test_push_on_pro_calls_backend(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        import cortex_protocol.cloud.client as cmod

        grant_for_tests(tier=Tier.PRO)
        monkeypatch.setenv("CORTEX_CLOUD_TOKEN", "t")
        monkeypatch.setenv("CORTEX_CLOUD_WORKSPACE", "ws")

        # Patch the transport used by anonymous constructors (CLI path).
        def fake(method, url, **kw):
            if method == "POST" and "reg-test/versions" in url:
                return (200, {}, {"url": "https://cloud.example/ws/reg-test@1.0.0"})
            return (404, {}, {})
        monkeypatch.setattr(cmod, "_request", fake)

        spec_path = tmp_path / "agent.yaml"
        spec_path.write_text(_spec().to_yaml())
        runner = CliRunner()
        result = runner.invoke(main, [
            "push", str(spec_path), "--version", "1.0.0",
        ])
        assert result.exit_code == 0, result.output
        assert "Published" in result.output

    def test_pull_writes_spec(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        import cortex_protocol.cloud.client as cmod

        grant_for_tests(tier=Tier.PRO)
        monkeypatch.setenv("CORTEX_CLOUD_TOKEN", "t")
        monkeypatch.setenv("CORTEX_CLOUD_WORKSPACE", "ws")

        spec_yaml = _spec("pulled").to_yaml()

        def fake(method, url, **kw):
            if method == "GET" and url.endswith("/agents/pulled/latest"):
                return (200, {}, {"spec_yaml": spec_yaml})
            return (404, {}, {})
        monkeypatch.setattr(cmod, "_request", fake)

        out = tmp_path / "pulled.yaml"
        runner = CliRunner()
        result = runner.invoke(main, ["pull", "pulled", "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert out.exists()
        assert "pulled" in out.read_text()
