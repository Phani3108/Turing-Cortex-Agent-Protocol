"""Pydantic models for Cortex Protocol v0.1 agent specification."""

from __future__ import annotations

import json
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """JSON Schema fragment describing a tool's input parameters."""

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolSpec(BaseModel):
    """A tool the agent can invoke."""

    name: str
    description: str
    parameters: ToolParameter = Field(default_factory=ToolParameter)


class EscalationPolicy(BaseModel):
    """When and where to escalate."""

    trigger: str = ""
    target: str = ""


class PolicySpec(BaseModel):
    """Governance rules that travel with the agent."""

    max_turns: int | None = None
    require_approval: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    escalation: EscalationPolicy = Field(default_factory=EscalationPolicy)


class ModelConfig(BaseModel):
    """Advisory model preferences."""

    preferred: str = "claude-sonnet-4"
    fallback: str | None = None
    temperature: float = 0.7


class AgentIdentity(BaseModel):
    """Core agent identity."""

    name: str
    description: str
    instructions: str


class AgentSpec(BaseModel):
    """Root specification for a Cortex Protocol agent."""

    version: str = "0.1"
    agent: AgentIdentity
    tools: list[ToolSpec] = Field(default_factory=list)
    policies: PolicySpec = Field(default_factory=PolicySpec)
    model: ModelConfig = Field(default_factory=ModelConfig)

    @classmethod
    def from_yaml(cls, path: str) -> AgentSpec:
        """Load an agent spec from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_yaml_str(cls, text: str) -> AgentSpec:
        """Load an agent spec from a YAML string."""
        data = yaml.safe_load(text)
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        """Serialize the spec to YAML."""
        return yaml.dump(
            self.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

    def to_json_schema(self) -> str:
        """Export the JSON Schema for validation."""
        return json.dumps(cls.model_json_schema(), indent=2)
