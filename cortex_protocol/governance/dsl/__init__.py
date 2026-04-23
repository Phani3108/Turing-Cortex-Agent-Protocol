"""Policy-as-code DSL for Turing.

A small expression language for writing governance rules without being
boxed in by the YAML `require_approval` / `forbidden_actions` lists.
Example:

    policies:
      rules:
        - when: 'tool_name matches "^delete_.*" and env != "staging"'
          action: require_approval
          reason: "Destructive tools require human approval outside staging"
        - when: 'run_cost_usd > 4.00'
          action: deny
          reason: "Approaching budget cap"

Every rule is compiled once at spec-load time. At runtime
`PolicyEnforcer.check_tool_call` evaluates the compiled predicates in
order against a context dict (tool_name, tool_input, turn,
run_cost_usd, env, ...) and returns the first matching action.

This layer is deliberately *additive*: specs with no `rules:` block
behave exactly as before, and existing `require_approval` /
`forbidden_actions` continue to fire independently.
"""

from __future__ import annotations

from .compiler import Predicate, RuleError, compile_expression, compile_rule
from .runtime import (
    RuleAction,
    RuleDecision,
    RuleSet,
    evaluate_rules,
)

__all__ = [
    "Predicate",
    "RuleError",
    "compile_expression",
    "compile_rule",
    "RuleAction",
    "RuleDecision",
    "RuleSet",
    "evaluate_rules",
]
