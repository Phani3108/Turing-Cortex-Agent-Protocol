"""Tests for the core compiler — model-family-aware formatting."""

from cortex_protocol.compiler import compile_system_prompt
from cortex_protocol.model_families import resolve_family, get_format_family


def test_resolve_claude():
    fam = resolve_family("claude-sonnet-4")
    assert fam.id == "anthropic"


def test_resolve_gpt():
    fam = resolve_family("gpt-4o")
    assert fam.id == "openai-gpt"


def test_resolve_gemini():
    fam = resolve_family("gemini-2.5-pro")
    assert fam.id == "gemini"


def test_resolve_reasoning():
    fam = resolve_family("o4-mini")
    assert fam.id == "openai-reasoning"


def test_resolve_deepseek():
    fam = resolve_family("deepseek-v3")
    assert fam.id == "deepseek"


def test_resolve_llama():
    fam = resolve_family("llama-4")
    assert fam.id == "meta-llama"


def test_resolve_unknown():
    fam = resolve_family("some-random-model")
    assert fam.id == "unknown"


def test_format_family_claude():
    assert get_format_family("claude-sonnet-4") == "claude-family"


def test_format_family_gpt():
    assert get_format_family("gpt-4o") == "openai-family"


def test_format_family_reasoning():
    assert get_format_family("o3") == "reasoning-family"


def test_claude_prompt_uses_xml(basic_spec):
    prompt = compile_system_prompt(basic_spec, "claude-sonnet-4")
    assert "<identity>" in prompt
    assert "</identity>" in prompt
    assert "<tools>" in prompt
    assert "<policies>" in prompt


def test_openai_prompt_uses_numbered_lists(basic_spec):
    prompt = compile_system_prompt(basic_spec, "gpt-4o")
    assert "## Identity" in prompt or "## Instructions" in prompt
    assert "1." in prompt


def test_reasoning_prompt_minimal(basic_spec):
    prompt = compile_system_prompt(basic_spec, "o3")
    assert "## Task Constraints" in prompt


def test_open_source_prompt_explicit(basic_spec):
    prompt = compile_system_prompt(basic_spec, "llama-4")
    assert "IMPORTANT INSTRUCTIONS" in prompt
    assert "Do not deviate" in prompt


def test_gemini_prompt_mixed(basic_spec):
    prompt = compile_system_prompt(basic_spec, "gemini-2.5-pro")
    # Gemini uses XML for context, markdown for instructions
    assert "<identity>" in prompt
    assert "## Tools" in prompt or "## Policies" in prompt


def test_prompt_contains_agent_name(basic_spec):
    prompt = compile_system_prompt(basic_spec, "gpt-4o")
    assert "support-agent" in prompt


def test_prompt_contains_tools(basic_spec):
    prompt = compile_system_prompt(basic_spec, "gpt-4o")
    assert "lookup-order" in prompt
    assert "process-refund" in prompt
    assert "send-email" in prompt


def test_prompt_contains_policies(basic_spec):
    prompt = compile_system_prompt(basic_spec, "gpt-4o")
    assert "process-refund" in prompt  # require_approval
    assert "NEVER" in prompt  # forbidden_actions


def test_prompt_contains_escalation(policy_spec):
    prompt = compile_system_prompt(policy_spec, "gpt-4o")
    assert "vp-engineering" in prompt
