"""Transport selection for the Turing MCP server.

Two transports are supported:

  - `stdio`           : for desktop MCP clients (Cursor, Claude Desktop,
                        VS Code, Windsurf). Default.
  - `streamable-http` : for remote / server deployments.

Isolate all SDK calls here so a future MCP spec change (SSE -> streamable,
etc.) lands in one file instead of scattering across the codebase.
"""

from __future__ import annotations


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8077) -> None:
    """Blocking: build the server and run it on the chosen transport."""
    from .server import build_server

    if transport not in ("stdio", "streamable-http", "sse"):
        raise ValueError(
            f"Unsupported transport '{transport}'. "
            "Use 'stdio' for desktop clients or 'streamable-http' for remote."
        )

    mcp = build_server()

    if transport == "stdio":
        mcp.run(transport="stdio")
        return

    # HTTP transports accept host/port; the SDK picks up the appropriate
    # ASGI implementation internally.
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport=transport)
