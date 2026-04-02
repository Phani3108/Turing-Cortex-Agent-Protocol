"""Tests for the policy linter."""

import pytest

from cortex_protocol.linter import lint, RULES, Severity
from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, PolicySpec,
    EscalationPolicy, ModelConfig, ToolParameter,
)


def _make_spec(
    name="test-agent",
    instructions="You are a helpful assistant. Be clear and concise. Always ask before acting.",
    tools=None,
    policies=None,
    model=None,
):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name=name, description="Test agent", instructions=instructions),
        tools=tools or [],
        policies=policies or PolicySpec(
            max_turns=10,
            require_approval=[],
            forbidden_actions=["Do not harm users"],
            escalation=EscalationPolicy(trigger="on failure", target="human"),
        ),
        model=model or ModelConfig(preferred="claude-sonnet-4", fallback="gpt-4o"),
    )


def _full_spec():
    """A spec that passes every lint rule."""
    return _make_spec(
        instructions=(
            "You are a helpful assistant. Be clear and concise. "
            "Always ask before acting. Cite sources when available."
        ),
        tools=[
            ToolSpec(
                name="search",
                description="Search the web",
                parameters=ToolParameter(
                    type="object",
                    properties={"query": {"type": "string"}},
                    required=["query"],
                ),
            )
        ],
        policies=PolicySpec(
            max_turns=10,
            require_approval=[],
            forbidden_actions=["Do not share PII"],
            escalation=EscalationPolicy(trigger="on unresolvable error", target="human-support"),
        ),
        model=ModelConfig(preferred="claude-sonnet-4", fallback="gpt-4o", temperature=0.5),
    )


# ---------------------------------------------------------------------------
# Score and grade
# ---------------------------------------------------------------------------

class TestScoreAndGrade:
    def test_full_spec_scores_high(self):
        report = lint(_full_spec())
        assert report.score >= 80
        assert report.grade in ("A", "B")

    def test_empty_policies_scores_low(self):
        spec = _make_spec(
            instructions="Short.",
            tools=[],
            policies=PolicySpec(max_turns=None, require_approval=[], forbidden_actions=[]),
            model=ModelConfig(preferred="gpt-4o"),
        )
        report = lint(spec)
        assert report.score < 60
        assert report.grade in ("D", "F")

    def test_score_is_0_to_100(self):
        report = lint(_full_spec())
        assert 0 <= report.score <= 100

    def test_grade_progression(self):
        # grades map correctly
        assert lint(_full_spec()).grade in ("A", "B", "C", "D", "F")


# ---------------------------------------------------------------------------
# Rule: approval-gate-missing
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_risky_tool_without_approval_fails(self):
        spec = _make_spec(
            tools=[
                ToolSpec(name="send-email", description="Send an email",
                         parameters=ToolParameter(type="object", properties={}, required=[]))
            ],
            policies=PolicySpec(
                max_turns=10,
                require_approval=[],
                forbidden_actions=["Never send spam"],
                escalation=EscalationPolicy(trigger="error", target="human"),
            ),
        )
        report = lint(spec)
        gate_result = next(r for r in report.results if r.rule.id == "approval-gate-missing")
        assert not gate_result.passed
        assert "send-email" in gate_result.detail

    def test_risky_tool_with_approval_passes(self):
        spec = _make_spec(
            tools=[
                ToolSpec(name="send-email", description="Send an email",
                         parameters=ToolParameter(type="object", properties={}, required=[]))
            ],
            policies=PolicySpec(
                max_turns=10,
                require_approval=["send-email"],
                forbidden_actions=["Never send spam"],
                escalation=EscalationPolicy(trigger="error", target="human"),
            ),
        )
        report = lint(spec)
        gate_result = next(r for r in report.results if r.rule.id == "approval-gate-missing")
        assert gate_result.passed

    def test_non_risky_tool_no_approval_needed(self):
        spec = _make_spec(
            tools=[
                ToolSpec(name="summarize", description="Summarize text",
                         parameters=ToolParameter(type="object", properties={}, required=[]))
            ],
        )
        report = lint(spec)
        gate_result = next(r for r in report.results if r.rule.id == "approval-gate-missing")
        assert gate_result.passed

    def test_pager_tool_flagged(self):
        spec = _make_spec(
            tools=[ToolSpec(name="pager", description="Page on-call",
                            parameters=ToolParameter(type="object", properties={}, required=[]))],
            policies=PolicySpec(max_turns=5, require_approval=[], forbidden_actions=["x"],
                                escalation=EscalationPolicy(trigger="x", target="y")),
        )
        report = lint(spec)
        gate_result = next(r for r in report.results if r.rule.id == "approval-gate-missing")
        assert not gate_result.passed

    def test_delete_tool_flagged(self):
        spec = _make_spec(
            tools=[ToolSpec(name="delete-record", description="Delete a DB record",
                            parameters=ToolParameter(type="object", properties={}, required=[]))],
            policies=PolicySpec(max_turns=5, require_approval=[], forbidden_actions=["x"],
                                escalation=EscalationPolicy(trigger="x", target="y")),
        )
        report = lint(spec)
        gate_result = next(r for r in report.results if r.rule.id == "approval-gate-missing")
        assert not gate_result.passed


# ---------------------------------------------------------------------------
# Rule: no-forbidden-actions
# ---------------------------------------------------------------------------

class TestForbiddenActions:
    def test_no_forbidden_actions_fails(self):
        spec = _make_spec(
            policies=PolicySpec(max_turns=10, require_approval=[], forbidden_actions=[])
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "no-forbidden-actions")
        assert not r.passed

    def test_with_forbidden_actions_passes(self):
        spec = _make_spec(
            policies=PolicySpec(
                max_turns=10, require_approval=[], forbidden_actions=["Never share PII"],
                escalation=EscalationPolicy(trigger="x", target="y"),
            )
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "no-forbidden-actions")
        assert r.passed


# ---------------------------------------------------------------------------
# Rule: missing-max-turns
# ---------------------------------------------------------------------------

class TestMaxTurns:
    def test_no_max_turns_fails(self):
        spec = _make_spec(
            policies=PolicySpec(
                max_turns=None, require_approval=[], forbidden_actions=["x"],
                escalation=EscalationPolicy(trigger="x", target="y"),
            )
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "missing-max-turns")
        assert not r.passed

    def test_with_max_turns_passes(self):
        report = lint(_full_spec())
        r = next(x for x in report.results if x.rule.id == "missing-max-turns")
        assert r.passed


# ---------------------------------------------------------------------------
# Rule: no-escalation-path
# ---------------------------------------------------------------------------

class TestEscalation:
    def test_no_escalation_fails(self):
        # Empty trigger string = no escalation path configured
        spec = _make_spec(
            policies=PolicySpec(
                max_turns=10, require_approval=[], forbidden_actions=["x"],
                escalation=EscalationPolicy(trigger="", target=""),
            )
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "no-escalation-path")
        assert not r.passed

    def test_with_escalation_passes(self):
        report = lint(_full_spec())
        r = next(x for x in report.results if x.rule.id == "no-escalation-path")
        assert r.passed


# ---------------------------------------------------------------------------
# Rule: thin-instructions
# ---------------------------------------------------------------------------

class TestThinInstructions:
    def test_short_instructions_fail(self):
        spec = _make_spec(instructions="Be helpful.")
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "thin-instructions")
        assert not r.passed
        assert "word" in r.detail

    def test_long_instructions_pass(self):
        long_instructions = " ".join(["word"] * 40)
        spec = _make_spec(instructions=long_instructions)
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "thin-instructions")
        assert r.passed


# ---------------------------------------------------------------------------
# Rule: no-fallback-model
# ---------------------------------------------------------------------------

class TestFallbackModel:
    def test_no_fallback_fails(self):
        spec = _make_spec(model=ModelConfig(preferred="claude-sonnet-4"))
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "no-fallback-model")
        assert not r.passed

    def test_with_fallback_passes(self):
        spec = _make_spec(model=ModelConfig(preferred="claude-sonnet-4", fallback="gpt-4o"))
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "no-fallback-model")
        assert r.passed

    def test_fallback_is_info_severity(self):
        r = next(x for x in RULES if x.id == "no-fallback-model")
        assert r.severity == Severity.INFO


# ---------------------------------------------------------------------------
# Rule: tools-missing-required
# ---------------------------------------------------------------------------

class TestToolsRequired:
    def test_multi_property_tool_without_required_fails(self):
        spec = _make_spec(
            tools=[
                ToolSpec(
                    name="create-ticket",
                    description="Create a ticket",
                    parameters=ToolParameter(
                        type="object",
                        properties={
                            "title": {"type": "string"},
                            "priority": {"type": "string"},
                        },
                        required=[],  # empty = missing required fields
                    ),
                )
            ]
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "tools-missing-required")
        assert not r.passed

    def test_single_property_tool_ok(self):
        spec = _make_spec(
            tools=[
                ToolSpec(
                    name="search",
                    description="Search",
                    parameters=ToolParameter(
                        type="object",
                        properties={"query": {"type": "string"}},
                        required=[],  # single property, no required needed
                    ),
                )
            ]
        )
        report = lint(spec)
        r = next(x for x in report.results if x.rule.id == "tools-missing-required")
        assert r.passed


# ---------------------------------------------------------------------------
# LintReport structure
# ---------------------------------------------------------------------------

class TestLintReport:
    def test_report_has_all_rule_results(self):
        report = lint(_full_spec())
        rule_ids = {r.rule.id for r in report.results}
        expected_ids = {r.id for r in RULES}
        assert rule_ids == expected_ids

    def test_to_dict_structure(self):
        report = lint(_full_spec())
        d = report.to_dict()
        assert "spec" in d
        assert "score" in d
        assert "grade" in d
        assert "results" in d
        for result in d["results"]:
            assert "rule" in result
            assert "severity" in result
            assert "passed" in result

    def test_errors_and_warnings_helpers(self):
        spec = _make_spec(
            instructions="Short.",
            policies=PolicySpec(max_turns=None, require_approval=[], forbidden_actions=[]),
        )
        report = lint(spec)
        assert isinstance(report.errors, list)
        assert isinstance(report.warnings, list)
        assert isinstance(report.infos, list)
