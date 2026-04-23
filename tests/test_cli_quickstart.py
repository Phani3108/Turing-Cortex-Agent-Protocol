"""Tests for the 0.4 quickstart additions: `init --interactive` and `compile --run`."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from cortex_protocol.cli import main


def test_init_non_interactive_writes_spec(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["init", "demo.yaml"])
        assert result.exit_code == 0
        assert Path("demo.yaml").exists()
        # Inline lint message in output — confirms we wired validator+linter in.
        assert "lint:" in result.output


def test_init_interactive_seeds_from_pack(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Answers: name, description, pack choice=1 (first pack),
        # compliance tags (blank), max cost (blank).
        stdin = "\n".join([
            "incident-bot",             # agent name
            "Incident response agent",  # description
            "1",                        # pick pack 1
            "",                         # compliance tags (skip)
            "",                         # max cost (skip)
        ]) + "\n"
        result = runner.invoke(main, ["init", "--interactive", "out.yaml"], input=stdin)
        assert result.exit_code == 0, result.output
        # Filename uses the provided agent name, not the positional argument.
        assert Path("incident-bot.yaml").exists()
        content = Path("incident-bot.yaml").read_text()
        assert "incident-bot" in content
        assert "Incident response agent" in content


def test_init_interactive_custom_cost(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        stdin = "\n".join([
            "budget-agent",
            "Test agent with a cost cap",
            "4",       # last choice = "(none — start from default template)"
            "",        # compliance skip
            "0.50",    # max cost
        ]) + "\n"
        result = runner.invoke(main, ["init", "--interactive", "tmp.yaml"], input=stdin)
        assert result.exit_code == 0, result.output
        content = Path("budget-agent.yaml").read_text()
        assert "max_cost_usd" in content and "0.5" in content


def test_compile_run_dry_runs_enforcement(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        runner.invoke(main, ["init", "demo.yaml"])
        result = runner.invoke(main, [
            "compile", "demo.yaml",
            "--target", "system-prompt",
            "--run",
            "--output", "./out",
        ])
        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert "PolicyEnforcer attached" in result.output
        assert "[allowed]" in result.output  # at least one tool passed


def test_compile_run_shows_blocked_approval_gate(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        Path("gated.yaml").write_text('''\
version: "0.1"
agent:
  name: gated
  description: Agent with gated tools
  instructions: You do things. Answer concisely. Escalate when unsure. Always cite sources.
tools:
  - name: send-email
    description: Send mail
    parameters: {type: object}
policies:
  max_turns: 5
  require_approval:
    - send-email
  forbidden_actions: []
model:
  preferred: claude-sonnet-4
''')
        result = runner.invoke(main, [
            "compile", "gated.yaml",
            "--target", "system-prompt",
            "--run",
            "--output", "./out",
        ])
        assert result.exit_code == 0, result.output
        assert "[blocked]" in result.output
        assert "send-email" in result.output
