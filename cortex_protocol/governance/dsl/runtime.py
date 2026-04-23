"""Runtime layer — apply a compiled rule set to a context dict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from .compiler import CompiledRule, RuleError, compile_rule


class RuleAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class RuleDecision:
    """Outcome of evaluating a rule set against a context."""

    action: RuleAction
    reason: str = ""
    rule_source: str = ""

    @classmethod
    def none(cls) -> "RuleDecision":
        return cls(action=RuleAction.ALLOW, reason="", rule_source="")


@dataclass
class RuleSet:
    """An ordered list of compiled rules. First-match wins."""

    rules: list[CompiledRule]

    @classmethod
    def from_list(cls, raw: Optional[Iterable[dict]]) -> "RuleSet":
        compiled: list[CompiledRule] = []
        for i, rule in enumerate(raw or []):
            try:
                compiled.append(compile_rule(rule))
            except RuleError as e:
                raise RuleError(f"rule #{i} failed to compile: {e}") from None
        return cls(rules=compiled)

    def evaluate(self, ctx: dict) -> RuleDecision:
        for rule in self.rules:
            try:
                matched = bool(rule.predicate(ctx))
            except Exception:
                # Any evaluation error falls through — fail safe, not closed.
                # The spec-level require_approval / forbidden_actions still
                # apply and will catch genuine policy violations.
                continue
            if matched:
                return RuleDecision(
                    action=RuleAction(rule.action),
                    reason=rule.reason,
                    rule_source=rule.when_source,
                )
        return RuleDecision.none()


def evaluate_rules(raw_rules: Optional[Iterable[dict]], ctx: dict) -> RuleDecision:
    """Convenience: compile + evaluate in one step (useful for tests)."""
    return RuleSet.from_list(raw_rules).evaluate(ctx)
