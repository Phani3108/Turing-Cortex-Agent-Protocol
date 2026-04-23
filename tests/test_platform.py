"""Tests for cortex_protocol.platform — per-OS path resolution."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cortex_protocol import platform as plat


class TestDirResolution:
    def test_all_dirs_return_path_objects(self):
        for fn in (plat.config_dir, plat.data_dir, plat.cache_dir,
                   plat.mcp_cache_dir, plat.mcp_config_path,
                   plat.license_path, plat.credentials_path):
            result = fn()
            assert isinstance(result, Path)

    def test_app_name_in_paths(self):
        # The app name must appear in each Turing-owned dir to prevent
        # collisions with other apps' config.
        for fn in (plat.config_dir, plat.data_dir, plat.cache_dir):
            assert plat.APP_NAME in fn().parts

    def test_ensure_dir_creates(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        assert not target.exists()
        plat.ensure_dir(target)
        assert target.exists()

    def test_ensure_dir_is_idempotent(self, tmp_path):
        target = tmp_path / "already" / "exists"
        plat.ensure_dir(target)
        plat.ensure_dir(target)  # must not raise

    def test_xdg_config_home_respected_on_linux(self, monkeypatch, tmp_path):
        if plat.is_windows() or plat.is_macos():
            pytest.skip("XDG is a Linux convention")
        custom = tmp_path / "custom_config"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
        assert plat.config_dir() == custom / plat.APP_NAME


class TestOSDetection:
    def test_exactly_one_os_detected(self):
        hits = [plat.is_macos(), plat.is_windows(), plat.is_linux()]
        assert sum(hits) == 1, f"expected exactly one of mac/win/linux to be True, got {hits}"


class TestMCPClientTargets:
    def test_all_known_clients_resolve(self):
        for key in ("cursor", "claude-desktop", "vscode", "windsurf"):
            t = plat.resolve_client(key)
            assert t.key == "mcpServers"
            assert isinstance(t.path, Path)

    def test_unknown_client_raises(self):
        with pytest.raises(KeyError):
            plat.resolve_client("emacs")

    def test_detect_installed_clients_returns_list(self):
        # Whatever the host has, the result must be a subset of known keys.
        result = plat.detect_installed_clients()
        assert isinstance(result, list)
        assert set(result) <= set(plat.MCP_CLIENTS)

    def test_cursor_path_is_dotcursor(self):
        # Cursor uses the same path everywhere — this is a stable invariant.
        t = plat.resolve_client("cursor")
        assert t.path.name == "mcp.json"
        assert t.path.parent.name == ".cursor"


class TestExecutableLookups:
    def test_find_executable_for_python(self):
        # Python must be on PATH since we're running under it.
        assert plat.find_executable("python") or plat.find_executable(sys.executable.split("/")[-1])

    def test_find_executable_missing(self):
        assert plat.find_executable("definitely-not-a-real-binary-xyz-12345") is None

    def test_require_node_and_npx_raises_when_missing(self):
        with patch.object(plat, "find_executable", return_value=None):
            with pytest.raises(RuntimeError, match="Node.js"):
                plat.require_node_and_npx()
