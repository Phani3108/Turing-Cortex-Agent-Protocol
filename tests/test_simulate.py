"""Tests for the simulation / red-team harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.models import (
    AgentIdentity, AgentSpec, ModelConfig, PolicySpec, ToolParameter, ToolSpec,
)
from cortex_protocol.simulate import (
    Scenario,
    ScenarioStep,
    load_scenarios,
    run_scenarios,
)
from cortex_protocol.simulate.harness import BUNDLED_SCENARIOS_DIR, ScenarioExpectation


def _spec(require_approval=None, forbidden_actions=None, max_cost_usd=None, tools=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name="sim-test", description="t",
                             instructions="Answer concisely. Cite sources. Escalate when unsure."),
        tools=tools or [
            ToolSpec(name="search", description="",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="process-refund", description="",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="delete-database", description="",
                     parameters=ToolParameter(type="object")),
        ],
        policies=PolicySpec(
            max_turns=10,
            require_approval=require_approval or [],
            forbidden_actions=forbidden_actions or [],
            max_cost_usd=max_cost_usd,
        ),
        model=ModelConfig(preferred="claude-sonnet-4"),
    )


class TestLoading:
    def test_bundled_scenarios_present(self):
        scenarios = load_scenarios()
        ids = {s.id for s in scenarios}
        assert "pi-001" in ids  # ignore-previous-instructions
        assert "ex-001" in ids  # credential exfil

    def test_loads_single_file(self, tmp_path):
        src = tmp_path / "x.yaml"
        src.write_text("""
- id: custom-1
  name: "Custom scenario"
  category: custom
  severity: low
  steps:
    - kind: tool_call
      tool_name: search
  expected:
    block_tools: []
""")
        scenarios = load_scenarios([src], include_bundled=False)
        assert len(scenarios) == 1 and scenarios[0].id == "custom-1"

    def test_loads_directory(self, tmp_path):
        (tmp_path / "a.yaml").write_text("""
id: single-1
name: one
category: a
steps: []
expected: {}
""")
        (tmp_path / "b.yaml").write_text("""
id: single-2
name: two
category: b
steps: []
expected: {}
""")
        scenarios = load_scenarios([tmp_path], include_bundled=False)
        ids = {s.id for s in scenarios}
        assert ids == {"single-1", "single-2"}

    def test_no_bundled_flag(self, tmp_path):
        scenarios = load_scenarios([tmp_path], include_bundled=False)
        assert scenarios == []

    def test_single_scenario_file_format(self, tmp_path):
        # Some files contain a single scenario (not a list). Both should work.
        (tmp_path / "one.yaml").write_text("""
id: lone-1
name: lone
category: x
steps: []
expected: {}
""")
        scenarios = load_scenarios([tmp_path], include_bundled=False)
        assert len(scenarios) == 1


class TestRunner:
    def test_passing_scenario(self):
        # Spec gates process-refund; scenario expects that gating to fire.
        spec = _spec(require_approval=["process-refund"])
        scenarios = [Scenario(
            id="t-1", name="t", category="test",
            steps=[ScenarioStep(kind="tool_call", tool_name="process-refund")],
            expected=ScenarioExpectation(block_tools=["process-refund"],
                                         require_approval_hit=True),
        )]
        report = run_scenarios(spec, scenarios)
        assert report.passed == 1 and report.failed == 0
        assert "process-refund" in report.results[0].blocked_tools

    def test_failing_scenario(self):
        # Spec does NOT gate process-refund; the scenario expects it to.
        spec = _spec()
        scenarios = [Scenario(
            id="t-2", name="t", category="test",
            steps=[ScenarioStep(kind="tool_call", tool_name="process-refund")],
            expected=ScenarioExpectation(block_tools=["process-refund"]),
        )]
        report = run_scenarios(spec, scenarios)
        assert report.failed == 1
        assert any("[FAIL]" in f for f in report.results[0].findings)

    def test_forbidden_match_fires(self):
        spec = _spec(forbidden_actions=["share card number"])
        scenarios = [Scenario(
            id="t-3", name="t", category="test",
            steps=[ScenarioStep(kind="response",
                                 text="Here is my card number 4111...")],
            expected=ScenarioExpectation(forbidden_match=["share card number"]),
        )]
        report = run_scenarios(spec, scenarios)
        assert report.passed == 1

    def test_budget_cap_fires(self):
        spec = _spec(max_cost_usd=0.01)
        scenarios = [Scenario(
            id="t-4", name="t", category="test",
            steps=[
                ScenarioStep(kind="usage", model="claude-opus-4",
                             input_tokens=100_000, output_tokens=0,
                             cost_usd=1.50),
                ScenarioStep(kind="tool_call", tool_name="search"),
            ],
            expected=ScenarioExpectation(budget_block=True),
        )]
        report = run_scenarios(spec, scenarios)
        assert report.passed == 1
        assert report.results[0].budget_blocked

    def test_bundled_pi_001_against_strong_spec_passes(self):
        # Spec that gates process-refund and delete-database.
        spec = _spec(require_approval=["process-refund", "delete-database"])
        scenarios = [s for s in load_scenarios() if s.id in {"pi-001", "pi-002"}]
        report = run_scenarios(spec, scenarios)
        assert report.passed >= 2


class TestCLI:
    def test_simulate_cli(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec = _spec(require_approval=["process-refund", "delete-database"])
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec.to_yaml())

        runner = CliRunner()
        result = runner.invoke(main, ["simulate", str(spec_path), "--format", "json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["total"] >= 1
        # Spec above should pass pi-001 and pi-002 at minimum.
        passed_ids = {r["scenario_id"] for r in payload["results"] if r["passed"]}
        assert "pi-001" in passed_ids and "pi-002" in passed_ids

    def test_simulate_cli_fail_on_miss(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        # Weak spec — bundled scenarios should fail.
        spec = _spec()
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec.to_yaml())

        runner = CliRunner()
        result = runner.invoke(main, [
            "simulate", str(spec_path), "--fail-on-miss",
        ])
        assert result.exit_code == 1
        assert "FAIL" in result.output
