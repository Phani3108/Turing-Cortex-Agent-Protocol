"""
Spec differ for Cortex Protocol.

Compares two AgentSpec versions and produces a structured diff showing
what changed in tools, policies, model config, and instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import AgentSpec


@dataclass
class ToolChange:
    name: str
    kind: str  # "added" | "removed" | "modified"
    detail: str = ""


@dataclass
class PolicyChange:
    field: str
    old_value: Any
    new_value: Any

    def describe(self) -> str:
        return f"{self.field}: {self.old_value!r} → {self.new_value!r}"


@dataclass
class SpecDiff:
    spec_a_name: str
    spec_b_name: str

    # Tool changes
    tools_added: List[str] = field(default_factory=list)
    tools_removed: List[str] = field(default_factory=list)
    tools_modified: List[ToolChange] = field(default_factory=list)

    # Policy changes
    policy_changes: List[PolicyChange] = field(default_factory=list)

    # Model changes
    model_changes: List[PolicyChange] = field(default_factory=list)

    # Identity changes
    instructions_changed: bool = False
    description_changed: bool = False

    @property
    def is_empty(self) -> bool:
        return not any([
            self.tools_added,
            self.tools_removed,
            self.tools_modified,
            self.policy_changes,
            self.model_changes,
            self.instructions_changed,
            self.description_changed,
        ])

    @property
    def has_breaking_changes(self) -> bool:
        """Returns True if the diff contains changes that could break consumers."""
        return bool(self.tools_removed or self.policy_changes)

    def to_dict(self) -> dict:
        return {
            "a": self.spec_a_name,
            "b": self.spec_b_name,
            "breaking": self.has_breaking_changes,
            "tools": {
                "added": self.tools_added,
                "removed": self.tools_removed,
                "modified": [
                    {"name": t.name, "kind": t.kind, "detail": t.detail}
                    for t in self.tools_modified
                ],
            },
            "policies": [
                {"field": c.field, "from": c.old_value, "to": c.new_value}
                for c in self.policy_changes
            ],
            "model": [
                {"field": c.field, "from": c.old_value, "to": c.new_value}
                for c in self.model_changes
            ],
            "identity": {
                "instructions_changed": self.instructions_changed,
                "description_changed": self.description_changed,
            },
        }

    def summary_lines(self) -> List[str]:
        lines = []
        if self.is_empty:
            lines.append("No differences found.")
            return lines

        if self.has_breaking_changes:
            lines.append("⚠  Breaking changes detected")
            lines.append("")

        if self.tools_added:
            for t in self.tools_added:
                lines.append(f"  + tool: {t}")
        if self.tools_removed:
            for t in self.tools_removed:
                lines.append(f"  - tool: {t}")
        if self.tools_modified:
            for t in self.tools_modified:
                detail = f" ({t.detail})" if t.detail else ""
                lines.append(f"  ~ tool: {t.name}{detail}")

        for c in self.policy_changes:
            old = repr(c.old_value) if c.old_value is not None else "none"
            new = repr(c.new_value) if c.new_value is not None else "none"
            lines.append(f"  ~ policy.{c.field}: {old} → {new}")

        for c in self.model_changes:
            old = repr(c.old_value) if c.old_value is not None else "none"
            new = repr(c.new_value) if c.new_value is not None else "none"
            lines.append(f"  ~ model.{c.field}: {old} → {new}")

        if self.instructions_changed:
            lines.append("  ~ agent.instructions: changed")
        if self.description_changed:
            lines.append("  ~ agent.description: changed")

        return lines


# ---------------------------------------------------------------------------
# Diff logic
# ---------------------------------------------------------------------------

def _diff_tools(spec_a: AgentSpec, spec_b: AgentSpec) -> Tuple[List, List, List]:
    a_tools = {t.name: t for t in spec_a.tools}
    b_tools = {t.name: t for t in spec_b.tools}

    added = [n for n in b_tools if n not in a_tools]
    removed = [n for n in a_tools if n not in b_tools]

    modified = []
    for name in a_tools:
        if name not in b_tools:
            continue
        ta, tb = a_tools[name], b_tools[name]
        details = []
        if ta.description != tb.description:
            details.append("description changed")
        # Compare parameters at JSON level
        a_params = ta.parameters.model_dump() if ta.parameters else {}
        b_params = tb.parameters.model_dump() if tb.parameters else {}
        if a_params != b_params:
            details.append("parameters changed")
        if details:
            modified.append(ToolChange(name=name, kind="modified", detail="; ".join(details)))

    return added, removed, modified


def _diff_policies(spec_a: AgentSpec, spec_b: AgentSpec) -> List[PolicyChange]:
    pa = spec_a.policies
    pb = spec_b.policies
    changes = []

    def _get(p, attr):
        return getattr(p, attr, None) if p else None

    scalar_fields = ["max_turns"]
    for f in scalar_fields:
        va, vb = _get(pa, f), _get(pb, f)
        if va != vb:
            changes.append(PolicyChange(field=f, old_value=va, new_value=vb))

    # require_approval (list)
    ra = sorted(_get(pa, "require_approval") or [])
    rb = sorted(_get(pb, "require_approval") or [])
    if ra != rb:
        changes.append(PolicyChange(field="require_approval", old_value=ra, new_value=rb))

    # forbidden_actions (list)
    fa = sorted(_get(pa, "forbidden_actions") or [])
    fb = sorted(_get(pb, "forbidden_actions") or [])
    if fa != fb:
        changes.append(PolicyChange(field="forbidden_actions", old_value=fa, new_value=fb))

    # escalation
    ea = _get(pa, "escalation")
    eb = _get(pb, "escalation")
    ea_str = f"{ea.trigger}→{ea.target}" if ea else None
    eb_str = f"{eb.trigger}→{eb.target}" if eb else None
    if ea_str != eb_str:
        changes.append(PolicyChange(field="escalation", old_value=ea_str, new_value=eb_str))

    return changes


def _diff_model(spec_a: AgentSpec, spec_b: AgentSpec) -> List[PolicyChange]:
    ma = spec_a.model
    mb = spec_b.model
    changes = []

    def _get(m, attr):
        return getattr(m, attr, None) if m else None

    for f in ["preferred", "fallback", "temperature"]:
        va, vb = _get(ma, f), _get(mb, f)
        if va != vb:
            changes.append(PolicyChange(field=f, old_value=va, new_value=vb))

    return changes


def diff_specs(spec_a: AgentSpec, spec_b: AgentSpec) -> SpecDiff:
    """Compare two AgentSpec objects and return a SpecDiff."""
    added, removed, modified = _diff_tools(spec_a, spec_b)
    policy_changes = _diff_policies(spec_a, spec_b)
    model_changes = _diff_model(spec_a, spec_b)

    instructions_changed = (spec_a.agent.instructions or "") != (spec_b.agent.instructions or "")
    description_changed = (spec_a.agent.description or "") != (spec_b.agent.description or "")

    return SpecDiff(
        spec_a_name=spec_a.agent.name,
        spec_b_name=spec_b.agent.name,
        tools_added=added,
        tools_removed=removed,
        tools_modified=modified,
        policy_changes=policy_changes,
        model_changes=model_changes,
        instructions_changed=instructions_changed,
        description_changed=description_changed,
    )


def diff_files(path_a: str, path_b: str) -> SpecDiff:
    """Load two YAML spec files and diff them."""
    return diff_specs(AgentSpec.from_yaml(path_a), AgentSpec.from_yaml(path_b))
