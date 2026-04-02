"""Tests for the Semantic Kernel compilation target."""

import ast
import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.targets.semantic_kernel import SemanticKernelTarget
from tests.conftest import basic_spec, policy_spec


class TestSemanticKernelBasic:
    def test_produces_three_files(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        paths = [f.path for f in files]
        assert "agent.py" in paths
        assert "requirements.txt" in paths
        assert "test_agent.py" in paths

    def test_agent_py_is_valid_python(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py")
        ast.parse(agent_py.content)  # raises SyntaxError if invalid

    def test_test_agent_py_is_valid_python(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        test_py = next(f for f in files if f.path == "test_agent.py")
        ast.parse(test_py.content)

    def test_system_prompt_in_agent(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "SYSTEM_PROMPT" in agent_py
        assert basic_spec.agent.name in agent_py

    def test_plugin_class_generated(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "class " in agent_py
        assert "Plugin" in agent_py

    def test_kernel_function_decorator_present(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "@kernel_function" in agent_py

    def test_build_kernel_function(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "def build_kernel" in agent_py

    def test_build_agent_function(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "def build_agent" in agent_py

    def test_run_agent_coroutine(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "async def run_agent" in agent_py

    def test_max_turns_in_run_loop(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "max_turns" in agent_py


class TestSemanticKernelPolicies:
    def test_approval_required_tools_flagged(self, policy_spec):
        files = SemanticKernelTarget().compile(policy_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "APPROVAL REQUIRED" in agent_py

    def test_escalation_in_run_loop(self, policy_spec):
        files = SemanticKernelTarget().compile(policy_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "Escalat" in agent_py

    def test_max_turns_from_policy(self, policy_spec):
        files = SemanticKernelTarget().compile(policy_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "8" in agent_py  # policy_spec has max_turns=8


class TestSemanticKernelModelFamily:
    def test_claude_model_uses_anthropic_connector(self, basic_spec):
        # basic_spec uses claude-sonnet-4
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "AnthropicChatCompletion" in agent_py

    def test_openai_model_uses_azure_connector(self, policy_spec):
        # policy_spec uses gpt-4o
        files = SemanticKernelTarget().compile(policy_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "AzureChatCompletion" in agent_py

    def test_requirements_includes_semantic_kernel(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        req = next(f for f in files if f.path == "requirements.txt").content
        assert "semantic-kernel" in req

    def test_requirements_anthropic_extra_for_claude(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        req = next(f for f in files if f.path == "requirements.txt").content
        assert "anthropic" in req


class TestSemanticKernelAllTools:
    def test_all_tools_have_kernel_function(self, policy_spec):
        files = SemanticKernelTarget().compile(policy_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        for tool in policy_spec.tools:
            fn_name = tool.name.replace("-", "_").lower()
            assert fn_name in agent_py

    def test_tool_descriptions_in_agent(self, basic_spec):
        files = SemanticKernelTarget().compile(basic_spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        for tool in basic_spec.tools:
            assert tool.description in agent_py


class TestSemanticKernelMCP:
    def _mcp_spec(self):
        return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: mcp-sk-agent
  description: SK agent with MCP
  instructions: Test
tools:
  - name: gh-file
    description: Get GitHub file
    mcp: "mcp-server-github@1.0.0"
  - name: local-fn
    description: Local function
""")

    def test_mcp_plugin_setup_in_build_kernel(self):
        spec = self._mcp_spec()
        files = SemanticKernelTarget().compile(spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "MCPStdioPlugin" in agent_py

    def test_mcp_server_name_in_output(self):
        spec = self._mcp_spec()
        files = SemanticKernelTarget().compile(spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "mcp-server-github" in agent_py

    def test_non_mcp_tool_still_in_plugin(self):
        spec = self._mcp_spec()
        files = SemanticKernelTarget().compile(spec)
        agent_py = next(f for f in files if f.path == "agent.py").content
        assert "local_fn" in agent_py

    def test_mcp_requirements_has_mcp_extra(self):
        spec = self._mcp_spec()
        files = SemanticKernelTarget().compile(spec)
        reqs = next(f for f in files if f.path == "requirements.txt").content
        assert "semantic-kernel[mcp]" in reqs
