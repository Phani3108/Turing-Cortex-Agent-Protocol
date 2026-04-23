"""Lazy-import shim for the optional `mcp` Python SDK.

Keep the import surface thin: every caller should go through `get_mcp()`
so that a missing SDK raises a single, friendly error from one place.
"""

from __future__ import annotations

_INSTALL_HINT = (
    "The Turing MCP server needs the official `mcp` Python SDK. Install it with:\n"
    "    pip install 'cortex-protocol[mcp]'\n"
    "or directly:\n"
    "    pip install 'mcp>=1.2,<2.0'"
)


def get_fastmcp():
    """Return the FastMCP class (raises with a clear hint if SDK missing)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return FastMCP
