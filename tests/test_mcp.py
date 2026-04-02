"""Tests for MCP server registry and tool wiring (Phase 5)."""

import pytest

from cortex_protocol.network.mcp import (
    MCPServerRegistry,
    MCPServerInfo,
    parse_mcp_ref,
    resolve_mcp_tools,
    generate_mcp_client_code,
)
from cortex_protocol.models import ToolSpec


# ---------------------------------------------------------------------------
# parse_mcp_ref
# ---------------------------------------------------------------------------

class TestParseMcpRef:
    def test_with_version(self):
        name, ver = parse_mcp_ref("mcp-server-atlassian@2.1.0")
        assert name == "mcp-server-atlassian"
        assert ver == "2.1.0"

    def test_without_version(self):
        name, ver = parse_mcp_ref("mcp-server-github")
        assert name == "mcp-server-github"
        assert ver is None

    def test_scoped_package(self):
        name, ver = parse_mcp_ref("mcp-server-stripe@1.0.0")
        assert name == "mcp-server-stripe"
        assert ver == "1.0.0"


# ---------------------------------------------------------------------------
# MCPServerRegistry
# ---------------------------------------------------------------------------

class TestMCPServerRegistry:
    def test_builtin_servers_exist(self):
        reg = MCPServerRegistry()
        servers = reg.list_servers()
        assert len(servers) >= 8

    def test_get_known_server(self):
        reg = MCPServerRegistry()
        server = reg.get("mcp-server-github")
        assert server is not None
        assert server.name == "mcp-server-github"
        assert "GITHUB_TOKEN" in server.env_vars

    def test_get_unknown_returns_none(self):
        reg = MCPServerRegistry()
        assert reg.get("mcp-server-nonexistent") is None

    def test_resolve_with_version(self):
        reg = MCPServerRegistry()
        server, ver = reg.resolve("mcp-server-atlassian@2.1.0")
        assert server is not None
        assert server.name == "mcp-server-atlassian"
        assert ver == "2.1.0"

    def test_resolve_without_version(self):
        reg = MCPServerRegistry()
        server, ver = reg.resolve("mcp-server-slack")
        assert server is not None
        assert ver is None

    def test_resolve_unknown(self):
        reg = MCPServerRegistry()
        server, ver = reg.resolve("mcp-server-nonexistent@1.0.0")
        assert server is None
        assert ver == "1.0.0"

    def test_custom_servers(self):
        custom = MCPServerInfo(
            name="mcp-server-custom",
            package="@my-org/mcp-server-custom",
            description="Custom server",
        )
        reg = MCPServerRegistry(extra_servers=[custom])
        assert reg.get("mcp-server-custom") is not None
        # Builtins still present
        assert reg.get("mcp-server-github") is not None

    def test_known_server_names(self):
        reg = MCPServerRegistry()
        names = {s.name for s in reg.list_servers()}
        assert "mcp-server-atlassian" in names
        assert "mcp-server-github" in names
        assert "mcp-server-slack" in names
        assert "mcp-server-postgres" in names
        assert "mcp-server-filesystem" in names
        assert "mcp-server-memory" in names
        assert "mcp-server-puppeteer" in names
        assert "mcp-server-stripe" in names

    def test_servers_have_required_fields(self):
        reg = MCPServerRegistry()
        for server in reg.list_servers():
            assert server.name
            assert server.package
            assert server.description


# ---------------------------------------------------------------------------
# resolve_mcp_tools
# ---------------------------------------------------------------------------

class TestResolveMcpTools:
    def test_tool_with_mcp(self):
        tools = [ToolSpec(name="jira", description="Jira", mcp="mcp-server-atlassian@2.1.0")]
        results = resolve_mcp_tools(tools)
        assert len(results) == 1
        assert results[0]["resolved"] is True
        assert results[0]["server_info"].name == "mcp-server-atlassian"
        assert results[0]["version"] == "2.1.0"

    def test_tool_without_mcp(self):
        tools = [ToolSpec(name="search", description="Search")]
        results = resolve_mcp_tools(tools)
        assert len(results) == 1
        assert results[0]["resolved"] is False
        assert results[0]["mcp_ref"] is None

    def test_tool_with_unknown_mcp(self):
        tools = [ToolSpec(name="custom", description="Custom", mcp="mcp-server-nonexistent@1.0")]
        results = resolve_mcp_tools(tools)
        assert len(results) == 1
        assert results[0]["resolved"] is False
        assert results[0]["mcp_ref"] == "mcp-server-nonexistent@1.0"

    def test_mixed_tools(self):
        tools = [
            ToolSpec(name="jira", description="Jira", mcp="mcp-server-atlassian@2.1.0"),
            ToolSpec(name="search", description="Search"),
            ToolSpec(name="github", description="GitHub", mcp="mcp-server-github"),
        ]
        results = resolve_mcp_tools(tools)
        assert len(results) == 3
        assert results[0]["resolved"] is True
        assert results[1]["resolved"] is False
        assert results[2]["resolved"] is True


# ---------------------------------------------------------------------------
# generate_mcp_client_code
# ---------------------------------------------------------------------------

class TestGenerateMcpClientCode:
    def test_openai_sdk_target(self):
        code = generate_mcp_client_code("openai-sdk", "jira", "mcp-server-atlassian@2.1.0")
        assert "MCPServerStdio" in code["import"]
        assert "mcp-server-atlassian" in code["setup"]
        assert code["requirements"] == "openai-agents[mcp]>=0.1"

    def test_claude_sdk_target(self):
        code = generate_mcp_client_code("claude-sdk", "jira", "mcp-server-atlassian@2.1.0")
        assert "subprocess" in code["import"]
        assert "handle_jira" in code["call"]

    def test_langgraph_target(self):
        code = generate_mcp_client_code("langgraph", "github", "mcp-server-github@1.0.0")
        assert "MultiServerMCPClient" in code["import"]
        assert "mcp-server-github" in code["setup"]
        assert "langchain-mcp-adapters" in code["requirements"]

    def test_crewai_target(self):
        code = generate_mcp_client_code("crewai", "jira", "mcp-server-atlassian@2.0.0")
        assert "MCPTool" in code["import"]
        assert "crewai-tools[mcp]" in code["requirements"]

    def test_semantic_kernel_target(self):
        code = generate_mcp_client_code("semantic-kernel", "slack", "mcp-server-slack@1.0.0")
        assert "MCPStdioPlugin" in code["import"]
        assert "mcp-server-slack" in code["setup"]

    def test_system_prompt_target(self):
        code = generate_mcp_client_code("system-prompt", "jira", "mcp-server-atlassian@2.0.0")
        assert code["import"] == ""
        assert "MCP" in code["setup"]

    def test_env_vars_included(self):
        code = generate_mcp_client_code("openai-sdk", "github", "mcp-server-github@1.0.0")
        assert "GITHUB_TOKEN" in code["env_vars"]

    def test_version_in_setup(self):
        code = generate_mcp_client_code("openai-sdk", "jira", "mcp-server-atlassian@2.1.0")
        assert "@2.1.0" in code["setup"]

    def test_unknown_server_still_generates(self):
        code = generate_mcp_client_code("openai-sdk", "custom", "mcp-server-unknown@1.0.0")
        assert code["import"]  # still generates import
        assert "mcp-server-unknown" in code["setup"]

    def test_all_targets_produce_output(self):
        targets = ["openai-sdk", "claude-sdk", "langgraph", "crewai", "semantic-kernel", "system-prompt"]
        for target in targets:
            code = generate_mcp_client_code(target, "test-tool", "mcp-server-github@1.0.0")
            assert isinstance(code, dict)
            assert "import" in code
            assert "setup" in code
            assert "call" in code
            assert "env_vars" in code
            assert "requirements" in code
