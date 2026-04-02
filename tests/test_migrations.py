"""Tests for schema migrations."""

import tempfile
from pathlib import Path

import yaml
from click.testing import CliRunner

from cortex_protocol.migrations import migrate, MIGRATIONS
from cortex_protocol.migrations.v01_to_v03 import migrate_v01_to_v03
from cortex_protocol.cli import main


_V01_SPEC = {
    "version": "0.1",
    "agent": {
        "name": "old-agent",
        "description": "An old agent",
        "instructions": "Do stuff",
    },
    "tools": [
        {"name": "search", "description": "Search things"},
        {"name": "write", "description": "Write things"},
    ],
    "policies": {"max_turns": 10},
}


def test_v01_to_v03_adds_metadata():
    result = migrate_v01_to_v03(_V01_SPEC)
    assert "metadata" in result


def test_v01_to_v03_updates_version():
    result = migrate_v01_to_v03(_V01_SPEC)
    assert result["version"] == "0.3"


def test_v01_to_v03_adds_mcp_null_on_tools():
    result = migrate_v01_to_v03(_V01_SPEC)
    for tool in result["tools"]:
        assert "mcp" in tool
        assert tool["mcp"] is None


def test_v01_to_v03_adds_extends_null():
    result = migrate_v01_to_v03(_V01_SPEC)
    assert "extends" in result
    assert result["extends"] is None


def test_v01_to_v03_preserves_tools():
    result = migrate_v01_to_v03(_V01_SPEC)
    names = [t["name"] for t in result["tools"]]
    assert "search" in names
    assert "write" in names


def test_migrate_already_v03_unchanged():
    spec = dict(_V01_SPEC)
    spec["version"] = "0.3"
    result = migrate(spec)
    assert result is spec  # returned as-is


def test_migrate_v01_auto_detects_version():
    result = migrate(dict(_V01_SPEC))
    assert result["version"] == "0.3"


def test_migrate_unknown_version_passthrough():
    spec = {"version": "9.9", "agent": {"name": "x", "description": "x", "instructions": "x"}}
    result = migrate(spec)
    assert result["version"] == "9.9"


def test_cli_migrate_command_writes_output():
    runner = CliRunner()
    with runner.isolated_filesystem():
        spec_content = yaml.dump(dict(_V01_SPEC))
        Path("agent.yaml").write_text(spec_content)

        result = runner.invoke(main, ["migrate", "agent.yaml", "--output", "agent_v3.yaml"])
        assert result.exit_code == 0, result.output
        assert "agent_v3.yaml" in result.output

        migrated = yaml.safe_load(Path("agent_v3.yaml").read_text())
        assert migrated["version"] == "0.3"


def test_cli_migrate_in_place_creates_backup():
    runner = CliRunner()
    with runner.isolated_filesystem():
        spec_content = yaml.dump(dict(_V01_SPEC))
        Path("agent.yaml").write_text(spec_content)

        result = runner.invoke(main, ["migrate", "agent.yaml"])
        assert result.exit_code == 0, result.output
        assert ".bak" in result.output

        assert Path("agent.yaml.bak").exists()
        migrated = yaml.safe_load(Path("agent.yaml").read_text())
        assert migrated["version"] == "0.3"
