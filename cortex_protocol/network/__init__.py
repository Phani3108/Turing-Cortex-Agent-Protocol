"""Network layer — MCP tool wiring and A2A multi-agent composition."""

from .mcp import MCPServerRegistry, resolve_mcp_tools, generate_mcp_client_code
from .models import NetworkSpec, AgentRef, Route
from .graph import validate_network, compile_network
from .a2a import generate_a2a_card, generate_a2a_handler

__all__ = [
    "MCPServerRegistry",
    "resolve_mcp_tools",
    "generate_mcp_client_code",
    "NetworkSpec",
    "AgentRef",
    "Route",
    "validate_network",
    "compile_network",
    "generate_a2a_card",
    "generate_a2a_handler",
]
