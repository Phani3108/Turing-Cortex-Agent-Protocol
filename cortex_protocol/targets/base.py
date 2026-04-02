"""Base classes for compilation targets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import AgentSpec


@dataclass
class OutputFile:
    """A single file produced by compilation."""

    path: str  # relative path within the output directory
    content: str
    description: str = ""


class CompilationTarget(ABC):
    """Abstract base for a compilation target."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def compile(self, spec: AgentSpec) -> list[OutputFile]:
        """Compile an agent spec into output files."""
        ...
