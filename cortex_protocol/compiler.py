"""Core compilation engine — model-family-aware prompt formatting.

Ported from Cortex compiler.js. Different models respond differently
to the same instructions. This module formats agent specs optimally
for each model family.
"""

from __future__ import annotations

from .model_families import get_format_family, resolve_family
from .models import AgentSpec


def compile_system_prompt(spec: AgentSpec, model_hint: str | None = None) -> str:
    """Compile an agent spec into a model-optimized system prompt."""
    model = model_hint or spec.model.preferred
    format_family = get_format_family(model)

    sections = _build_sections(spec)

    formatters = {
        "claude-family": _format_claude,
        "openai-family": _format_openai,
        "reasoning-family": _format_reasoning,
        "gemini-family": _format_gemini,
        "open-source": _format_open_source,
    }

    formatter = formatters.get(format_family, _format_openai)
    return formatter(sections)


def _build_sections(spec: AgentSpec) -> dict[str, list[str]]:
    """Extract structured sections from an agent spec."""
    sections: dict[str, list[str]] = {}

    # Identity
    sections["identity"] = [
        f"You are {spec.agent.name}.",
        spec.agent.description,
    ]

    # Instructions
    sections["instructions"] = [spec.agent.instructions.strip()]

    # Tools
    if spec.tools:
        tool_lines = []
        for tool in spec.tools:
            params = ""
            if tool.parameters.properties:
                param_names = ", ".join(tool.parameters.properties.keys())
                params = f" (parameters: {param_names})"
            tool_lines.append(f"{tool.name}: {tool.description}{params}")
        sections["tools"] = tool_lines

    # Policies
    policy_lines = []
    if spec.policies.max_turns:
        policy_lines.append(
            f"You must complete your task within {spec.policies.max_turns} turns. "
            "If you cannot, escalate to a human."
        )
    if spec.policies.require_approval:
        tools = ", ".join(spec.policies.require_approval)
        policy_lines.append(
            f"The following tools require human approval before execution: {tools}"
        )
    if spec.policies.forbidden_actions:
        for action in spec.policies.forbidden_actions:
            policy_lines.append(f"You must NEVER: {action}")
    if spec.policies.escalation.trigger:
        policy_lines.append(
            f"Escalation rule: When {spec.policies.escalation.trigger}, "
            f"escalate to {spec.policies.escalation.target}."
        )
    if policy_lines:
        sections["policies"] = policy_lines

    return sections


# ── Claude Format ───────────────────────────────────────────────────────────
# Claude responds well to XML structure and direct imperatives.

def _format_claude(sections: dict[str, list[str]]) -> str:
    parts = []
    for section, items in sections.items():
        parts.append(f"<{section}>")
        for item in items:
            parts.append(f"- {item}")
        parts.append(f"</{section}>")
        parts.append("")
    return "\n".join(parts).strip()


# ── OpenAI Format ───────────────────────────────────────────────────────────
# GPT models prefer numbered lists with clear section headers.

def _format_openai(sections: dict[str, list[str]]) -> str:
    parts = []
    for section, items in sections.items():
        parts.append(f"## {_capitalize(section)}")
        parts.append("")
        for i, item in enumerate(items, 1):
            parts.append(f"{i}. {item}")
        parts.append("")
    return "\n".join(parts).strip()


# ── Reasoning Model Format ──────────────────────────────────────────────────
# o1, o3, o4-mini — internal chain-of-thought. Minimal scaffolding.

def _format_reasoning(sections: dict[str, list[str]]) -> str:
    parts = ["## Task Constraints", ""]
    for section, items in sections.items():
        if len(items) == 1:
            parts.append(f"- **{_capitalize(section)}**: {items[0]}")
        else:
            parts.append(f"### {_capitalize(section)}")
            for item in items:
                parts.append(f"- {item}")
        parts.append("")
    return "\n".join(parts).strip()


# ── Gemini Format ───────────────────────────────────────────────────────────
# Gemini benefits from XML tags for context, markdown for instructions.

def _format_gemini(sections: dict[str, list[str]]) -> str:
    parts = []
    context_keys = {"identity", "instructions"}
    for section, items in sections.items():
        if section in context_keys:
            parts.append(f"<{section}>")
            for item in items:
                parts.append(f"- {item}")
            parts.append(f"</{section}>")
        else:
            parts.append(f"## {_capitalize(section)}")
            parts.append("")
            for item in items:
                parts.append(f"- {item}")
        parts.append("")
    return "\n".join(parts).strip()


# ── Open Source Format ──────────────────────────────────────────────────────
# Llama, DeepSeek, Mistral — need more explicit instructions.

def _format_open_source(sections: dict[str, list[str]]) -> str:
    parts = ["IMPORTANT INSTRUCTIONS — Follow these rules strictly:", ""]
    for section, items in sections.items():
        parts.append(f"### {_capitalize(section)}")
        parts.append("")
        for item in items:
            parts.append(f"- {item}")
        parts.append("")
    parts.append("Do not deviate from these rules.")
    return "\n".join(parts).strip()


def _capitalize(s: str) -> str:
    return s.replace("_", " ").capitalize()
