"""Pydantic models for Cortex Protocol agent specification (v0.1 + v0.3 extensions)."""

from __future__ import annotations

import json
from typing import Any, Optional

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
    mcp: Optional[str] = None  # v0.3: MCP server reference, e.g. "mcp-server-atlassian@2.1.0"


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


class AgentMetadata(BaseModel):
    """Queryable metadata for registry discovery (v0.3)."""

    owner: str = ""
    tags: list[str] = Field(default_factory=list)
    compliance: list[str] = Field(default_factory=list)
    environment: str = ""


class AgentSpec(BaseModel):
    """Root specification for a Cortex Protocol agent."""

    version: str = "0.1"
    agent: AgentIdentity
    tools: list[ToolSpec] = Field(default_factory=list)
    policies: PolicySpec = Field(default_factory=PolicySpec)
    model: ModelConfig = Field(default_factory=ModelConfig)
    metadata: Optional[AgentMetadata] = None  # v0.3
    extends: Optional[str] = None  # v0.3: base spec reference, e.g. "@org/base-agent@^2.0"

    @classmethod
    def from_yaml(cls, path: str) -> AgentSpec:
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_yaml_str(cls, text: str) -> AgentSpec:
        data = yaml.safe_load(text)
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        return yaml.dump(
            self.model_dump(exclude_none=True),
            default_flow_style=False,
            sort_keys=False,
        )

    def to_json_schema(self) -> str:
        return json.dumps(self.model_json_schema(), indent=2)
