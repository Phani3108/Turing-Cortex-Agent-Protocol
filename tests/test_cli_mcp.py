"""CLI tests for the `mcp` subcommand group."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from cortex_protocol.cli import main


def test_mcp_list_text():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "list"])
    assert result.exit_code == 0
    assert "mcp-server-github" in result.output


def test_mcp_list_json():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "list", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "builtin" in data and "user" in data
    names = {s["name"] for s in data["builtin"]}
    assert "mcp-server-github" in names


def test_mcp_add_creates_entry(tmp_path, monkeypatch):
    from cortex_protocol.mcp_server import config as mcfg
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(mcfg, "mcp_config_path", lambda: cfg)
    # load_config/save_config in mcp_server.config import mcp_config_path at
    # call time, so monkeypatching platform is enough.
    runner = CliRunner()
    # Options precede positional args; everything after `myserver` is forwarded
    # verbatim to the MCP server (so `-y` is a pass-through, not an option).
    result = runner.invoke(main, [
        "mcp", "add", "-e", "API_KEY=abc",
        "myserver", "npx", "-y", "@myorg/mcp-srv@1.0",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(cfg.read_text())
    entry = payload["mcpServers"]["myserver"]
    assert entry["command"] == "npx"
    assert entry["args"] == ["-y", "@myorg/mcp-srv@1.0"]
    assert entry["env"]["API_KEY"] == "abc"


def test_mcp_add_duplicate_errors(tmp_path, monkeypatch):
    from cortex_protocol.mcp_server import config as mcfg
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(mcfg, "mcp_config_path", lambda: cfg)
    runner = CliRunner()
    runner.invoke(main, ["mcp", "add", "x", "echo"])
    second = runner.invoke(main, ["mcp", "add", "x", "echo"])
    assert second.exit_code != 0
    assert "already registered" in second.output


def test_mcp_add_with_overwrite(tmp_path, monkeypatch):
    from cortex_protocol.mcp_server import config as mcfg
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr(mcfg, "mcp_config_path", lambda: cfg)
    runner = CliRunner()
    runner.invoke(main, ["mcp", "add", "x", "echo", "one"])
    # --overwrite must come BEFORE positional args because the command uses
    # allow_interspersed_args=False so user server args (like `-y`) aren't
    # swallowed as options.
    result = runner.invoke(main, ["mcp", "add", "--overwrite", "x", "echo", "two"])
    assert result.exit_code == 0, result.output
    entry = json.loads(cfg.read_text())["mcpServers"]["x"]
    assert entry["args"] == ["two"]


def test_mcp_connect_dry_run_reports(tmp_path, monkeypatch):
    from cortex_protocol import platform as plat
    from cortex_protocol.mcp_server import install as inst

    fake = {
        "cursor": plat.McpClientTarget("Cursor", tmp_path / "cursor" / "mcp.json"),
    }
    monkeypatch.setattr(plat, "MCP_CLIENTS", fake)
    monkeypatch.setattr(inst, "MCP_CLIENTS", fake)
    monkeypatch.setattr(inst, "resolve_client", lambda n: fake[n])
    monkeypatch.setattr(plat, "detect_installed_clients", lambda: ["cursor"])

    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "connect", "--client", "cursor", "--dry-run"])
    assert result.exit_code == 0
    assert "would-write" in result.output or "cursor" in result.output
    # Dry run must not touch disk.
    assert not fake["cursor"].path.exists()


def test_top_level_connect_alias(tmp_path, monkeypatch):
    from cortex_protocol import platform as plat
    from cortex_protocol.mcp_server import install as inst

    fake = {
        "cursor": plat.McpClientTarget("Cursor", tmp_path / "cursor" / "mcp.json"),
    }
    monkeypatch.setattr(plat, "MCP_CLIENTS", fake)
    monkeypatch.setattr(inst, "MCP_CLIENTS", fake)
    monkeypatch.setattr(inst, "resolve_client", lambda n: fake[n])
    monkeypatch.setattr(plat, "detect_installed_clients", lambda: ["cursor"])

    runner = CliRunner()
    result = runner.invoke(main, ["connect", "--client", "cursor", "--dry-run"])
    assert result.exit_code == 0


def test_mcp_install_requires_server_or_all():
    runner = CliRunner()
    result = runner.invoke(main, ["mcp", "install"])
    assert result.exit_code != 0
    assert "server" in result.output.lower() or "all" in result.output.lower()
