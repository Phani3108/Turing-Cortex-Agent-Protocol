"""Turing's own MCP config at ~/.cortex-protocol/mcp.json.

Shape-compatible with Claude Desktop's mcpServers block so users can
copy-paste between files. Schema:

    {
      "mcpServers": {
        "<name>": {
          "command": "...",
          "args": ["..."],
          "env": {"KEY": "value"},
          "transport": "stdio"        // optional
        }
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..platform import mcp_config_path, ensure_dir


@dataclass
class McpServerEntry:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"

    def to_dict(self) -> dict:
        d = {"command": self.command, "args": list(self.args)}
        if self.env:
            d["env"] = dict(self.env)
        if self.transport and self.transport != "stdio":
            d["transport"] = self.transport
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "McpServerEntry":
        return cls(
            command=data.get("command", ""),
            args=list(data.get("args", [])),
            env=dict(data.get("env", {})),
            transport=data.get("transport", "stdio"),
        )


def load_config(path: Optional[Path] = None) -> dict[str, McpServerEntry]:
    """Load the user's MCP server map. Missing file => empty dict."""
    p = path or mcp_config_path()
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    servers = raw.get("mcpServers", {})
    return {name: McpServerEntry.from_dict(cfg) for name, cfg in servers.items()}


def save_config(servers: dict[str, McpServerEntry], path: Optional[Path] = None) -> Path:
    """Persist the MCP server map. Creates parent dirs as needed."""
    p = path or mcp_config_path()
    ensure_dir(p.parent)
    payload = {"mcpServers": {name: entry.to_dict() for name, entry in servers.items()}}
    p.write_text(json.dumps(payload, indent=2) + "\n")
    return p


def add_server(name: str, entry: McpServerEntry, *, path: Optional[Path] = None,
               overwrite: bool = False) -> Path:
    servers = load_config(path)
    if name in servers and not overwrite:
        raise KeyError(f"MCP server '{name}' already registered. Use overwrite=True to replace.")
    servers[name] = entry
    return save_config(servers, path)


def remove_server(name: str, *, path: Optional[Path] = None) -> bool:
    servers = load_config(path)
    if name not in servers:
        return False
    servers.pop(name)
    save_config(servers, path)
    return True
