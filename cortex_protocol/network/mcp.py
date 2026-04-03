"""MCP (Model Context Protocol) server registry and tool wiring.

Provides a bundled registry of well-known MCP servers and generates
MCP client setup code for each compilation target when a tool spec
has an ``mcp`` field set.

Example spec::

    tools:
      - name: jira
        description: Manage Jira tickets
        mcp: "mcp-server-atlassian@2.1.0"

When the compiler encounters ``tool.mcp``, it calls
``generate_mcp_client_code(target, tool)`` which returns framework-specific
code that wires the tool through a real MCP client instead of a TODO stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# MCP server metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MCPServerInfo:
    """Metadata for a known MCP server."""

    name: str
    package: str  # npm/pip package name for installation
    description: str
    transport: str = "stdio"  # stdio | sse | streamable-http
    tools: list[str] = field(default_factory=list)  # tool names it exposes
    env_vars: list[str] = field(default_factory=list)  # required env vars


# ---------------------------------------------------------------------------
# Bundled registry of well-known MCP servers
# ---------------------------------------------------------------------------

_BUILTIN_SERVERS: list[MCPServerInfo] = [
    MCPServerInfo(
        name="mcp-server-atlassian",
        package="@anthropic/mcp-server-atlassian",
        description="Jira and Confluence via Atlassian APIs",
        tools=["jira-search", "jira-create", "jira-update", "confluence-search"],
        env_vars=["ATLASSIAN_API_TOKEN", "ATLASSIAN_EMAIL", "ATLASSIAN_URL"],
    ),
    MCPServerInfo(
        name="mcp-server-github",
        package="@anthropic/mcp-server-github",
        description="GitHub repos, issues, PRs, code search",
        tools=["github-search", "github-create-issue", "github-create-pr", "github-get-file"],
        env_vars=["GITHUB_TOKEN"],
    ),
    MCPServerInfo(
        name="mcp-server-slack",
        package="@anthropic/mcp-server-slack",
        description="Slack channels, messages, and threads",
        tools=["slack-send", "slack-search", "slack-list-channels"],
        env_vars=["SLACK_BOT_TOKEN"],
    ),
    MCPServerInfo(
        name="mcp-server-postgres",
        package="@anthropic/mcp-server-postgres",
        description="PostgreSQL read/write via MCP",
        tools=["sql-query", "sql-execute"],
        env_vars=["DATABASE_URL"],
    ),
    MCPServerInfo(
        name="mcp-server-filesystem",
        package="@anthropic/mcp-server-filesystem",
        description="Local filesystem read/write with sandboxing",
        tools=["file-read", "file-write", "file-list"],
        env_vars=[],
    ),
    MCPServerInfo(
        name="mcp-server-memory",
        package="@anthropic/mcp-server-memory",
        description="Persistent key-value memory store",
        tools=["memory-store", "memory-retrieve", "memory-search"],
        env_vars=[],
    ),
    MCPServerInfo(
        name="mcp-server-puppeteer",
        package="@anthropic/mcp-server-puppeteer",
        description="Browser automation via Puppeteer",
        tools=["browser-navigate", "browser-screenshot", "browser-click"],
        env_vars=[],
    ),
    MCPServerInfo(
        name="mcp-server-stripe",
        package="@anthropic/mcp-server-stripe",
        description="Stripe payments, customers, and subscriptions",
        tools=["stripe-create-charge", "stripe-get-customer", "stripe-list-payments"],
        env_vars=["STRIPE_API_KEY"],
    ),
]


class MCPServerRegistry:
    """Registry of known MCP servers with lookup and resolution."""

    def __init__(self, extra_servers: list[MCPServerInfo] | None = None):
        self._servers: dict[str, MCPServerInfo] = {}
        for server in _BUILTIN_SERVERS:
            self._servers[server.name] = server
        if extra_servers:
            for server in extra_servers:
                self._servers[server.name] = server

    def get(self, name: str) -> MCPServerInfo | None:
        """Look up a server by name (without version)."""
        return self._servers.get(name)

    def list_servers(self) -> list[MCPServerInfo]:
        """Return all known servers."""
        return list(self._servers.values())

    def resolve(self, mcp_ref: str) -> tuple[MCPServerInfo | None, str | None]:
        """Resolve an MCP reference like 'mcp-server-atlassian@2.1.0'.

        Returns (server_info, version) or (None, None) if not found.
        """
        name, version = parse_mcp_ref(mcp_ref)
        server = self._servers.get(name)
        return server, version


# ---------------------------------------------------------------------------
# MCP reference parsing
# ---------------------------------------------------------------------------

def parse_mcp_ref(mcp_ref: str) -> tuple[str, str | None]:
    """Parse 'server-name@version' into (name, version).

    >>> parse_mcp_ref("mcp-server-atlassian@2.1.0")
    ('mcp-server-atlassian', '2.1.0')
    >>> parse_mcp_ref("mcp-server-github")
    ('mcp-server-github', None)
    """
    if "@" in mcp_ref:
        parts = mcp_ref.rsplit("@", 1)
        return parts[0], parts[1]
    return mcp_ref, None


# ---------------------------------------------------------------------------
# Tool resolution helpers
# ---------------------------------------------------------------------------

def resolve_mcp_tools(tools: list, registry: MCPServerRegistry | None = None) -> list[dict]:
    """For a list of ToolSpec objects, resolve MCP references to server info.

    Returns list of dicts: {tool_name, mcp_ref, server_info, version, resolved}.
    """
    reg = registry or MCPServerRegistry()
    results = []
    for tool in tools:
        mcp_ref = getattr(tool, "mcp", None)
        if not mcp_ref:
            results.append({
                "tool_name": tool.name,
                "mcp_ref": None,
                "server_info": None,
                "version": None,
                "resolved": False,
            })
            continue

        server, version = reg.resolve(mcp_ref)
        results.append({
            "tool_name": tool.name,
            "mcp_ref": mcp_ref,
            "server_info": server,
            "version": version,
            "resolved": server is not None,
        })
    return results


# ---------------------------------------------------------------------------
# Code generation for MCP client wiring
# ---------------------------------------------------------------------------

def generate_mcp_client_code(target: str, tool_name: str, mcp_ref: str,
                              registry: MCPServerRegistry | None = None) -> dict[str, str]:
    """Generate framework-specific MCP client code for a tool.

    Args:
        target: Compilation target name (openai-sdk, claude-sdk, etc.)
        tool_name: The tool's name in the spec
        mcp_ref: MCP reference string, e.g. "mcp-server-github@1.0.0"
        registry: Optional custom registry

    Returns:
        Dict with keys:
            - "import": import statements to add
            - "setup": server setup/connection code
            - "call": the tool call implementation (replaces TODO stub)
            - "env_vars": list of required env vars
            - "requirements": additional pip/npm packages needed
    """
    reg = registry or MCPServerRegistry()
    server, version = reg.resolve(mcp_ref)
    name, _ = parse_mcp_ref(mcp_ref)

    server_var = _to_snake(name)
    func_name = _to_snake(tool_name)

    env_vars = server.env_vars if server else []
    env_comment = ""
    if env_vars:
        env_comment = f"# Required env vars: {', '.join(env_vars)}"

    version_pin = f"@{version}" if version else ""
    package = server.package if server else name

    if target in ("openai-sdk",):
        return _gen_openai_mcp(func_name, server_var, name, version_pin, package, env_vars, env_comment)
    elif target in ("claude-sdk",):
        return _gen_claude_mcp(func_name, server_var, name, version_pin, package, env_vars, env_comment)
    elif target in ("langgraph",):
        return _gen_langgraph_mcp(func_name, server_var, name, version_pin, package, env_vars, env_comment)
    elif target in ("crewai",):
        return _gen_crewai_mcp(func_name, server_var, name, version_pin, package, env_vars, env_comment)
    elif target in ("semantic-kernel",):
        return _gen_semantic_kernel_mcp(func_name, server_var, name, version_pin, package, env_vars, env_comment)
    else:
        # system-prompt and unknown targets: just a comment
        return {
            "import": "",
            "setup": f"# MCP: {name}{version_pin} — configure {name} server externally",
            "call": f"# MCP tool: {tool_name} via {name}",
            "env_vars": env_vars,
            "requirements": "",
        }


def _gen_openai_mcp(func: str, server_var: str, name: str, ver: str,
                     package: str, env_vars: list, env_comment: str) -> dict:
    return {
        "import": "from agents.mcp import MCPServerStdio",
        "setup": "\n".join([
            env_comment,
            f'{server_var} = MCPServerStdio(',
            f'    name="{name}",',
            f'    command="npx",',
            f'    args=["-y", "{package}{ver}"],',
            f')',
        ]),
        "call": f'# Tool {func} is auto-provided by MCP server {name}',
        "env_vars": env_vars,
        "requirements": "openai-agents[mcp]>=0.1",
    }


def _gen_claude_mcp(func: str, server_var: str, name: str, ver: str,
                     package: str, env_vars: list, env_comment: str) -> dict:
    return {
        "import": "import subprocess\nimport json",
        "setup": "\n".join([
            env_comment,
            f'# MCP server: {name}{ver}',
            f'# Start with: npx -y {package}{ver}',
            f'{server_var}_command = ["npx", "-y", "{package}{ver}"]',
        ]),
        "call": "\n".join([
            f'def handle_{func}(tool_input: dict) -> str:',
            f'    """Call {name} MCP server for {func}."""',
            f'    # In production, maintain a persistent MCP client connection',
            f'    import subprocess, json',
            f'    result = subprocess.run(',
            f'        {server_var}_command + ["--tool", "{func}", "--input", json.dumps(tool_input)],',
            f'        capture_output=True, text=True, timeout=30,',
            f'    )',
            f'    return result.stdout or result.stderr',
        ]),
        "env_vars": env_vars,
        "requirements": f"# npm: {package}{ver}",
    }


def _gen_langgraph_mcp(func: str, server_var: str, name: str, ver: str,
                        package: str, env_vars: list, env_comment: str) -> dict:
    return {
        "import": "from langchain_mcp_adapters.client import MultiServerMCPClient",
        "setup": "\n".join([
            env_comment,
            f'mcp_client = MultiServerMCPClient({{',
            f'    "{name}": {{',
            f'        "command": "npx",',
            f'        "args": ["-y", "{package}{ver}"],',
            f'        "transport": "stdio",',
            f'    }},',
            f'}})',
        ]),
        "call": f'# Tool {func} is auto-provided by MCP server {name} via langchain adapter',
        "env_vars": env_vars,
        "requirements": "langchain-mcp-adapters>=0.1",
    }


def _gen_crewai_mcp(func: str, server_var: str, name: str, ver: str,
                     package: str, env_vars: list, env_comment: str) -> dict:
    return {
        "import": "from crewai_tools import MCPTool",
        "setup": "\n".join([
            env_comment,
            f'# MCP server: {name}{ver}',
            f'{func}_tool = MCPTool(',
            f'    server_command="npx",',
            f'    server_args=["-y", "{package}{ver}"],',
            f')',
        ]),
        "call": f'# Tool {func} wired through CrewAI MCP adapter',
        "env_vars": env_vars,
        "requirements": "crewai-tools[mcp]>=0.14",
    }


def _gen_semantic_kernel_mcp(func: str, server_var: str, name: str, ver: str,
                              package: str, env_vars: list, env_comment: str) -> dict:
    return {
        "import": "from semantic_kernel.connectors.mcp import MCPStdioPlugin",
        "setup": "\n".join([
            env_comment,
            f'{server_var}_plugin = MCPStdioPlugin(',
            f'    name="{name}",',
            f'    command="npx",',
            f'    args=["-y", "{package}{ver}"],',
            f')',
            f'# Add to kernel: kernel.add_plugin({server_var}_plugin)',
        ]),
        "call": f'# Tool {func} is auto-provided by MCP plugin {name}',
        "env_vars": env_vars,
        "requirements": "semantic-kernel[mcp]>=1.0.0",
    }


def _to_snake(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")
