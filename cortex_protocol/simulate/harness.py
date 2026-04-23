"""Simulation harness — load scenarios and run them against a spec."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

from ..governance.enforcer import PolicyEnforcer
from ..governance.exceptions import (
    ApprovalRequired,
    BudgetExceeded,
    ForbiddenActionDetected,
    MaxTurnsExceeded,
    PolicyViolation,
)
from ..models import AgentSpec


BUNDLED_SCENARIOS_DIR = Path(__file__).parent / "scenarios"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class ScenarioStep:
    """One step in a scenario. `kind` drives which enforcer method runs."""
    kind: str                          # "tool_call" | "response" | "usage" | "turn"
    tool_name: Optional[str] = None
    tool_input: dict = field(default_factory=dict)
    text: str = ""                     # for response
    model: str = ""                    # for usage
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Optional[float] = None


@dataclass
class ScenarioExpectation:
    """Which policies MUST fire for the scenario to count as PASSED."""
    block_tools: list[str] = field(default_factory=list)     # tool names that must be blocked
    forbidden_match: list[str] = field(default_factory=list) # response snippets that must trip forbidden_actions
    require_approval_hit: bool = False                        # approval gate must fire at least once
    budget_block: bool = False                                 # budget cap must fire


@dataclass
class Scenario:
    id: str
    name: str
    category: str
    severity: str = "medium"
    description: str = ""
    steps: list[ScenarioStep] = field(default_factory=list)
    expected: ScenarioExpectation = field(default_factory=ScenarioExpectation)
    source_path: str = ""


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    category: str
    severity: str
    passed: bool
    findings: list[str] = field(default_factory=list)
    # Observed signals — raw material the findings were computed from.
    blocked_tools: list[str] = field(default_factory=list)
    forbidden_matches: list[str] = field(default_factory=list)
    approval_required: bool = False
    budget_blocked: bool = False

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "category": self.category,
            "severity": self.severity,
            "passed": self.passed,
            "findings": self.findings,
            "blocked_tools": self.blocked_tools,
            "forbidden_matches": self.forbidden_matches,
            "approval_required": self.approval_required,
            "budget_blocked": self.budget_blocked,
        }


@dataclass
class SimulationReport:
    total: int
    passed: int
    failed: int
    results: list[ScenarioResult]

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 1.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.pass_rate, 3),
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _scenario_from_dict(data: dict, *, source: str = "") -> Scenario:
    expected = data.get("expected", {}) or {}
    steps: list[ScenarioStep] = []
    for step in data.get("steps", []) or []:
        steps.append(ScenarioStep(
            kind=step.get("kind", "tool_call"),
            tool_name=step.get("tool_name"),
            tool_input=step.get("tool_input") or {},
            text=step.get("text", ""),
            model=step.get("model", ""),
            input_tokens=step.get("input_tokens", 0),
            output_tokens=step.get("output_tokens", 0),
            cost_usd=step.get("cost_usd"),
        ))
    return Scenario(
        id=data["id"],
        name=data.get("name", data["id"]),
        category=data.get("category", "generic"),
        severity=data.get("severity", "medium"),
        description=data.get("description", ""),
        steps=steps,
        expected=ScenarioExpectation(
            block_tools=list(expected.get("block_tools") or []),
            forbidden_match=list(expected.get("forbidden_match") or []),
            require_approval_hit=bool(expected.get("require_approval_hit", False)),
            budget_block=bool(expected.get("budget_block", False)),
        ),
        source_path=source,
    )


def load_scenarios(paths: Optional[Iterable[Path]] = None,
                   *, include_bundled: bool = True) -> list[Scenario]:
    """Load scenarios from YAML files and/or directories.

    A path that is a directory is walked (*.yaml, *.yml). If
    `include_bundled` is True (the default), Turing's shipped pack is
    also included.
    """
    collected: list[Scenario] = []
    sources: list[Path] = []
    if include_bundled:
        sources.append(BUNDLED_SCENARIOS_DIR)
    for p in paths or []:
        sources.append(Path(p))

    for src in sources:
        if not src.exists():
            continue
        if src.is_file():
            collected.extend(_load_file(src))
            continue
        for f in sorted(src.rglob("*.yaml")):
            collected.extend(_load_file(f))
        for f in sorted(src.rglob("*.yml")):
            collected.extend(_load_file(f))
    return collected


def _load_file(path: Path) -> list[Scenario]:
    data = yaml.safe_load(path.read_text())
    if data is None:
        return []
    # Support both a single scenario and a list (multi-doc) per file.
    if isinstance(data, list):
        return [_scenario_from_dict(d, source=str(path)) for d in data]
    return [_scenario_from_dict(data, source=str(path))]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _auto_deny(tool, tool_input, context):
    return False


def run_scenarios(spec: AgentSpec, scenarios: list[Scenario]) -> SimulationReport:
    results: list[ScenarioResult] = [_run_one(spec, s) for s in scenarios]
    passed = sum(1 for r in results if r.passed)
    return SimulationReport(
        total=len(results), passed=passed,
        failed=len(results) - passed, results=results,
    )


def _run_one(spec: AgentSpec, scenario: Scenario) -> ScenarioResult:
    enforcer = PolicyEnforcer(spec, strict_forbidden=False,
                               approval_handler=_auto_deny)
    blocked_tools: list[str] = []
    forbidden_matches: list[str] = []
    approval_required = False
    budget_blocked = False
    findings: list[str] = []

    # Seed a single turn boundary so check_tool_call has a turn counter.
    try:
        enforcer.increment_turn()
    except MaxTurnsExceeded:
        pass

    for step in scenario.steps:
        if step.kind == "turn":
            try:
                enforcer.increment_turn()
            except MaxTurnsExceeded:
                pass
            continue

        if step.kind == "usage":
            try:
                enforcer.record_usage(
                    model=step.model or None,
                    input_tokens=step.input_tokens,
                    output_tokens=step.output_tokens,
                    cost_usd=step.cost_usd,
                )
            except BudgetExceeded:
                budget_blocked = True
            continue

        if step.kind == "response":
            ef = enforcer.check_response(step.text)
            for v in ef.violations:
                forbidden_matches.append(v.action or step.text[:60])
            continue

        if step.kind == "tool_call":
            if not step.tool_name:
                findings.append(f"  [!] step without tool_name — skipped")
                continue
            try:
                enforcer.check_tool_call(step.tool_name, step.tool_input)
            except ApprovalRequired:
                approval_required = True
                blocked_tools.append(step.tool_name)
            except BudgetExceeded:
                budget_blocked = True
                blocked_tools.append(step.tool_name)
            except ForbiddenActionDetected:
                blocked_tools.append(step.tool_name)
            except MaxTurnsExceeded:
                blocked_tools.append(step.tool_name)
            except PolicyViolation:
                blocked_tools.append(step.tool_name)
            continue

        findings.append(f"  [!] unknown step kind: {step.kind}")

    # Score against expectations.
    passed = True
    for tool in scenario.expected.block_tools:
        if tool not in blocked_tools:
            findings.append(f"  [FAIL] expected tool '{tool}' to be blocked but it was allowed")
            passed = False
        else:
            findings.append(f"  [ok] blocked '{tool}'")
    for snippet in scenario.expected.forbidden_match:
        if not any(snippet.lower() in m.lower() or snippet.lower() in _flatten(forbidden_matches).lower()
                   for m in forbidden_matches + [snippet]) and not any(
            snippet.lower() in ev.detail.lower() for ev in enforcer.audit_log.events()
        ):
            findings.append(f"  [FAIL] expected forbidden match on '{snippet}' did not fire")
            passed = False
        else:
            findings.append(f"  [ok] forbidden match fired for '{snippet}'")
    if scenario.expected.require_approval_hit and not approval_required:
        findings.append("  [FAIL] expected approval gate to fire; it did not")
        passed = False
    elif scenario.expected.require_approval_hit:
        findings.append("  [ok] approval gate fired")
    if scenario.expected.budget_block and not budget_blocked:
        findings.append("  [FAIL] expected budget block; none fired")
        passed = False
    elif scenario.expected.budget_block:
        findings.append("  [ok] budget block fired")

    return ScenarioResult(
        scenario_id=scenario.id,
        name=scenario.name,
        category=scenario.category,
        severity=scenario.severity,
        passed=passed,
        findings=findings,
        blocked_tools=blocked_tools,
        forbidden_matches=forbidden_matches,
        approval_required=approval_required,
        budget_blocked=budget_blocked,
    )


def _flatten(items: list[Any]) -> str:
    return " ".join(str(i) for i in items)
