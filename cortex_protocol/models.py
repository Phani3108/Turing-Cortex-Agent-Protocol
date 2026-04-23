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
    from_template: Optional[str | list[str]] = None
    # v0.3+: cost governance. All optional; enforcement is skipped when unset.
    max_cost_usd: float | None = None
    max_tokens_per_run: int | None = None
    max_tool_calls_per_run: int | None = None
    cost_breakdown_required: bool = False
    # v0.6+: policy-as-code DSL rules. First-match wins; evaluated after
    # budget checks and before the static require_approval list.
    rules: list[dict] = Field(default_factory=list)


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


def merge_specs(base: "AgentSpec", override: "AgentSpec") -> "AgentSpec":
    """Merge two specs: override wins on conflicts, lists are combined."""
    # Instructions: concatenate
    if base.agent.instructions and override.agent.instructions:
        merged_instructions = base.agent.instructions + "\n\n" + override.agent.instructions
    else:
        merged_instructions = override.agent.instructions or base.agent.instructions

    merged_agent = AgentIdentity(
        name=override.agent.name,
        description=override.agent.description,
        instructions=merged_instructions,
    )

    # Tools: base + override, override wins on name conflict
    base_tools_by_name = {t.name: t for t in base.tools}
    override_tools_by_name = {t.name: t for t in override.tools}
    merged_tools_dict = {**base_tools_by_name, **override_tools_by_name}
    merged_tools = list(merged_tools_dict.values())

    # Policies: override wins field by field, lists merged
    base_p = base.policies
    over_p = override.policies
    merged_policies = PolicySpec(
        max_turns=over_p.max_turns if over_p.max_turns is not None else base_p.max_turns,
        require_approval=list(set(base_p.require_approval) | set(over_p.require_approval)),
        forbidden_actions=list(set(base_p.forbidden_actions) | set(over_p.forbidden_actions)),
        escalation=over_p.escalation if over_p.escalation.trigger else base_p.escalation,
        max_cost_usd=(
            over_p.max_cost_usd if over_p.max_cost_usd is not None else base_p.max_cost_usd
        ),
        max_tokens_per_run=(
            over_p.max_tokens_per_run if over_p.max_tokens_per_run is not None else base_p.max_tokens_per_run
        ),
        max_tool_calls_per_run=(
            over_p.max_tool_calls_per_run if over_p.max_tool_calls_per_run is not None else base_p.max_tool_calls_per_run
        ),
        cost_breakdown_required=over_p.cost_breakdown_required or base_p.cost_breakdown_required,
        rules=list(base_p.rules) + list(over_p.rules),
    )

    return AgentSpec(
        version=override.version,
        agent=merged_agent,
        tools=merged_tools,
        policies=merged_policies,
        model=override.model,
        metadata=override.metadata or base.metadata,
        extends=None,
    )
