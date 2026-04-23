"""Per-OS path resolution for Turing (Cortex Protocol).

All path-dependent code should route through these helpers instead of
hardcoding `~/.cortex-protocol` or probing `sys.platform` in-place. The
functions here resolve:

  - Config / data / cache dirs for Turing itself
  - MCP client config files (Cursor, Claude Desktop, VS Code, Windsurf)
  - Executable lookups (node/npx) with friendly error messages

Conventions:
  - macOS  : ~/Library/Application Support/<app>
  - Linux  : $XDG_CONFIG_HOME or ~/.config/<app>   (XDG spec)
  - Windows: %APPDATA%/<app>
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_NAME = "cortex-protocol"
"""Canonical on-disk app directory name. Must NOT change — persisted state."""


# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------

def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


# ---------------------------------------------------------------------------
# Turing's own directories
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    """Per-user config dir for Turing itself. Created on demand by callers."""
    if is_windows():
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / APP_NAME
    if is_macos():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # Linux / other POSIX — XDG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) / APP_NAME if xdg else Path.home() / ".config" / APP_NAME


def data_dir() -> Path:
    """Per-user data dir (registry, license file, credentials)."""
    if is_windows():
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / APP_NAME
    if is_macos():
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) / APP_NAME if xdg else Path.home() / ".local" / "share" / APP_NAME


def cache_dir() -> Path:
    """Per-user cache dir (MCP server package cache, compiled artifacts)."""
    if is_windows():
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(root) / APP_NAME / "Cache"
    if is_macos():
        return Path.home() / "Library" / "Caches" / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg) / APP_NAME if xdg else Path.home() / ".cache" / APP_NAME


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def mcp_cache_dir() -> Path:
    """Where lazily-installed external MCP servers are cached."""
    return cache_dir() / "mcp-cache"


def mcp_config_path() -> Path:
    """Turing's own MCP config (list of registered servers)."""
    return config_dir() / "mcp.json"


def license_path() -> Path:
    """Ed25519-signed license file (created by `cortex-protocol activate`)."""
    return data_dir() / "license.json"


def credentials_path() -> Path:
    """Cortex Cloud OAuth tokens (mode 0600 on POSIX)."""
    return data_dir() / "credentials.json"


# ---------------------------------------------------------------------------
# MCP client config paths (for `cortex-protocol mcp connect`)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class McpClientTarget:
    """A known MCP client and the config file we need to merge into.

    `key`: the JSON object key under which mcpServers are nested (usually
    "mcpServers", always in the top level). None means top-level.
    """

    name: str
    path: Path
    key: str = "mcpServers"


def _claude_desktop_config() -> Path:
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if is_windows():
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "Claude" / "claude_desktop_config.json"
    # Linux (Claude Desktop is not officially distributed here, but some users
    # run it via unofficial builds that drop config here).
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _cursor_config() -> Path:
    # Cursor uses the same path on every OS.
    return Path.home() / ".cursor" / "mcp.json"


def _windsurf_config() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


def _vscode_config() -> Path:
    """VS Code user-scope MCP config (stable channel)."""
    if is_macos():
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if is_windows():
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "Code" / "User" / "mcp.json"
    return Path.home() / ".config" / "Code" / "User" / "mcp.json"


MCP_CLIENTS: dict[str, McpClientTarget] = {
    "claude-desktop": McpClientTarget("Claude Desktop", _claude_desktop_config()),
    "cursor":         McpClientTarget("Cursor",         _cursor_config()),
    "vscode":         McpClientTarget("VS Code",        _vscode_config()),
    "windsurf":       McpClientTarget("Windsurf",       _windsurf_config()),
}


def detect_installed_clients() -> list[str]:
    """Return the subset of MCP_CLIENTS whose config directory exists.

    Existence of the parent directory is a better signal than existence of
    the file itself — the file is often created lazily by the client on
    first use.
    """
    detected = []
    for key, target in MCP_CLIENTS.items():
        if target.path.parent.exists():
            detected.append(key)
    return detected


def resolve_client(name: str) -> McpClientTarget:
    key = name.strip().lower()
    if key not in MCP_CLIENTS:
        raise KeyError(
            f"Unknown MCP client '{name}'. Known: {', '.join(sorted(MCP_CLIENTS))}"
        )
    return MCP_CLIENTS[key]


# ---------------------------------------------------------------------------
# Executable lookups
# ---------------------------------------------------------------------------

def find_executable(name: str) -> Optional[str]:
    """Cross-platform `which`. Returns absolute path or None."""
    return shutil.which(name)


def require_node_and_npx() -> tuple[str, str]:
    """Return (node_path, npx_path) or raise a clear error with install hint."""
    node = find_executable("node")
    npx = find_executable("npx")
    if node and npx:
        return node, npx
    hint = {
        "darwin": "brew install node",
        "win32":  "winget install OpenJS.NodeJS  (or https://nodejs.org/)",
    }.get(sys.platform, "your package manager (apt install nodejs, etc.) or https://nodejs.org/")
    raise RuntimeError(
        "Turing needs Node.js (with `npx`) to run external MCP servers. "
        f"Install it with: {hint}"
    )
