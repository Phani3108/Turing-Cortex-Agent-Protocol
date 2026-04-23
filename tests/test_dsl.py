"""Tests for the policy-as-code DSL (lexer, parser, compiler, enforcer wiring)."""

from __future__ import annotations

import pytest

from cortex_protocol.governance.dsl import (
    RuleAction,
    RuleError,
    compile_expression,
    compile_rule,
    evaluate_rules,
)
from cortex_protocol.governance.dsl.lexer import LexError, tokenize
from cortex_protocol.governance.dsl.parser import ParseError, parse
from cortex_protocol.governance.enforcer import PolicyEnforcer
from cortex_protocol.governance.exceptions import (
    ApprovalRequired,
    RuleDenied,
)
from cortex_protocol.models import (
    AgentIdentity, AgentMetadata, AgentSpec, ModelConfig, PolicySpec,
    ToolParameter, ToolSpec,
)


def _spec(rules=None, *, env="production", tools=None,
          require_approval=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name="dsl-test", description="t",
                             instructions="Answer concisely. Cite sources. Escalate when unsure."),
        tools=tools or [
            ToolSpec(name="search", description="",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="delete_user", description="",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="send-email", description="",
                     parameters=ToolParameter(type="object")),
        ],
        policies=PolicySpec(
            max_turns=10,
            require_approval=require_approval or [],
            rules=list(rules or []),
        ),
        model=ModelConfig(preferred="claude-sonnet-4"),
        metadata=AgentMetadata(environment=env, tags=["payment"]),
    )


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class TestLexer:
    def test_basic_tokens(self):
        toks = tokenize("tool_name == 'x' and turn > 2")
        kinds = [t.kind for t in toks if t.kind != "EOF"]
        assert kinds == ["IDENT", "OP", "STRING", "KEYWORD", "IDENT", "OP", "NUMBER"]

    def test_string_escapes(self):
        toks = tokenize(r"'hello\nworld'")
        assert toks[0].value == "hello\nworld"

    def test_keyword_vs_ident(self):
        toks = tokenize("and or not in matches true false null foo")
        kinds = [(t.kind, t.value) for t in toks if t.kind != "EOF"]
        # All except the last (foo) should be KEYWORD.
        for kind, _ in kinds[:-1]:
            assert kind == "KEYWORD"
        assert kinds[-1] == ("IDENT", "foo")

    def test_unterminated_string(self):
        with pytest.raises(LexError):
            tokenize("'unterminated")

    def test_unknown_char(self):
        with pytest.raises(LexError):
            tokenize("@@")

    def test_float(self):
        toks = tokenize("cost > 4.50")
        assert toks[2].kind == "NUMBER" and toks[2].value == "4.50"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class TestParser:
    def test_precedence(self):
        ast = parse("a == 1 or b == 2 and c == 3")
        # Top-level should be `or`, right side should be `and`.
        assert ast.op == "or"
        assert ast.right.op == "and"

    def test_nested_dot_access(self):
        ast = parse("tool_input.customer.tier == 'gold'")
        assert ast.op == "=="
        assert ast.left.parts == ("tool_input", "customer", "tier")

    def test_function_call(self):
        ast = parse("len(tool_input.items) > 10")
        assert ast.op == ">"
        assert ast.left.name == "len"

    def test_list_and_in(self):
        ast = parse("tool_name in ['a', 'b']")
        assert ast.op == "in"
        assert len(ast.right.items) == 2

    def test_not_in(self):
        ast = parse("env not in ['prod']")
        assert ast.op == "not in"

    def test_parenthesized(self):
        ast = parse("(a == 1) and b == 2")
        assert ast.op == "and"

    def test_trailing_garbage_raises(self):
        with pytest.raises(ParseError):
            parse("a == 1 garbage")


# ---------------------------------------------------------------------------
# Compiler / evaluator
# ---------------------------------------------------------------------------

class TestCompiler:
    def test_literal(self):
        fn = compile_expression("42")
        assert fn({}) == 42

    def test_name_lookup(self):
        fn = compile_expression("tool_name")
        assert fn({"tool_name": "search"}) == "search"

    def test_missing_name_is_none(self):
        fn = compile_expression("missing.deep.key")
        assert fn({"tool_name": "x"}) is None

    def test_comparison(self):
        fn = compile_expression("turn > 3")
        assert fn({"turn": 5})
        assert not fn({"turn": 2})

    def test_and_or_short_circuit(self):
        fn = compile_expression("a or b")
        assert fn({"a": True, "b": False})
        fn2 = compile_expression("a and b")
        assert not fn2({"a": True, "b": False})

    def test_not(self):
        fn = compile_expression("not flag")
        assert fn({"flag": False})
        assert not fn({"flag": True})

    def test_in_list(self):
        fn = compile_expression("tool_name in ['a', 'b', 'c']")
        assert fn({"tool_name": "b"})
        assert not fn({"tool_name": "z"})

    def test_matches_regex(self):
        fn = compile_expression("tool_name matches '^delete_'")
        assert fn({"tool_name": "delete_user"})
        assert not fn({"tool_name": "search"})

    def test_startswith_endswith_contains(self):
        assert compile_expression("tool_name startswith 'del'")({"tool_name": "delete"})
        assert compile_expression("tool_name endswith 'user'")({"tool_name": "delete_user"})
        assert compile_expression("tool_name contains 'ete'")({"tool_name": "delete"})

    def test_len_builtin(self):
        fn = compile_expression("len(items) > 3")
        assert fn({"items": [1, 2, 3, 4]})

    def test_unknown_function_raises(self):
        with pytest.raises(RuleError):
            compile_expression("sqrt(x)")

    def test_type_errors_return_false(self):
        # Comparing a missing value against a number must not crash.
        fn = compile_expression("nope > 5")
        assert fn({}) is False


class TestRuleCompilation:
    def test_valid_rule(self):
        rule = compile_rule({"when": "turn > 3", "action": "deny",
                              "reason": "too many turns"})
        assert rule.action == "deny"
        assert rule.reason == "too many turns"

    def test_missing_when(self):
        with pytest.raises(RuleError):
            compile_rule({"action": "deny"})

    def test_invalid_action(self):
        with pytest.raises(RuleError):
            compile_rule({"when": "1 == 1", "action": "laugh"})


class TestEvaluateRules:
    def test_first_match_wins(self):
        rules = [
            {"when": "tool_name == 'x'", "action": "allow"},
            {"when": "tool_name == 'x'", "action": "deny"},   # unreached
        ]
        decision = evaluate_rules(rules, {"tool_name": "x"})
        assert decision.action is RuleAction.ALLOW

    def test_no_match(self):
        decision = evaluate_rules(
            [{"when": "false", "action": "deny"}],
            {"tool_name": "x"},
        )
        assert decision.action is RuleAction.ALLOW
        assert decision.rule_source == ""

    def test_evaluation_error_skips_to_next(self):
        rules = [
            # This rule's `len()` receives None and works; this is more a
            # belt-and-suspenders test for the general swallow-exception contract.
            {"when": "len(unknown) > 0", "action": "deny"},
            {"when": "true", "action": "require_approval"},
        ]
        decision = evaluate_rules(rules, {})
        assert decision.action is RuleAction.REQUIRE_APPROVAL


# ---------------------------------------------------------------------------
# Enforcer integration
# ---------------------------------------------------------------------------

class TestEnforcerIntegration:
    def test_deny_rule_raises_rule_denied(self):
        spec = _spec(rules=[
            {"when": "tool_name matches '^delete_'", "action": "deny",
             "reason": "destructive"},
        ])
        e = PolicyEnforcer(spec)
        e.increment_turn()
        with pytest.raises(RuleDenied) as exc:
            e.check_tool_call("delete_user", {"id": 1})
        assert exc.value.rule_source.startswith("tool_name")
        assert "destructive" in str(exc.value)

    def test_allow_rule_bypasses_static_require_approval(self):
        # Static rule says "send-email requires approval"; DSL rule allows it.
        spec = _spec(
            require_approval=["send-email"],
            rules=[{"when": "tool_name == 'send-email'", "action": "allow",
                     "reason": "pre-authorized"}],
        )
        e = PolicyEnforcer(spec)
        e.increment_turn()
        result = e.check_tool_call("send-email", {"to": "x"})
        assert result.allowed

    def test_require_approval_rule_without_handler_raises(self):
        spec = _spec(rules=[
            {"when": "tool_name == 'search' and env == 'production'",
             "action": "require_approval",
             "reason": "prod read-through needs approval"},
        ])
        e = PolicyEnforcer(spec)
        e.increment_turn()
        with pytest.raises(ApprovalRequired) as exc:
            e.check_tool_call("search", {})
        assert exc.value.policy == "rule:require_approval"

    def test_require_approval_rule_with_handler_approves(self):
        spec = _spec(rules=[
            {"when": "tool_name == 'search'",
             "action": "require_approval", "reason": "demo"},
        ])
        e = PolicyEnforcer(spec, approval_handler=lambda *a: True)
        e.increment_turn()
        result = e.check_tool_call("search", {})
        assert result.allowed
        # Single tool-call record (no double counting).
        assert e.cost.snapshot.total_tool_calls == 1

    def test_rule_that_never_matches_is_noop(self):
        spec = _spec(rules=[
            {"when": "tool_name == 'nope'", "action": "deny"},
        ])
        e = PolicyEnforcer(spec)
        e.increment_turn()
        e.check_tool_call("search", {})   # fine

    def test_cost_aware_rule(self):
        spec = _spec(rules=[
            {"when": "run_cost_usd > 0.01", "action": "deny",
             "reason": "budget"},
        ])
        e = PolicyEnforcer(spec)
        e.increment_turn()
        # Spend some money first — enough to trip the rule but not a cost cap.
        e.record_usage(model="claude-sonnet-4",
                        input_tokens=10_000, output_tokens=0)
        with pytest.raises(RuleDenied):
            e.check_tool_call("search", {})

    def test_audit_event_shape_on_deny(self):
        spec = _spec(rules=[
            {"when": "tool_name == 'search'", "action": "deny"},
        ])
        e = PolicyEnforcer(spec)
        e.increment_turn()
        with pytest.raises(RuleDenied):
            e.check_tool_call("search", {})
        types = [ev.event_type for ev in e.audit_log.events()]
        assert "rule_denied" in types

    def test_bad_rule_at_construction_raises(self):
        spec = _spec(rules=[{"when": "this is not !!! valid", "action": "deny"}])
        with pytest.raises(RuleError):
            PolicyEnforcer(spec)
