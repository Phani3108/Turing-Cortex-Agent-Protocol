"""System Prompt compilation target — universal baseline."""

from __future__ import annotations

from ..compiler import compile_system_prompt
from ..models import AgentSpec
from .base import CompilationTarget, OutputFile


class SystemPromptTarget(CompilationTarget):
    name = "system-prompt"
    description = "Model-family-optimized system prompt (XML for Claude, numbered lists for GPT)"

    def __init__(self, model_hint: str | None = None):
        self.model_hint = model_hint

    def compile(self, spec: AgentSpec) -> list[OutputFile]:
        model = self.model_hint or spec.model.preferred
        prompt = compile_system_prompt(spec, model)

        return [
            OutputFile(
                path="system_prompt.md",
                content=prompt,
                description=f"System prompt optimized for {model}",
            ),
        ]
