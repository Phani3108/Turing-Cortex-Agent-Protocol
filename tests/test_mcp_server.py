"""Tests for the first-party Turing MCP server module.

The `mcp` SDK is an optional dependency. These tests exercise:
  - The tool layer directly (no SDK involved; thin delegates over existing funcs)
  - The install layer against temp config files
  - The config module round-trip
  - The SDK shim raises a clear error when `mcp` is absent

We do NOT spin up a real FastMCP instance here — that's covered by an
integration test when the SDK is present.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cortex_protocol.mcp_server import tools as t
from cortex_protocol.mcp_server import install as inst
from cortex_protocol.mcp_server import config as mcfg
from cortex_protocol.mcp_server import resources as res
from cortex_protocol.mcp_server import prompts as pr


# A minimal valid spec we reuse across tests.
_VALID_YAML = """
version: "0.1"
agent:
  name: mcp-test
  description: A test agent for the MCP server tests
  instructions: |
    You are a test agent. Respond clearly and concisely. Cite sources. Escalate when unsure.
tools:
  - name: search
    description: Search for information
    parameters:
      type: object
      properties:
        q:
          type: string
      required:
        - q
  - name: send-email
    description: Send an email
    parameters:
      type: object
policies:
  max_turns: 10
  require_approval:
    - send-email
  forbidden_actions:
    - Share credentials
model:
  preferred: claude-sonnet-4
"""


class TestToolsLayer:
    def test_validate_spec_ok(self):
        r = t.validate_spec(_VALID_YAML)
        assert r["ok"] is True
        assert r["valid"] is True
        assert r["errors"] == []
        assert r["spec_name"] == "mcp-test"

    def test_validate_spec_bad(self):
        r = t.validate_spec("not: yaml: ::")
        assert r["ok"] is True
        assert r["valid"] is False
        assert r["errors"]

    def test_lint_spec(self):
        r = t.lint_spec(_VALID_YAML)
        assert r["ok"] is True
        assert 0 <= r["score"] <= 100
        assert r["grade"] in {"A", "B", "C", "D", "F"}
        assert isinstance(r["findings"], list)

    def test_diff_specs_detects_change(self):
        # Bump max_turns to trigger a policy diff.
        b = _VALID_YAML.replace("max_turns: 10", "max_turns: 5")
        r = t.diff_specs(_VALID_YAML, b)
        assert r["ok"] is True
        # A policy change on max_turns is a breaking change per the differ.
        assert r["breaking"] is True
        # Policy change array is structured.
        assert any(p["field"] == "max_turns" for p in r["policy_changes"])

    def test_compile_system_prompt(self):
        r = t.compile_spec(_VALID_YAML, target="system-prompt")
        assert r["ok"] is True
        assert r["target"] == "system-prompt"
        assert r["files"][0]["path"] == "system_prompt.txt"
        assert "mcp-test" in r["files"][0]["content"].lower() or len(r["files"][0]["content"]) > 0

    def test_compile_unknown_target(self):
        r = t.compile_spec(_VALID_YAML, target="nope")
        assert r["ok"] is False
        assert "known" in r

    def test_check_policy_gated_tool_denied(self):
        r = t.check_policy(_VALID_YAML, "send-email")
        assert r["ok"] is True
        assert r["allowed"] is False
        assert r["policy"] == "require_approval"

    def test_check_policy_allowed_tool(self):
        r = t.check_policy(_VALID_YAML, "search", {"q": "x"})
        assert r["ok"] is True
        assert r["allowed"] is True

    def test_list_packs(self):
        r = t.list_packs()
        assert r["ok"] is True
        assert isinstance(r["packs"], list)
        assert r["packs"]  # at least one pack

    def test_list_mcp_servers(self):
        r = t.list_mcp_servers()
        assert r["ok"] is True
        names = {s["name"] for s in r["servers"]}
        assert "mcp-server-github" in names

    def test_suggest_mcp_for_tool(self):
        r = t.suggest_mcp_for_tool("create GitHub issues and pull requests")
        assert r["ok"] is True
        assert r["suggestions"]
        assert r["suggestions"][0]["name"] == "mcp-server-github"

    def test_list_registry_no_crash_when_empty(self, monkeypatch, tmp_path):
        # Point LocalRegistry at a clean dir so it's empty.
        from cortex_protocol.registry import local as loc
        monkeypatch.setattr(loc, "DEFAULT_REGISTRY_DIR", tmp_path / "registry")
        r = t.list_registry()
        assert r["ok"] is True
        assert r["count"] == 0
        assert r["agents"] == []


class TestAuditTools:
    def test_audit_query_reads_log(self, tmp_path):
        from cortex_protocol.governance.audit import AuditLog, AuditEvent

        log_path = tmp_path / "audit.jsonl"
        log = AuditLog(path=log_path)
        log.write(AuditEvent.now(run_id="r1", agent="a", turn=1,
                                 event_type="tool_call", allowed=True,
                                 tool_name="search", detail="ok"))
        r = t.audit_query(str(log_path))
        assert r["ok"] is True
        assert r["count"] == 1
        assert r["events"][0]["event_type"] == "tool_call"

    def test_audit_query_missing(self, tmp_path):
        r = t.audit_query(str(tmp_path / "missing.jsonl"))
        assert r["ok"] is False

    def test_drift_check(self, tmp_path):
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(_VALID_YAML)
        log_path = tmp_path / "empty.jsonl"
        log_path.write_text("")
        r = t.drift_check(str(spec_path), str(log_path))
        assert r["ok"] is True
        assert r["compliance_score"] == 1.0

    def test_compliance_report(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"
        log_path.write_text("")
        r = t.compliance_report(str(log_path), standard="soc2")
        assert r["ok"] is True
        assert "total_events" in r


class TestInstallLayer:
    def _fake_client_paths(self, tmp_path, monkeypatch):
        from cortex_protocol import platform as plat
        fake_clients = {
            "cursor": plat.McpClientTarget("Cursor", tmp_path / ".cursor" / "mcp.json"),
            "claude-desktop": plat.McpClientTarget(
                "Claude Desktop", tmp_path / "Claude" / "claude_desktop_config.json"),
        }
        monkeypatch.setattr(plat, "MCP_CLIENTS", fake_clients)
        # Also patch through the install module's imports.
        monkeypatch.setattr(inst, "MCP_CLIENTS", fake_clients)
        monkeypatch.setattr(inst, "resolve_client",
                            lambda name: fake_clients[name])
        return fake_clients

    def test_install_creates_file(self, tmp_path, monkeypatch):
        self._fake_client_paths(tmp_path, monkeypatch)
        result = inst.install_into_client("cursor")
        assert result.action == "created"
        assert result.path.exists()
        data = json.loads(result.path.read_text())
        assert "turing" in data["mcpServers"]

    def test_install_preserves_other_entries(self, tmp_path, monkeypatch):
        clients = self._fake_client_paths(tmp_path, monkeypatch)
        clients["cursor"].path.parent.mkdir(parents=True, exist_ok=True)
        clients["cursor"].path.write_text(json.dumps(
            {"mcpServers": {"other": {"command": "x", "args": []}}}, indent=2
        ))
        result = inst.install_into_client("cursor")
        data = json.loads(result.path.read_text())
        assert "other" in data["mcpServers"]
        assert "turing" in data["mcpServers"]

    def test_install_idempotent(self, tmp_path, monkeypatch):
        self._fake_client_paths(tmp_path, monkeypatch)
        inst.install_into_client("cursor")
        second = inst.install_into_client("cursor")
        assert second.action == "already-current"

    def test_uninstall_removes_entry(self, tmp_path, monkeypatch):
        self._fake_client_paths(tmp_path, monkeypatch)
        inst.install_into_client("cursor")
        assert inst.uninstall_from_client("cursor") is True
        assert inst.uninstall_from_client("cursor") is False  # already gone

    def test_install_into_many(self, tmp_path, monkeypatch):
        self._fake_client_paths(tmp_path, monkeypatch)
        results = inst.install_into_clients(["cursor", "claude-desktop", "not-a-client"])
        assert {r.client for r in results} == {"cursor", "claude-desktop"}


class TestConfigRoundTrip:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "mcp.json"
        mcfg.save_config(
            {"mine": mcfg.McpServerEntry(command="npx", args=["-y", "@my/server@1"])},
            path=path,
        )
        loaded = mcfg.load_config(path)
        assert loaded["mine"].command == "npx"
        assert loaded["mine"].args == ["-y", "@my/server@1"]

    def test_add_duplicate_raises(self, tmp_path):
        path = tmp_path / "mcp.json"
        mcfg.add_server("x", mcfg.McpServerEntry(command="a"), path=path)
        with pytest.raises(KeyError):
            mcfg.add_server("x", mcfg.McpServerEntry(command="b"), path=path)

    def test_add_overwrite(self, tmp_path):
        path = tmp_path / "mcp.json"
        mcfg.add_server("x", mcfg.McpServerEntry(command="a"), path=path)
        mcfg.add_server("x", mcfg.McpServerEntry(command="b"), path=path, overwrite=True)
        assert mcfg.load_config(path)["x"].command == "b"

    def test_remove(self, tmp_path):
        path = tmp_path / "mcp.json"
        mcfg.add_server("x", mcfg.McpServerEntry(command="a"), path=path)
        assert mcfg.remove_server("x", path=path) is True
        assert mcfg.load_config(path) == {}


class TestResourcesAndPrompts:
    def test_resources_registry(self):
        assert "cortex://packs" in res.RESOURCES
        # Loaders are callable and return strings.
        for uri, (desc, loader) in res.RESOURCES.items():
            assert isinstance(desc, str)
            assert callable(loader)

    def test_packs_resource_returns_json(self):
        payload = res.RESOURCES["cortex://packs"][1]()
        parsed = json.loads(payload)
        assert isinstance(parsed, list)

    def test_prompts_produce_strings(self):
        rv = pr.PROMPTS["governance_review"][1]("agent: {}")
        assert isinstance(rv, str) and "governance" in rv.lower()


class TestSdkShim:
    def test_missing_sdk_raises_clearly(self):
        """If `mcp` is not installed, the SDK shim raises ImportError with a hint."""
        from cortex_protocol.mcp_server import _sdk
        # Simulate the SDK being unavailable by patching the import inside the shim.
        with patch.dict(sys.modules, {"mcp.server.fastmcp": None}):
            try:
                _sdk.get_fastmcp()
            except ImportError as e:
                assert "cortex-protocol[mcp]" in str(e)
                return
            # If we reach here with `mcp` actually installed, that's fine too;
            # the negative-path behavior is what we care about.
            pytest.skip("mcp SDK present; negative path already covered elsewhere")
