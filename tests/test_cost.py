"""Tests for cost governance: ModelPricing, CostTracker, and enforcer budget caps."""

import json
from pathlib import Path

import pytest

from cortex_protocol.models import (
    AgentSpec, AgentIdentity, ToolSpec, ToolParameter, PolicySpec,
    ModelConfig,
)
from cortex_protocol.governance.cost import (
    CostTracker, ModelPricing, ModelPrice, aggregate_samples, UsageSample,
)
from cortex_protocol.governance.enforcer import PolicyEnforcer
from cortex_protocol.governance.audit import AuditLog
from cortex_protocol.governance.exceptions import BudgetExceeded


def _spec(*, max_cost_usd=None, max_tokens_per_run=None, max_tool_calls_per_run=None,
          tools=None, require_approval=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(
            name="cost-test",
            description="Cost test agent",
            instructions="Test. " * 20,
        ),
        tools=tools or [
            ToolSpec(name="search", description="Search",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="send-email", description="Email",
                     parameters=ToolParameter(type="object")),
        ],
        policies=PolicySpec(
            max_turns=100,
            require_approval=require_approval or [],
            max_cost_usd=max_cost_usd,
            max_tokens_per_run=max_tokens_per_run,
            max_tool_calls_per_run=max_tool_calls_per_run,
        ),
        model=ModelConfig(preferred="claude-sonnet-4"),
    )


# ---------------------------------------------------------------------------
# ModelPricing
# ---------------------------------------------------------------------------

class TestModelPricing:
    def test_known_model_price(self):
        p = ModelPricing().for_model("claude-sonnet-4")
        assert isinstance(p, ModelPrice)
        assert p.cost(1_000_000, 0) == pytest.approx(3.0)
        assert p.cost(0, 1_000_000) == pytest.approx(15.0)

    def test_family_prefix_match(self):
        # Dated model id should match the family.
        p = ModelPricing().for_model("claude-sonnet-4-6-20250401")
        assert p.cost(1_000_000, 0) == pytest.approx(3.0)

    def test_unknown_model_falls_back_pessimistic(self):
        p = ModelPricing().for_model("imaginary-model-xyz")
        # Pessimistic Opus-tier pricing.
        assert p.cost(1_000_000, 0) == pytest.approx(15.0)

    def test_override_wins_over_builtin(self):
        p = ModelPricing(overrides={"claude-sonnet-4": (1.0, 2.0)}).for_model("claude-sonnet-4")
        assert p.cost(1_000_000, 1_000_000) == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------

class TestCostTracker:
    def test_record_accumulates(self):
        tr = CostTracker()
        tr.record("gpt-4o-mini", input_tokens=1000, output_tokens=500)
        tr.record("gpt-4o-mini", input_tokens=2000, output_tokens=200)
        snap = tr.snapshot
        assert snap.total_input_tokens == 3000
        assert snap.total_output_tokens == 700
        assert snap.total_cost_usd > 0
        assert snap.total_tool_calls == 0  # record() must NOT bump count

    def test_explicit_cost_override(self):
        tr = CostTracker()
        tr.record("gpt-4o-mini", input_tokens=1_000_000, output_tokens=0, cost_usd=0.01)
        assert tr.snapshot.total_cost_usd == pytest.approx(0.01)

    def test_record_tool_call_bumps_count_only(self):
        tr = CostTracker()
        tr.record_tool_call("search")
        tr.record_tool_call("send-email")
        snap = tr.snapshot
        assert snap.total_tool_calls == 2
        assert snap.total_cost_usd == 0.0
        assert snap.total_input_tokens == 0

    def test_would_exceed_helpers(self):
        tr = CostTracker()
        tr.record("gpt-4o-mini", input_tokens=1_000_000, output_tokens=0, cost_usd=0.50)
        assert tr.would_exceed_cost(max_cost_usd=0.40)
        assert not tr.would_exceed_cost(max_cost_usd=0.60)
        assert tr.would_exceed_cost(max_cost_usd=0.60, next_call_cost_usd=0.20)
        assert tr.would_exceed_tokens(max_tokens=500_000)
        assert not tr.would_exceed_tokens(max_tokens=2_000_000)

    def test_aggregate_samples_counts_tools(self):
        snap = aggregate_samples([
            UsageSample(model="m", tool_name="search"),
            UsageSample(model="m", tool_name="email"),
            UsageSample(model="m", input_tokens=100, cost_usd=0.01),
        ])
        assert snap.total_tool_calls == 2
        assert snap.total_cost_usd == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# PolicyEnforcer budget enforcement
# ---------------------------------------------------------------------------

class TestEnforcerBudgets:
    def test_cost_cap_raises_after_usage(self):
        spec = _spec(max_cost_usd=0.01)
        e = PolicyEnforcer(spec)
        e.increment_turn()
        # Record usage that exceeds the $0.01 cap. Sonnet-4 input at $3/MTok,
        # so 10,000 input tokens = $0.03 — well over the cap.
        with pytest.raises(BudgetExceeded) as exc:
            e.record_usage(model="claude-sonnet-4", input_tokens=10_000, output_tokens=0)
        assert exc.value.budget_type == "cost_usd"
        assert exc.value.limit == 0.01
        assert exc.value.observed > 0.01

    def test_under_cap_allows(self):
        spec = _spec(max_cost_usd=1.00)
        e = PolicyEnforcer(spec)
        e.increment_turn()
        result = e.record_usage(model="gpt-4o-mini", input_tokens=1_000, output_tokens=500)
        assert result.allowed
        assert e.cost.snapshot.total_cost_usd > 0
        assert e.cost.snapshot.total_cost_usd < 1.00

    def test_token_cap_blocks(self):
        spec = _spec(max_tokens_per_run=1_000)
        e = PolicyEnforcer(spec)
        e.increment_turn()
        with pytest.raises(BudgetExceeded) as exc:
            e.record_usage(model="gpt-4o-mini", input_tokens=800, output_tokens=500)
        assert exc.value.budget_type == "tokens"

    def test_tool_call_cap_blocks_before_execution(self):
        spec = _spec(max_tool_calls_per_run=2)
        e = PolicyEnforcer(spec)
        e.increment_turn()
        e.check_tool_call("search")
        e.check_tool_call("search")
        with pytest.raises(BudgetExceeded) as exc:
            e.check_tool_call("search")
        assert exc.value.budget_type == "tool_calls"
        assert exc.value.limit == 2

    def test_no_caps_never_raises(self):
        spec = _spec()  # no budget fields set
        e = PolicyEnforcer(spec)
        e.increment_turn()
        # Huge usage should pass fine.
        e.record_usage(model="claude-opus-4", input_tokens=10_000_000, output_tokens=1_000_000)
        assert e.cost.snapshot.total_cost_usd > 100  # big spend, no cap, no raise

    def test_audit_log_records_usage_and_budget_block(self, tmp_path):
        spec = _spec(max_cost_usd=0.01)
        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(path=log_path)
        e = PolicyEnforcer(spec, audit_log=log)
        e.increment_turn()
        with pytest.raises(BudgetExceeded):
            e.record_usage(model="claude-sonnet-4", input_tokens=10_000, output_tokens=0)

        # Reload from disk to confirm JSONL is parseable.
        reloaded = AuditLog.from_file(log_path)
        types = [ev.event_type for ev in reloaded.events()]
        assert "usage" in types
        assert "budget_blocked" in types

        usage_events = [ev for ev in reloaded.events() if ev.event_type == "usage"]
        assert usage_events
        u = usage_events[0]
        assert u.input_tokens == 10_000
        assert u.cost_usd is not None
        assert u.model == "claude-sonnet-4"
        assert u.run_cost_usd is not None

    def test_defaults_uses_spec_preferred_model(self):
        spec = _spec(max_cost_usd=10.0)
        e = PolicyEnforcer(spec)
        e.increment_turn()
        e.record_usage(input_tokens=1_000, output_tokens=100)  # no model arg
        sample = e.cost.snapshot.samples[-1]
        assert sample.model == "claude-sonnet-4"

    def test_pricing_overrides_via_constructor(self):
        spec = _spec(max_cost_usd=1.00)
        pricing = ModelPricing(overrides={"claude-sonnet-4": (0.0, 0.0)})
        e = PolicyEnforcer(spec, pricing=pricing)
        e.increment_turn()
        # Free pricing — no matter how many tokens, no cost-cap breach.
        e.record_usage(model="claude-sonnet-4", input_tokens=10_000_000, output_tokens=10_000_000)
        assert e.cost.snapshot.total_cost_usd == 0.0

    def test_existing_enforcer_behavior_unchanged(self):
        """Spec with no cost fields behaves exactly as before v0.4."""
        spec = _spec()
        e = PolicyEnforcer(spec)
        e.increment_turn()
        # check_tool_call still allows non-gated tools.
        r = e.check_tool_call("search")
        assert r.allowed
        # And still rejects approval-gated tools with no handler.
        from cortex_protocol.governance.exceptions import ApprovalRequired
        spec2 = _spec(require_approval=["send-email"])
        e2 = PolicyEnforcer(spec2)
        e2.increment_turn()
        with pytest.raises(ApprovalRequired):
            e2.check_tool_call("send-email")


# ---------------------------------------------------------------------------
# CLI cost-report smoke test
# ---------------------------------------------------------------------------

def test_cli_cost_report(tmp_path):
    from click.testing import CliRunner
    from cortex_protocol.cli import main

    spec = _spec(max_cost_usd=10.0)
    log_path = tmp_path / "audit.jsonl"
    log = AuditLog(path=log_path)
    e = PolicyEnforcer(spec, audit_log=log)
    e.increment_turn()
    e.record_usage(model="claude-sonnet-4", input_tokens=1000, output_tokens=200)
    e.record_usage(model="gpt-4o-mini", input_tokens=5000, output_tokens=500)

    runner = CliRunner()
    result = runner.invoke(main, ["cost-report", str(log_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "buckets" in payload
    assert payload["totals"]["input_tokens"] == 6000
    assert payload["totals"]["output_tokens"] == 700
    assert payload["totals"]["cost_usd"] > 0

    # Group by model should split into two buckets.
    result2 = runner.invoke(main, ["cost-report", str(log_path), "--by", "model", "--format", "json"])
    assert result2.exit_code == 0
    payload2 = json.loads(result2.output)
    assert set(payload2["buckets"].keys()) == {"claude-sonnet-4", "gpt-4o-mini"}
