"""Pydantic models for multi-agent network specifications.

A NetworkSpec defines a graph of agents that can communicate with each other,
with shared tools, shared policies, and explicit routing rules.

Example::

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
      shared_tools: [lookup-customer, create-ticket]
      shared_policies:
        max_turns: 30
        forbidden_actions:
          - Access admin data without approval
"""

from __future__ import annotations

from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


class AgentRef(BaseModel):
    """Reference to an agent within the network."""

    spec: str  # path to YAML spec or registry reference
    role: str = "worker"  # entry | worker | escalation
    alias: str = ""  # optional short name override


class Route(BaseModel):
    """Routing rule between agents in the network."""

    from_agent: str = Field(alias="from")
    to: list[str]
    condition: str = ""
    priority: int = 0

    model_config = {"populate_by_name": True}


class SharedPolicies(BaseModel):
    """Policies that apply across the entire network."""

    max_turns: int | None = None
    forbidden_actions: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)


class NetworkSpec(BaseModel):
    """Root specification for a multi-agent network."""

    version: str = "0.1"
    name: str
    description: str = ""
    agents: list[AgentRef]
    routes: list[Route] = Field(default_factory=list)
    shared_tools: list[str] = Field(default_factory=list)
    shared_policies: SharedPolicies = Field(default_factory=SharedPolicies)

    @classmethod
    def from_yaml(cls, path: str) -> NetworkSpec:
        with open(path) as f:
            data = yaml.safe_load(f)
        # Support both top-level and nested under "network:" key
        if "network" in data and isinstance(data["network"], dict):
            data = data["network"]
        return cls.model_validate(data)

    @classmethod
    def from_yaml_str(cls, text: str) -> NetworkSpec:
        data = yaml.safe_load(text)
        if "network" in data and isinstance(data["network"], dict):
            data = data["network"]
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.dump(
            {"network": self.model_dump(exclude_none=True, by_alias=True)},
            default_flow_style=False,
            sort_keys=False,
        )

    def agent_names(self) -> list[str]:
        """Extract agent names from spec paths (filename without extension)."""
        names = []
        for agent in self.agents:
            name = agent.alias or agent.spec.replace(".yaml", "").replace(".yml", "")
            # Handle registry refs like @org/agent-name@1.0
            if "/" in name:
                name = name.split("/")[-1]
            if "@" in name:
                name = name.split("@")[0]
            names.append(name)
        return names

    def entry_agents(self) -> list[AgentRef]:
        """Return agents with role='entry'."""
        return [a for a in self.agents if a.role == "entry"]

    def get_routes_from(self, agent_name: str) -> list[Route]:
        """Return all routes originating from a given agent."""
        return [r for r in self.routes if r.from_agent == agent_name]
