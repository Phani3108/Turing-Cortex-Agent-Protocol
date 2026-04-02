"""
Policy linter for Cortex Protocol agent specs.

Scores a spec 0-100 and assigns a letter grade based on governance completeness.
Each rule has a weight; passing all weighted rules = 100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .models import AgentSpec


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class LintRule:
    id: str
    severity: Severity
    message: str
    weight: int  # contribution to score (0-100 total across all rules)


@dataclass
class LintResult:
    rule: LintRule
    passed: bool
    detail: str = ""

    @property
    def icon(self) -> str:
        if self.passed:
            return "✓"
        icons = {Severity.ERROR: "✗", Severity.WARNING: "⚠", Severity.INFO: "ℹ"}
        return icons[self.rule.severity]


@dataclass
class LintReport:
    spec_name: str
    results: List[LintResult] = field(default_factory=list)

    @property
    def score(self) -> int:
        """0-100 weighted score based on passing rules."""
        total_weight = sum(r.rule.weight for r in self.results)
        if total_weight == 0:
            return 100
        earned = sum(r.rule.weight for r in self.results if r.passed)
        return round(earned / total_weight * 100)

    @property
    def grade(self) -> str:
        s = self.score
        if s >= 90:
            return "A"
        if s >= 80:
            return "B"
        if s >= 70:
            return "C"
        if s >= 60:
            return "D"
        return "F"

    @property
    def errors(self) -> List[LintResult]:
        return [r for r in self.results if not r.passed and r.rule.severity == Severity.ERROR]

    @property
    def warnings(self) -> List[LintResult]:
        return [r for r in self.results if not r.passed and r.rule.severity == Severity.WARNING]

    @property
    def infos(self) -> List[LintResult]:
        return [r for r in self.results if not r.passed and r.rule.severity == Severity.INFO]

    def to_dict(self) -> dict:
        return {
            "spec": self.spec_name,
            "score": self.score,
            "grade": self.grade,
            "results": [
                {
                    "rule": r.rule.id,
                    "severity": r.rule.severity.value,
                    "passed": r.passed,
                    "message": r.rule.message,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }


# ---------------------------------------------------------------------------
# Lint rules — weights must sum to 100
# ---------------------------------------------------------------------------

# Risky tools that should require human approval before execution
_RISKY_TOOL_PATTERNS = re.compile(
    r"(delete|remove|cancel|send|pay|charge|escalate|page|alert|deploy|"
    r"drop|destroy|terminate|shutdown|reset|override|approve|reject|"
    r"publish|broadcast|notify|email|sms|call)",
    re.IGNORECASE,
)

RULES: List[LintRule] = [
    LintRule(
        id="approval-gate-missing",
        severity=Severity.ERROR,
        message="Risky tools have no human approval gate",
        weight=25,
    ),
    LintRule(
        id="no-forbidden-actions",
        severity=Severity.ERROR,
        message="No forbidden_actions guardrails defined",
        weight=20,
    ),
    LintRule(
        id="missing-max-turns",
        severity=Severity.WARNING,
        message="No max_turns limit — agent can run indefinitely",
        weight=15,
    ),
    LintRule(
        id="no-escalation-path",
        severity=Severity.WARNING,
        message="No escalation path defined for failures or edge cases",
        weight=15,
    ),
    LintRule(
        id="thin-instructions",
        severity=Severity.WARNING,
        message="Instructions are too brief (< 30 words) to be reliable",
        weight=10,
    ),
    LintRule(
        id="no-fallback-model",
        severity=Severity.INFO,
        message="No fallback model specified — outages will cause hard failures",
        weight=10,
    ),
    LintRule(
        id="tools-missing-required",
        severity=Severity.WARNING,
        message="One or more tools have parameters but no required fields",
        weight=5,
    ),
]

# Build a lookup by id
_RULE_MAP = {r.id: r for r in RULES}


def _check_approval_gate(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["approval-gate-missing"]
    risky = [t.name for t in spec.tools if _RISKY_TOOL_PATTERNS.search(t.name)]
    if not risky:
        return LintResult(rule=rule, passed=True)
    approved = spec.policies.require_approval if spec.policies else []
    unapproved = [t for t in risky if t not in approved]
    if unapproved:
        return LintResult(
            rule=rule,
            passed=False,
            detail=f"Risky tools without approval gate: {', '.join(unapproved)}",
        )
    return LintResult(rule=rule, passed=True)


def _check_forbidden_actions(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["no-forbidden-actions"]
    has_guardrails = (
        spec.policies is not None
        and spec.policies.forbidden_actions
        and len(spec.policies.forbidden_actions) > 0
    )
    if has_guardrails:
        return LintResult(rule=rule, passed=True)
    return LintResult(
        rule=rule,
        passed=False,
        detail="Add policies.forbidden_actions to constrain agent behaviour",
    )


def _check_max_turns(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["missing-max-turns"]
    has_limit = spec.policies is not None and spec.policies.max_turns is not None
    if has_limit:
        return LintResult(rule=rule, passed=True)
    return LintResult(
        rule=rule,
        passed=False,
        detail="Set policies.max_turns to prevent runaway loops",
    )


def _check_escalation(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["no-escalation-path"]
    esc = spec.policies.escalation if spec.policies else None
    has_escalation = esc is not None and bool(esc.trigger)
    if has_escalation:
        return LintResult(rule=rule, passed=True)
    return LintResult(
        rule=rule,
        passed=False,
        detail="Define policies.escalation.trigger + target for graceful handoff",
    )


def _check_instructions(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["thin-instructions"]
    instructions = spec.agent.instructions or ""
    word_count = len(instructions.split())
    if word_count >= 30:
        return LintResult(rule=rule, passed=True)
    return LintResult(
        rule=rule,
        passed=False,
        detail=f"Instructions are {word_count} words — aim for 30+ for reliable behaviour",
    )


def _check_fallback_model(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["no-fallback-model"]
    has_fallback = spec.model is not None and spec.model.fallback is not None
    if has_fallback:
        return LintResult(rule=rule, passed=True)
    return LintResult(
        rule=rule,
        passed=False,
        detail="Add model.fallback to handle primary model outages",
    )


def _check_tools_required(spec: AgentSpec) -> LintResult:
    rule = _RULE_MAP["tools-missing-required"]
    if not spec.tools:
        return LintResult(rule=rule, passed=True)
    flagged = []
    for tool in spec.tools:
        if tool.parameters and tool.parameters.properties:
            if len(tool.parameters.properties) > 1 and not tool.parameters.required:
                # 2+ properties with no required array = likely a mistake
                flagged.append(tool.name)
    if flagged:
        return LintResult(
            rule=rule,
            passed=False,
            detail=f"Tools missing required fields: {', '.join(flagged)}",
        )
    return LintResult(rule=rule, passed=True)


_CHECKERS = [
    _check_approval_gate,
    _check_forbidden_actions,
    _check_max_turns,
    _check_escalation,
    _check_instructions,
    _check_fallback_model,
    _check_tools_required,
]


def lint(spec: AgentSpec) -> LintReport:
    """Run all lint rules against a spec and return a LintReport."""
    report = LintReport(spec_name=spec.agent.name)
    for checker in _CHECKERS:
        report.results.append(checker(spec))
    return report


def lint_file(path: str) -> LintReport:
    """Load a YAML spec file and lint it."""
    spec = AgentSpec.from_yaml(path)
    return lint(spec)
