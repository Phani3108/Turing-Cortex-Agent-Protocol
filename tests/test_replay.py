"""Tests for deterministic replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.governance.audit import AuditEvent, AuditLog
from cortex_protocol.governance.replay import replay
from cortex_protocol.models import (
    AgentIdentity, AgentSpec, ModelConfig, PolicySpec, ToolParameter, ToolSpec,
)


def _spec(require_approval=None, max_turns=10, max_cost_usd=None,
          forbidden_actions=None, tools=None):
    return AgentSpec(
        version="0.1",
        agent=AgentIdentity(name="replay-test", description="t",
                             instructions="You do things. Cite sources. Escalate when unsure."),
        tools=tools or [
            ToolSpec(name="search", description="Search",
                     parameters=ToolParameter(type="object")),
            ToolSpec(name="send-email", description="Email",
                     parameters=ToolParameter(type="object")),
        ],
        policies=PolicySpec(
            max_turns=max_turns,
            require_approval=require_approval or [],
            forbidden_actions=forbidden_actions or [],
            max_cost_usd=max_cost_usd,
        ),
        model=ModelConfig(preferred="claude-sonnet-4"),
    )


def _log_with(events):
    log = AuditLog()
    for e in events:
        log.write(e)
    return log


def _call(run_id, turn, tool, allowed=True, event_type="tool_call"):
    return AuditEvent.now(
        run_id=run_id, agent="replay-test", turn=turn,
        event_type=event_type, allowed=allowed,
        tool_name=tool, detail="",
    )


class TestReplay:
    def test_unchanged_when_spec_matches_history(self):
        spec = _spec()
        log = _log_with([_call("r1", 1, "search")])
        r = replay(spec, log)
        assert r.total_tool_events == 1
        assert r.regression_count == 0
        assert r.unchanged == 1

    def test_newly_blocked_when_spec_tightens(self):
        # Historically allowed; new spec gates send-email behind approval.
        spec = _spec(require_approval=["send-email"])
        log = _log_with([_call("r1", 1, "send-email")])
        r = replay(spec, log)
        assert r.regression_count == 1
        assert len(r.newly_blocked) == 1
        d = r.newly_blocked[0]
        assert d.tool_name == "send-email"
        assert d.replay_policy == "require_approval"

    def test_newly_allowed_when_spec_loosens(self):
        # Historically blocked (allowed=False); new spec allows the tool.
        spec = _spec()  # no approval required
        log = _log_with([_call("r1", 1, "send-email", allowed=False,
                                event_type="tool_blocked")])
        r = replay(spec, log)
        assert len(r.newly_allowed) == 1

    def test_only_tool_events_count(self):
        spec = _spec()
        # Turn-start / response events have no tool_name and must not
        # enter the replay tally.
        events = [
            AuditEvent.now(run_id="r1", agent="a", turn=1,
                           event_type="turn_start", allowed=True),
            AuditEvent.now(run_id="r1", agent="a", turn=1,
                           event_type="response", allowed=True),
            _call("r1", 1, "search"),
        ]
        r = replay(spec, _log_with(events))
        assert r.total_tool_events == 1

    def test_budget_cap_fires_at_same_point(self):
        # A log with a usage event putting spend above the new $0.01 cap;
        # the subsequent tool call should now be newly_blocked.
        spec = _spec(max_cost_usd=0.01)
        events = [
            AuditEvent.now(run_id="r1", agent="a", turn=1,
                           event_type="usage", allowed=True,
                           model="claude-sonnet-4",
                           input_tokens=100_000, output_tokens=0,
                           cost_usd=0.30,
                           run_cost_usd=0.30),
            _call("r1", 1, "search"),
        ]
        r = replay(spec, _log_with(events))
        assert len(r.newly_blocked) == 1
        assert r.newly_blocked[0].replay_policy == "max_cost_usd"

    def test_max_turns_cap_handled(self):
        spec = _spec(max_turns=1)
        events = [
            _call("r1", 1, "search"),
            _call("r1", 2, "search"),   # exceeds max_turns=1
            _call("r1", 3, "search"),
        ]
        r = replay(spec, _log_with(events))
        # Turns 2 and 3 should be newly_blocked.
        assert len(r.newly_blocked) >= 1

    def test_replay_per_run_state_isolation(self):
        # Two independent runs; a budget cap tripping in one must not
        # affect the other.
        spec = _spec(max_cost_usd=0.01)
        events = [
            AuditEvent.now(run_id="r1", agent="a", turn=1,
                           event_type="usage", allowed=True,
                           model="claude-sonnet-4",
                           input_tokens=100_000, output_tokens=0, cost_usd=0.30,
                           run_cost_usd=0.30),
            _call("r1", 1, "search"),   # newly_blocked in r1
            _call("r2", 1, "search"),   # should still be allowed in r2
        ]
        r = replay(spec, _log_with(events))
        assert len(r.newly_blocked) == 1
        assert r.newly_blocked[0].run_id == "r1"

    def test_to_dict_shape(self):
        spec = _spec(require_approval=["send-email"])
        r = replay(spec, _log_with([_call("r1", 1, "send-email")]))
        d = r.to_dict()
        assert d["regression_count"] == 1
        assert d["newly_blocked"][0]["tool_name"] == "send-email"
        assert "newly_allowed" in d and "unchanged" in d


class TestReplayCLI:
    def test_cli_text_output(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec = _spec(require_approval=["send-email"])
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec.to_yaml())
        log_path = tmp_path / "audit.jsonl"
        AuditLog(path=log_path).write(_call("r1", 1, "send-email"))

        runner = CliRunner()
        result = runner.invoke(main, ["replay", str(spec_path), str(log_path)])
        assert result.exit_code == 0
        assert "newly_blocked" in result.output

    def test_cli_fail_on_regression(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec = _spec(require_approval=["send-email"])
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec.to_yaml())
        log_path = tmp_path / "audit.jsonl"
        AuditLog(path=log_path).write(_call("r1", 1, "send-email"))

        runner = CliRunner()
        result = runner.invoke(main, [
            "replay", str(spec_path), str(log_path), "--fail-on-regression",
        ])
        assert result.exit_code == 1

    def test_cli_json_format(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec = _spec()
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(spec.to_yaml())
        log_path = tmp_path / "audit.jsonl"
        AuditLog(path=log_path).write(_call("r1", 1, "search"))

        runner = CliRunner()
        result = runner.invoke(main, [
            "replay", str(spec_path), str(log_path), "--format", "json",
        ])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["total_tool_events"] == 1
