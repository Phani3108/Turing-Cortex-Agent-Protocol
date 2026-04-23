"""First-party Turing MCP server.

Exposes Turing's own capabilities — validate, lint, compile, check_policy,
audit_query, drift_check, compliance_report, registry/pack browsing — as
MCP tools so any MCP client (Cursor, Claude Desktop, VS Code, Windsurf)
can call them natively.

The heavy lifting stays in the existing modules (`compiler`, `validator`,
`linter`, `governance.*`, `registry.*`, `network.mcp`). This package is a
thin adapter layer.

Optional dependency: requires the `mcp` Python SDK.
  pip install cortex-protocol[mcp]

The modules here import lazily so `cortex_protocol.mcp_server` is safe to
import even when the SDK is absent — an error is only raised when
`build_server()` or `serve()` is actually called.
"""

from __future__ import annotations


def build_server(name: str = "turing"):
    """Construct and return a configured FastMCP server instance."""
    from .server import build_server as _build
    return _build(name=name)


def serve(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8077) -> None:
    """Run the Turing MCP server in a blocking loop."""
    from .transports import run
    run(transport=transport, host=host, port=port)


__all__ = ["build_server", "serve"]
