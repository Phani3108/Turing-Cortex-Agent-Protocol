"""Model family detection and formatting preferences.

Ported from Cortex families.js — regex-based model classification
so future models resolve automatically without code changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FormattingPrefs:
    """How to format prompts for a model family."""

    use_xml_tags: bool = False
    section_markers: str = "markdown"  # "xml" | "markdown"
    list_style: str = "dash"  # "dash" | "numbered"
    emphasis_style: str = "bold"  # "bold" | "caps"
    instruction_tone: str = "direct"  # "direct" | "system" | "minimal" | "explicit"


@dataclass
class ModelFamily:
    """A model family definition."""

    id: str
    name: str
    pattern: re.Pattern
    formatting: FormattingPrefs
    prompt_pattern: str = "system_prompt"

    def matches(self, model_name: str) -> bool:
        return bool(self.pattern.search(model_name))


# ── Family Definitions ──────────────────────────────────────────────────────

MODEL_FAMILIES: list[ModelFamily] = [
    ModelFamily(
        id="anthropic",
        name="Anthropic Claude",
        pattern=re.compile(r"claude|anthropic|sonnet|opus|haiku", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=True,
            section_markers="xml",
            list_style="dash",
            emphasis_style="bold",
            instruction_tone="direct",
        ),
        prompt_pattern="structured_xml",
    ),
    ModelFamily(
        id="openai-gpt",
        name="OpenAI GPT",
        pattern=re.compile(r"gpt-?\d|chatgpt", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=False,
            section_markers="markdown",
            list_style="numbered",
            emphasis_style="caps",
            instruction_tone="system",
        ),
        prompt_pattern="system_prompt",
    ),
    ModelFamily(
        id="openai-reasoning",
        name="OpenAI Reasoning",
        pattern=re.compile(r"^o[1-9]\d*(-mini|-pro)?$", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=False,
            section_markers="markdown",
            list_style="numbered",
            emphasis_style="caps",
            instruction_tone="minimal",
        ),
        prompt_pattern="problem_statement",
    ),
    ModelFamily(
        id="gemini",
        name="Google Gemini",
        pattern=re.compile(r"gemini", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=True,
            section_markers="markdown",
            list_style="dash",
            emphasis_style="bold",
            instruction_tone="conversational",
        ),
        prompt_pattern="detailed_markdown",
    ),
    ModelFamily(
        id="deepseek",
        name="DeepSeek",
        pattern=re.compile(r"deepseek", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=False,
            section_markers="markdown",
            list_style="dash",
            emphasis_style="bold",
            instruction_tone="explicit",
        ),
        prompt_pattern="explicit_markdown",
    ),
    ModelFamily(
        id="meta-llama",
        name="Meta Llama",
        pattern=re.compile(r"llama|meta-llama", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=False,
            section_markers="markdown",
            list_style="dash",
            emphasis_style="bold",
            instruction_tone="explicit",
        ),
        prompt_pattern="explicit_markdown",
    ),
    ModelFamily(
        id="mistral",
        name="Mistral AI",
        pattern=re.compile(r"mistral|codestral|mixtral|pixtral", re.IGNORECASE),
        formatting=FormattingPrefs(
            use_xml_tags=False,
            section_markers="markdown",
            list_style="dash",
            emphasis_style="bold",
            instruction_tone="explicit",
        ),
        prompt_pattern="explicit_markdown",
    ),
]

# ── Family Detection ────────────────────────────────────────────────────────

# Map family IDs to format family slugs (used by compiler)
_FORMAT_FAMILY_MAP = {
    "anthropic": "claude-family",
    "openai-gpt": "openai-family",
    "openai-reasoning": "reasoning-family",
    "gemini": "gemini-family",
    "deepseek": "open-source",
    "meta-llama": "open-source",
    "mistral": "open-source",
}

_DEFAULT_FAMILY = ModelFamily(
    id="unknown",
    name="Unknown",
    pattern=re.compile(r"$^"),  # never matches
    formatting=FormattingPrefs(
        use_xml_tags=False,
        section_markers="markdown",
        list_style="numbered",
        emphasis_style="caps",
        instruction_tone="system",
    ),
    prompt_pattern="system_prompt",
)


def resolve_family(model_name: str) -> ModelFamily:
    """Resolve a model name to its family definition."""
    if not model_name:
        return _DEFAULT_FAMILY
    for fam in MODEL_FAMILIES:
        if fam.matches(model_name):
            return fam
    return _DEFAULT_FAMILY


def get_format_family(model_name: str) -> str:
    """Get the format family slug for the compiler."""
    family = resolve_family(model_name)
    return _FORMAT_FAMILY_MAP.get(family.id, "openai-family")
