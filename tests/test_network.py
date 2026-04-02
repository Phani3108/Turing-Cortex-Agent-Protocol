"""Tests for multi-agent network models, validation, and compilation (Phase 6)."""

import json
import pytest

from cortex_protocol.network.models import NetworkSpec, AgentRef, Route, SharedPolicies
from cortex_protocol.network.graph import (
    validate_network,
    compile_network,
    resolve_agent_specs,
    NetworkValidationResult,
)
from cortex_protocol.network.a2a import (
    generate_a2a_card,
    generate_a2a_card_json,
    generate_a2a_handler,
    generate_network_a2a_cards,
)
from cortex_protocol.models import (
    AgentSpec,
    AgentIdentity,
    ToolSpec,
    PolicySpec,
    ModelConfig,
    AgentMetadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _network_yaml() -> str:
    return """
network:
  name: support-system
  description: Customer support multi-agent network
  agents:
    - spec: triage-agent.yaml
      role: entry
    - spec: billing-agent.yaml
      role: worker
    - spec: escalation-agent.yaml
      role: worker
  routes:
    - from: triage-agent
      to: [billing-agent, escalation-agent]
      condition: "based on intent classification"
    - from: billing-agent
      to: [escalation-agent]
      condition: "when refund > $500"
  shared_tools: [lookup-customer, create-ticket]
  shared_policies:
    max_turns: 30
    forbidden_actions:
      - Access admin data without approval
"""


def _spec(name="test-agent") -> AgentSpec:
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name=name, description=f"Agent {name}", instructions="Test instructions " * 5),
        tools=[ToolSpec(name="search", description="Search the web")],
        policies=PolicySpec(max_turns=10, forbidden_actions=["bad"]),
        model=ModelConfig(preferred="gpt-4o"),
    )


# ---------------------------------------------------------------------------
# NetworkSpec model
# ---------------------------------------------------------------------------

class TestNetworkSpec:
    def test_parse_from_yaml(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        assert network.name == "support-system"
        assert len(network.agents) == 3
        assert len(network.routes) == 2

    def test_agent_names(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        names = network.agent_names()
        assert "triage-agent" in names
        assert "billing-agent" in names
        assert "escalation-agent" in names

    def test_entry_agents(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        entries = network.entry_agents()
        assert len(entries) == 1
        assert entries[0].role == "entry"

    def test_get_routes_from(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        routes = network.get_routes_from("triage-agent")
        assert len(routes) == 1
        assert "billing-agent" in routes[0].to
        assert "escalation-agent" in routes[0].to

    def test_shared_policies(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        assert network.shared_policies.max_turns == 30
        assert len(network.shared_policies.forbidden_actions) == 1

    def test_shared_tools(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        assert "lookup-customer" in network.shared_tools
        assert "create-ticket" in network.shared_tools

    def test_to_yaml_roundtrip(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        yaml_str = network.to_yaml()
        reloaded = NetworkSpec.from_yaml_str(yaml_str)
        assert reloaded.name == network.name
        assert len(reloaded.agents) == len(network.agents)

    def test_minimal_network(self):
        yaml_str = """
network:
  name: minimal
  agents:
    - spec: agent-a.yaml
    - spec: agent-b.yaml
"""
        network = NetworkSpec.from_yaml_str(yaml_str)
        assert network.name == "minimal"
        assert len(network.agents) == 2
        assert network.routes == []

    def test_alias_override(self):
        yaml_str = """
network:
  name: test
  agents:
    - spec: "@org/my-agent@1.0.0"
      alias: my-agent
    - spec: worker.yaml
"""
        network = NetworkSpec.from_yaml_str(yaml_str)
        names = network.agent_names()
        assert "my-agent" in names


# ---------------------------------------------------------------------------
# Network validation
# ---------------------------------------------------------------------------

class TestValidateNetwork:
    def test_valid_network(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        result = validate_network(network)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_too_few_agents(self):
        network = NetworkSpec(
            name="one",
            agents=[AgentRef(spec="a.yaml")],
        )
        result = validate_network(network)
        assert result.valid is False
        assert any("at least 2" in e for e in result.errors)

    def test_no_entry_warning(self):
        network = NetworkSpec(
            name="no-entry",
            agents=[
                AgentRef(spec="a.yaml", role="worker"),
                AgentRef(spec="b.yaml", role="worker"),
            ],
        )
        result = validate_network(network)
        assert any("entry" in w for w in result.warnings)

    def test_route_to_unknown_agent(self):
        network = NetworkSpec(
            name="bad-route",
            agents=[
                AgentRef(spec="a.yaml", role="entry"),
                AgentRef(spec="b.yaml"),
            ],
            routes=[Route(**{"from": "a", "to": ["nonexistent"]})],
        )
        result = validate_network(network)
        assert result.valid is False
        assert any("unknown agent" in e.lower() for e in result.errors)

    def test_self_route_detected(self):
        network = NetworkSpec(
            name="self-route",
            agents=[
                AgentRef(spec="a.yaml", role="entry"),
                AgentRef(spec="b.yaml"),
            ],
            routes=[Route(**{"from": "a", "to": ["a"]})],
        )
        result = validate_network(network)
        assert result.valid is False
        assert any("self-route" in e.lower() for e in result.errors)

    def test_orphan_warning(self):
        network = NetworkSpec(
            name="orphan",
            agents=[
                AgentRef(spec="a.yaml", role="entry"),
                AgentRef(spec="b.yaml"),
                AgentRef(spec="c.yaml"),
            ],
            routes=[Route(**{"from": "a", "to": ["b"]})],
        )
        result = validate_network(network)
        assert any("not referenced" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Network compilation
# ---------------------------------------------------------------------------

class TestCompileNetwork:
    def test_compile_langgraph(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="langgraph")
        assert "StateGraph" in code
        assert "NetworkState" in code
        assert "triage_agent_node" in code
        assert "billing_agent_node" in code

    def test_compile_openai_sdk(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="openai-sdk")
        assert "from agents import Agent" in code
        assert "triage_agent" in code

    def test_compile_system_prompt(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="system-prompt")
        assert "support-system" in code
        assert "triage-agent" in code
        assert "billing-agent" in code

    def test_compile_unknown_target(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="unknown")
        assert "support-system" in code
        assert "Network" in code

    def test_compile_with_agent_specs(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        specs = {
            "triage-agent": _spec("triage-agent"),
            "billing-agent": _spec("billing-agent"),
            "escalation-agent": _spec("escalation-agent"),
        }
        code = compile_network(network, target="langgraph", agent_specs=specs)
        assert "Test instructions" in code

    def test_compile_langgraph_has_max_turns(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="langgraph")
        assert "30" in code  # max_turns from shared_policies

    def test_compile_openai_has_handoffs(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        code = compile_network(network, target="openai-sdk")
        assert "handoffs" in code


# ---------------------------------------------------------------------------
# resolve_agent_specs
# ---------------------------------------------------------------------------

class TestResolveAgentSpecs:
    def test_resolve_from_files(self, tmp_path):
        # Create agent YAML files
        spec_a = _spec("agent-a")
        (tmp_path / "agent-a.yaml").write_text(spec_a.to_yaml())

        network = NetworkSpec(
            name="test",
            agents=[
                AgentRef(spec="agent-a.yaml", role="entry"),
                AgentRef(spec="agent-b.yaml"),
            ],
        )
        specs = resolve_agent_specs(network, base_dir=tmp_path)
        assert specs["agent-a"] is not None
        assert specs["agent-b"] is None  # file doesn't exist

    def test_resolve_registry_ref(self, tmp_path):
        network = NetworkSpec(
            name="test",
            agents=[
                AgentRef(spec="@org/my-agent@1.0.0", alias="my-agent"),
                AgentRef(spec="local.yaml"),
            ],
        )
        specs = resolve_agent_specs(network, base_dir=tmp_path)
        assert specs["my-agent"] is None  # registry refs not resolved yet


# ---------------------------------------------------------------------------
# A2A agent card generation
# ---------------------------------------------------------------------------

class TestA2ACard:
    def test_basic_card(self):
        spec = _spec("support-agent")
        card = generate_a2a_card(spec)
        assert card["name"] == "support-agent"
        assert len(card["skills"]) == 1
        assert card["skills"][0]["id"] == "search"

    def test_card_with_metadata(self):
        spec = AgentSpec(
            version="0.1",
            agent=AgentIdentity(name="pay-agent", description="Payments", instructions="Handle payments " * 5),
            tools=[ToolSpec(name="charge", description="Charge card")],
            metadata=AgentMetadata(owner="team-pay", tags=["payment"], compliance=["pci-dss"]),
        )
        card = generate_a2a_card(spec)
        assert "extensions" in card
        assert card["extensions"]["cortex_protocol"]["owner"] == "team-pay"

    def test_card_with_mcp_tool(self):
        spec = AgentSpec(
            version="0.1",
            agent=AgentIdentity(name="dev-agent", description="Dev", instructions="Dev work " * 5),
            tools=[ToolSpec(name="github", description="GitHub", mcp="mcp-server-github@1.0.0")],
        )
        card = generate_a2a_card(spec)
        assert "mcp" in card["skills"][0]["tags"]
        assert card["skills"][0]["extensions"]["mcp_server"] == "mcp-server-github@1.0.0"

    def test_card_json(self):
        spec = _spec()
        json_str = generate_a2a_card_json(spec)
        parsed = json.loads(json_str)
        assert parsed["name"] == "test-agent"

    def test_card_url(self):
        spec = _spec()
        card = generate_a2a_card(spec, url="https://my-agent.example.com")
        assert card["url"] == "https://my-agent.example.com"

    def test_card_version(self):
        spec = _spec()
        card = generate_a2a_card(spec, version="2.0.0")
        assert card["version"] == "2.0.0"

    def test_card_capabilities(self):
        spec = _spec()
        card = generate_a2a_card(spec)
        assert "capabilities" in card
        assert card["capabilities"]["stateTransitionHistory"] is True


# ---------------------------------------------------------------------------
# A2A handler generation
# ---------------------------------------------------------------------------

class TestA2AHandler:
    def test_fastapi_handler(self):
        spec = _spec("support-agent")
        code = generate_a2a_handler(spec, framework="fastapi")
        assert "from fastapi import" in code
        assert "/.well-known/agent.json" in code
        assert "/a2a" in code
        assert "tasks/send" in code
        assert "tasks/get" in code
        assert "tasks/cancel" in code

    def test_flask_handler(self):
        spec = _spec("support-agent")
        code = generate_a2a_handler(spec, framework="flask")
        assert "from flask import" in code
        assert "/.well-known/agent.json" in code
        assert "/a2a" in code

    def test_handler_has_agent_card(self):
        spec = _spec("my-agent")
        code = generate_a2a_handler(spec)
        assert "AGENT_CARD" in code
        assert "my-agent" in code

    def test_handler_has_task_store(self):
        spec = _spec()
        code = generate_a2a_handler(spec)
        assert "tasks:" in code or "tasks =" in code

    def test_handler_has_entry_point(self):
        spec = _spec()
        code = generate_a2a_handler(spec)
        assert 'if __name__ == "__main__"' in code


# ---------------------------------------------------------------------------
# Network-level A2A cards
# ---------------------------------------------------------------------------

class TestNetworkA2ACards:
    def test_generates_cards_for_all_agents(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        cards = generate_network_a2a_cards(network)
        assert len(cards) == 3
        assert "triage-agent" in cards
        assert "billing-agent" in cards

    def test_unique_ports(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        cards = generate_network_a2a_cards(network, base_port=9000)
        urls = [card["url"] for card in cards.values()]
        assert len(set(urls)) == 3  # all unique

    def test_peers_in_extensions(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        cards = generate_network_a2a_cards(network)
        triage_card = cards["triage-agent"]
        assert "extensions" in triage_card
        assert "a2a_peers" in triage_card["extensions"]
        peer_names = [p["name"] for p in triage_card["extensions"]["a2a_peers"]]
        assert "billing-agent" in peer_names

    def test_with_resolved_specs(self):
        network = NetworkSpec.from_yaml_str(_network_yaml())
        specs = {"triage-agent": _spec("triage-agent")}
        cards = generate_network_a2a_cards(network, agent_specs=specs)
        assert cards["triage-agent"]["skills"]  # has skills from spec
        assert not cards["billing-agent"]["skills"]  # no spec = no skills
