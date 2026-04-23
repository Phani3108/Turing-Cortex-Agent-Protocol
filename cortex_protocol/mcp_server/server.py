"""FastMCP app assembly for the Turing MCP server.

One place, one function, fully deterministic output — call `build_server()`
to get an instance that has every Turing tool, resource, and prompt
registered on it.
"""

from __future__ import annotations

from ._sdk import get_fastmcp
from .tools import TURING_TOOLS


def build_server(name: str = "turing"):
    """Return a configured FastMCP instance ready to `.run(...)`."""
    FastMCP = get_fastmcp()
    from .. import __version__

    mcp = FastMCP(
        name=name,
        instructions=(
            "Turing governance tools. Use these to validate, lint, compile, "
            "diff, and enforce policy on Cortex Protocol agent specs, and to "
            "inspect audit logs, compliance posture, and registered MCP servers."
        ),
    )

    for tool_name, fn, description in TURING_TOOLS:
        # FastMCP expects the Python function to carry its own __name__;
        # we override the exposed MCP tool name and description for consistency.
        mcp.tool(name=f"cortex.{tool_name}", description=description)(fn)

    _register_resources(mcp)
    _register_prompts(mcp)

    return mcp


def _register_resources(mcp) -> None:
    from .resources import RESOURCES

    for uri, (description, loader) in RESOURCES.items():
        @mcp.resource(uri=uri, description=description)
        def _handler(_loader=loader):  # capture loader per-iteration
            return _loader()


def _register_prompts(mcp) -> None:
    from .prompts import PROMPTS

    for name, (description, fn) in PROMPTS.items():
        mcp.prompt(name=name, description=description)(fn)
