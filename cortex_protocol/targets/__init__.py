"""Compilation targets for Cortex Protocol."""

from .base import CompilationTarget, OutputFile
from .system_prompt import SystemPromptTarget
from .openai_sdk import OpenAISDKTarget
from .claude_sdk import ClaudeSDKTarget
from .crewai import CrewAITarget
from .langgraph import LangGraphTarget
from .semantic_kernel import SemanticKernelTarget

TARGET_REGISTRY: dict[str, type[CompilationTarget]] = {
    "system-prompt": SystemPromptTarget,
    "openai-sdk": OpenAISDKTarget,
    "claude-sdk": ClaudeSDKTarget,
    "crewai": CrewAITarget,
    "langgraph": LangGraphTarget,
    "semantic-kernel": SemanticKernelTarget,
}

__all__ = [
    "CompilationTarget",
    "OutputFile",
    "TARGET_REGISTRY",
    "SystemPromptTarget",
    "OpenAISDKTarget",
    "ClaudeSDKTarget",
    "CrewAITarget",
    "LangGraphTarget",
    "SemanticKernelTarget",
]
