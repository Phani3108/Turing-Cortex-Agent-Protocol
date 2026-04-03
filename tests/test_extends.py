"""Tests for extends resolution and spec merging."""

import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from cortex_protocol.models import AgentSpec, merge_specs
from cortex_protocol.registry.local import LocalRegistry
from cortex_protocol.registry.resolver import resolve_extends
from cortex_protocol.cli import main


def _base_spec():
    return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: base-agent
  description: Base agent
  instructions: Base instructions
tools:
  - name: shared-tool
    description: A shared tool
  - name: base-only-tool
    description: Only in base
policies:
  max_turns: 10
  forbidden_actions:
    - do-bad-thing
""")


def _child_spec():
    return AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: child-agent
  description: Child agent
  instructions: Child instructions
  extends: "base-agent@1.0.0"
tools:
  - name: shared-tool
    description: Overridden shared tool
  - name: child-only-tool
    description: Only in child
policies:
  max_turns: 5
  forbidden_actions:
    - do-another-bad-thing
""")


def test_merge_specs_instructions_concatenated():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    assert "Base instructions" in merged.agent.instructions
    assert "Child instructions" in merged.agent.instructions


def test_merge_specs_child_name_wins():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    assert merged.agent.name == "child-agent"


def test_merge_specs_tool_deduplication_override_wins():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    tools_by_name = {t.name: t for t in merged.tools}
    # shared-tool should use child's description
    assert "shared-tool" in tools_by_name
    assert tools_by_name["shared-tool"].description == "Overridden shared tool"


def test_merge_specs_base_only_tool_preserved():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    tool_names = {t.name for t in merged.tools}
    assert "base-only-tool" in tool_names
    assert "child-only-tool" in tool_names


def test_merge_specs_policy_max_turns_override():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    assert merged.policies.max_turns == 5  # child wins


def test_merge_specs_forbidden_actions_union():
    base = _base_spec()
    child = _child_spec()
    merged = merge_specs(base, child)
    assert "do-bad-thing" in merged.policies.forbidden_actions
    assert "do-another-bad-thing" in merged.policies.forbidden_actions


def test_merge_specs_require_approval_union():
    base = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: base
  description: b
  instructions: b
policies:
  require_approval:
    - tool-a
""")
    child = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: child
  description: c
  instructions: c
policies:
  require_approval:
    - tool-b
""")
    merged = merge_specs(base, child)
    assert "tool-a" in merged.policies.require_approval
    assert "tool-b" in merged.policies.require_approval


def test_resolve_extends_base_in_registry():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = LocalRegistry(Path(tmpdir))
        base = _base_spec()
        reg.publish(base, "1.0.0")

        child = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: child-agent
  description: Child
  instructions: Child instructions
extends: "base-agent@1.0.0"
tools:
  - name: child-only
    description: Child tool
""")

        merged = resolve_extends(child, reg)
        tool_names = {t.name for t in merged.tools}
        assert "shared-tool" in tool_names
        assert "base-only-tool" in tool_names
        assert "child-only" in tool_names


def test_resolve_extends_base_not_found_returns_original():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = LocalRegistry(Path(tmpdir))
        child = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: child-agent
  description: Child
  instructions: Child instructions
extends: "nonexistent-agent@1.0.0"
""")
        result = resolve_extends(child, reg)
        # Should return the child unchanged
        assert result.agent.name == "child-agent"
        assert result.extends == "nonexistent-agent@1.0.0"


def test_resolve_extends_no_extends_field():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = LocalRegistry(Path(tmpdir))
        spec = _base_spec()
        result = resolve_extends(spec, reg)
        assert result is spec


def test_resolve_extends_org_scoped_ref():
    with tempfile.TemporaryDirectory() as tmpdir:
        reg = LocalRegistry(Path(tmpdir))
        base = _base_spec()
        reg.publish(base, "2.0.0")

        child = AgentSpec.from_yaml_str("""
version: "0.3"
agent:
  name: child-agent
  description: Child
  instructions: Child instructions
extends: "@myorg/base-agent@^2.0.0"
""")
        merged = resolve_extends(child, reg)
        # base-agent@2.0.0 satisfies ^2.0
        assert merged.agent.name == "child-agent"
        tool_names = {t.name for t in merged.tools}
        assert "shared-tool" in tool_names


def test_compile_cli_resolves_extends():
    """Test that the compile CLI command resolves extends from registry."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_dir = Path(tmpdir) / "registry"
        reg = LocalRegistry(reg_dir)
        base = _base_spec()
        reg.publish(base, "1.0.0")

        child_yaml = '''\
version: "0.3"
agent:
  name: child-agent
  description: Child agent
  instructions: Child instructions
extends: "base-agent@1.0.0"
tools:
  - name: child-only
    description: Child tool
policies:
  max_turns: 5
'''
        spec_file = Path(tmpdir) / "child.yaml"
        spec_file.write_text(child_yaml)

        result = runner.invoke(main, [
            "compile", str(spec_file),
            "--target", "system-prompt",
            "--output", str(Path(tmpdir) / "out"),
            "--registry-dir", str(reg_dir),
        ])
        assert result.exit_code == 0
        assert "child-agent" in result.output


def test_compile_cli_no_extends_flag_skips_resolution():
    """Test that --no-extends skips extends resolution."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        child_yaml = '''\
version: "0.3"
agent:
  name: child-agent
  description: Child agent
  instructions: Child instructions
extends: "nonexistent-base@1.0.0"
tools:
  - name: child-only
    description: Child tool
'''
        spec_file = Path(tmpdir) / "child.yaml"
        spec_file.write_text(child_yaml)

        result = runner.invoke(main, [
            "compile", str(spec_file),
            "--target", "system-prompt",
            "--output", str(Path(tmpdir) / "out"),
            "--no-extends",
        ])
        assert result.exit_code == 0
