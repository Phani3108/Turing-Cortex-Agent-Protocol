"""Install the Turing MCP server into each MCP client's config file.

Called by `cortex-protocol mcp connect [--client ...]` and `cortex-protocol
connect`. We always merge rather than overwrite — the user's existing
mcpServers entries from other tools are preserved.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ..platform import MCP_CLIENTS, McpClientTarget, ensure_dir, resolve_client


TURING_ENTRY_NAME = "turing"


def _turing_server_entry(python_executable: Optional[str] = None) -> dict:
    """The mcpServers entry we inject into every client config.

    Uses the `cortex-protocol` CLI if it's on PATH; otherwise falls back to
    the current Python interpreter with `-m cortex_protocol.cli`.
    """
    cli = shutil.which("cortex-protocol") or shutil.which("turing")
    if cli:
        return {"command": cli, "args": ["mcp", "serve", "--transport", "stdio"]}
    python = python_executable or shutil.which("python3") or shutil.which("python") or "python3"
    return {
        "command": python,
        "args": ["-m", "cortex_protocol.cli", "mcp", "serve", "--transport", "stdio"],
    }


@dataclass
class InstallResult:
    client: str
    path: Path
    action: str   # "created" | "updated" | "already-current"
    backup: Optional[Path] = None


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text().strip()
    if not raw:
        return {}
    return json.loads(raw)


def _dump_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2) + "\n")


def install_into_client(
    client: str,
    *,
    entry_name: str = TURING_ENTRY_NAME,
    python_executable: Optional[str] = None,
    overwrite: bool = True,
    dry_run: bool = False,
) -> InstallResult:
    """Write (or update) the Turing server entry into a known MCP client config.

    `overwrite=True` (the default) replaces the existing Turing entry if
    present. Other clients' entries are always preserved.
    """
    target: McpClientTarget = resolve_client(client)
    config = _load_json(target.path)
    servers = config.setdefault(target.key, {})
    new_entry = _turing_server_entry(python_executable=python_executable)

    existing = servers.get(entry_name)
    if existing == new_entry:
        return InstallResult(client=client, path=target.path, action="already-current")

    if existing is not None and not overwrite:
        raise FileExistsError(
            f"Turing entry already present in {target.path}. "
            f"Pass overwrite=True to replace it."
        )

    backup: Optional[Path] = None
    if target.path.exists():
        backup = target.path.with_suffix(target.path.suffix + ".bak")
        shutil.copy2(target.path, backup)

    servers[entry_name] = new_entry

    if dry_run:
        return InstallResult(client=client, path=target.path, action="would-write",
                             backup=backup)

    _dump_json(target.path, config)
    action = "updated" if existing is not None else "created"
    return InstallResult(client=client, path=target.path, action=action, backup=backup)


def install_into_clients(
    clients: Iterable[str],
    *,
    overwrite: bool = True,
    dry_run: bool = False,
) -> list[InstallResult]:
    results = []
    for c in clients:
        try:
            results.append(install_into_client(c, overwrite=overwrite, dry_run=dry_run))
        except KeyError:
            # Unknown client name; skip silently — caller filters ahead of us.
            continue
    return results


def uninstall_from_client(client: str, *, entry_name: str = TURING_ENTRY_NAME) -> bool:
    """Remove the Turing entry from one client's config. Returns True if changed."""
    target = resolve_client(client)
    if not target.path.exists():
        return False
    config = _load_json(target.path)
    servers = config.get(target.key, {})
    if entry_name not in servers:
        return False
    servers.pop(entry_name)
    config[target.key] = servers
    _dump_json(target.path, config)
    return True


def all_known_clients() -> list[str]:
    return sorted(MCP_CLIENTS.keys())
