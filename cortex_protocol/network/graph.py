"""Multi-agent network validation and compilation.

Takes a NetworkSpec, resolves each agent's spec, validates the graph
(no orphans, valid routes, entry point exists), and compiles a
multi-agent orchestration scaffold for the chosen target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import AgentSpec
from .models import NetworkSpec


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class NetworkValidationResult:
    """Result of validating a network spec."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.valid = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_network(network: NetworkSpec) -> NetworkValidationResult:
    """Validate a network spec for structural correctness.

    Checks:
        - At least 2 agents
        - At least one entry agent
        - Route references are valid agent names
        - No orphaned agents (agents with no routes to/from)
        - No self-routes
    """
    result = NetworkValidationResult()
    names = set(network.agent_names())

    # Must have at least 2 agents
    if len(network.agents) < 2:
        result.add_error("Network must have at least 2 agents")

    # Must have entry agent
    entries = network.entry_agents()
    if not entries:
        result.add_warning("No agent with role='entry' — first agent will be used as entry")

    # Validate routes
    routed_agents: set[str] = set()
    for route in network.routes:
        from_name = route.from_agent
        if from_name not in names:
            result.add_error(f"Route from unknown agent: '{from_name}'")
        else:
            routed_agents.add(from_name)

        for to_name in route.to:
            if to_name not in names:
                result.add_error(f"Route to unknown agent: '{to_name}'")
            else:
                routed_agents.add(to_name)

            if from_name == to_name:
                result.add_error(f"Self-route detected: '{from_name}' -> '{to_name}'")

    # Orphan check (warning, not error — standalone agents are OK)
    if network.routes:
        orphans = names - routed_agents
        for orphan in orphans:
            result.add_warning(f"Agent '{orphan}' is not referenced in any route")

    return result


# ---------------------------------------------------------------------------
# Agent spec resolution
# ---------------------------------------------------------------------------

def resolve_agent_specs(
    network: NetworkSpec,
    base_dir: Path | None = None,
) -> dict[str, AgentSpec | None]:
    """Resolve each agent reference to an AgentSpec.

    For file paths, loads from disk relative to base_dir.
    For registry references (@org/name@version), returns None (not yet implemented).

    Returns dict of {agent_name: AgentSpec or None}.
    """
    base = base_dir or Path(".")
    specs: dict[str, AgentSpec | None] = {}
    agent_names = network.agent_names()

    for agent_ref, name in zip(network.agents, agent_names):
        spec_path = agent_ref.spec

        # Registry reference — not yet resolved
        if spec_path.startswith("@"):
            specs[name] = None
            continue

        # File path
        full_path = base / spec_path
        if full_path.exists():
            try:
                specs[name] = AgentSpec.from_yaml(str(full_path))
            except Exception:
                specs[name] = None
        else:
            specs[name] = None

    return specs


# ---------------------------------------------------------------------------
# Network compilation
# ---------------------------------------------------------------------------

def compile_network(
    network: NetworkSpec,
    target: str = "langgraph",
    agent_specs: dict[str, AgentSpec] | None = None,
) -> str:
    """Compile a network spec into a multi-agent orchestration scaffold.

    Currently supports: langgraph, openai-sdk, system-prompt.
    Returns generated Python code as a string.
    """
    if target == "langgraph":
        return _compile_langgraph(network, agent_specs)
    elif target == "openai-sdk":
        return _compile_openai(network, agent_specs)
    elif target == "system-prompt":
        return _compile_system_prompt(network)
    else:
        return _compile_generic(network, target)


def _compile_langgraph(network: NetworkSpec, specs: dict | None) -> str:
    """Generate a LangGraph multi-agent StateGraph."""
    names = network.agent_names()
    lines: list[str] = []

    lines.append(f'"""Multi-agent network: {network.name}')
    lines.append(f'{network.description}')
    lines.append(f'Generated by Cortex Protocol — do not edit directly."""')
    lines.append("")
    lines.append("from typing import Annotated, TypedDict, Literal")
    lines.append("")
    lines.append("from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage")
    lines.append("from langchain_openai import ChatOpenAI")
    lines.append("from langgraph.graph import StateGraph, START, END")
    lines.append("from langgraph.graph.message import add_messages")
    lines.append("")
    lines.append("")
    lines.append("# ── State ────────────────────────────────────────────────────────────")
    lines.append("")
    lines.append("class NetworkState(TypedDict):")
    lines.append("    messages: Annotated[list[AnyMessage], add_messages]")
    lines.append('    current_agent: str')
    lines.append('    turn_count: int')
    lines.append("")
    lines.append("")

    # Agent node factories
    lines.append("# ── Agent Nodes ──────────────────────────────────────────────────────")
    lines.append("")

    for name in names:
        snake = _to_snake(name)
        lines.append(f"def {snake}_node(state: NetworkState) -> NetworkState:")
        lines.append(f'    """Agent node: {name}"""')
        lines.append(f'    llm = ChatOpenAI(model="gpt-4o")')

        # Check if we have a resolved spec with instructions
        if specs and name in specs and specs[name]:
            spec = specs[name]
            instructions = spec.agent.instructions.strip().replace('"""', '\\"\\"\\"')
            lines.append(f'    system = """{instructions}"""')
        else:
            lines.append(f'    system = "You are {name}."')

        lines.append(f'    messages = [SystemMessage(content=system)] + state["messages"]')
        lines.append(f"    response = llm.invoke(messages)")
        lines.append(f'    return {{"messages": [response], "current_agent": "{name}", "turn_count": state.get("turn_count", 0) + 1}}')
        lines.append("")
        lines.append("")

    # Router function
    lines.append("# ── Router ────────────────────────────────────────────────────────────")
    lines.append("")

    entry_name = names[0]
    entries = network.entry_agents()
    if entries:
        entry_name = entries[0].alias or entries[0].spec.replace(".yaml", "").replace(".yml", "")

    # Build routing logic
    lines.append("def route_agent(state: NetworkState) -> str:")
    lines.append('    """Route to next agent based on network routes."""')

    max_turns = network.shared_policies.max_turns
    if max_turns:
        lines.append(f'    if state.get("turn_count", 0) >= {max_turns}:')
        lines.append(f'        return END')

    lines.append(f'    current = state.get("current_agent", "{entry_name}")')
    lines.append("")

    has_routes = False
    for route in network.routes:
        from_snake = _to_snake(route.from_agent)
        if route.to:
            first_to = _to_snake(route.to[0])
            condition_comment = f"  # condition: {route.condition}" if route.condition else ""
            lines.append(f'    if current == "{route.from_agent}":{condition_comment}')
            lines.append(f'        return "{first_to}_node"')
            has_routes = True

    if not has_routes:
        lines.append(f'    return END')
    else:
        lines.append(f'    return END')

    lines.append("")
    lines.append("")

    # Build graph
    lines.append("# ── Graph Assembly ────────────────────────────────────────────────────")
    lines.append("")
    lines.append("graph = StateGraph(NetworkState)")
    lines.append("")

    for name in names:
        snake = _to_snake(name)
        lines.append(f'graph.add_node("{snake}_node", {snake}_node)')

    lines.append("")

    # Entry point
    entry_snake = _to_snake(entry_name)
    lines.append(f'graph.add_edge(START, "{entry_snake}_node")')

    # Route edges
    route_targets: dict[str, list[str]] = {}
    for route in network.routes:
        from_snake = _to_snake(route.from_agent)
        from_key = f"{from_snake}_node"
        if from_key not in route_targets:
            route_targets[from_key] = []
        for to_name in route.to:
            to_snake = _to_snake(to_name)
            route_targets[from_key].append(f"{to_snake}_node")

    for from_node, to_nodes in route_targets.items():
        if len(to_nodes) == 1:
            lines.append(f'graph.add_edge("{from_node}", "{to_nodes[0]}")')
        else:
            lines.append(f'graph.add_conditional_edges("{from_node}", route_agent, {{')
            for tn in to_nodes:
                lines.append(f'    "{tn}": "{tn}",')
            lines.append(f'    END: END,')
            lines.append(f'}})')

    # Add END edges for terminal nodes
    routed_from = set(route_targets.keys())
    for name in names:
        snake = _to_snake(name)
        node_key = f"{snake}_node"
        if node_key not in routed_from:
            lines.append(f'graph.add_edge("{node_key}", END)')

    lines.append("")
    lines.append("app = graph.compile()")
    lines.append("")
    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append(f'    result = app.invoke({{"messages": [HumanMessage(content="Hello")], "current_agent": "", "turn_count": 0}})')
    lines.append(f'    for msg in result["messages"]:')
    lines.append(f'        print(f"{{msg.type}}: {{msg.content}}")')
    lines.append("")

    return "\n".join(lines)


def _compile_openai(network: NetworkSpec, specs: dict | None) -> str:
    """Generate OpenAI Agent SDK multi-agent handoff code."""
    names = network.agent_names()
    lines: list[str] = []

    lines.append(f'"""Multi-agent network: {network.name}')
    lines.append(f'{network.description}')
    lines.append(f'Generated by Cortex Protocol — do not edit directly."""')
    lines.append("")
    lines.append("from agents import Agent, Runner")
    lines.append("")
    lines.append("")

    # Define agents
    for name in names:
        snake = _to_snake(name)
        if specs and name in specs and specs[name]:
            desc = specs[name].agent.instructions.strip()[:200]
        else:
            desc = f"Agent: {name}"

        lines.append(f'{snake} = Agent(')
        lines.append(f'    name="{name}",')
        lines.append(f'    instructions="""{desc}""",')

        # Add handoffs
        routes = network.get_routes_from(name)
        if routes:
            handoff_names = []
            for route in routes:
                handoff_names.extend(route.to)
            handoffs_str = ", ".join(_to_snake(h) for h in handoff_names)
            lines.append(f'    handoffs=[{handoffs_str}],')

        lines.append(f')')
        lines.append("")

    lines.append("")
    lines.append('if __name__ == "__main__":')
    lines.append("    import asyncio")
    lines.append("")

    entry_name = names[0]
    entries = network.entry_agents()
    if entries:
        entry_name = entries[0].alias or entries[0].spec.replace(".yaml", "").replace(".yml", "")
    entry_snake = _to_snake(entry_name)

    lines.append("    async def main():")
    lines.append(f'        result = await Runner.run({entry_snake}, input="Hello")')
    lines.append("        print(result.final_output)")
    lines.append("")
    lines.append("    asyncio.run(main())")
    lines.append("")

    return "\n".join(lines)


def _compile_system_prompt(network: NetworkSpec) -> str:
    """Generate a system prompt describing the multi-agent network."""
    lines: list[str] = []
    names = network.agent_names()

    lines.append(f"# Multi-Agent Network: {network.name}")
    lines.append("")
    lines.append(f"{network.description}")
    lines.append("")
    lines.append("## Agents")
    lines.append("")

    for agent_ref, name in zip(network.agents, names):
        lines.append(f"- **{name}** (role: {agent_ref.role})")

    lines.append("")
    lines.append("## Routes")
    lines.append("")

    for route in network.routes:
        to_str = ", ".join(route.to)
        condition = f" when {route.condition}" if route.condition else ""
        lines.append(f"- {route.from_agent} → {to_str}{condition}")

    if network.shared_tools:
        lines.append("")
        lines.append("## Shared Tools")
        lines.append("")
        for tool in network.shared_tools:
            lines.append(f"- {tool}")

    if network.shared_policies.forbidden_actions:
        lines.append("")
        lines.append("## Network Policies")
        lines.append("")
        for action in network.shared_policies.forbidden_actions:
            lines.append(f"- FORBIDDEN: {action}")

    if network.shared_policies.max_turns:
        lines.append(f"- Max turns: {network.shared_policies.max_turns}")

    lines.append("")
    return "\n".join(lines)


def _compile_generic(network: NetworkSpec, target: str) -> str:
    """Generate a generic description for unsupported targets."""
    lines: list[str] = []
    lines.append(f"# Network: {network.name} — Target: {target}")
    lines.append(f"# {network.description}")
    lines.append(f"# Agents: {', '.join(network.agent_names())}")
    lines.append(f"# Routes: {len(network.routes)}")
    lines.append(f"#")
    lines.append(f"# Compile this network for a supported target:")
    lines.append(f"#   cortex-protocol compile-network network.yaml --target langgraph")
    lines.append(f"#   cortex-protocol compile-network network.yaml --target openai-sdk")
    lines.append("")
    return "\n".join(lines)


def _to_snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_").replace(".", "_")
