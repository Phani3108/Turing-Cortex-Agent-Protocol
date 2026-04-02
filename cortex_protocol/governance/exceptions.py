"""Policy violation exceptions for runtime enforcement.

These exceptions are raised by PolicyEnforcer when an agent action
violates the governance policies defined in its spec. Callers must
handle them — they are intentionally not silenceable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolicyViolation(Exception):
    """Base exception for all policy violations."""

    policy: str       # which policy field triggered this
    detail: str       # human-readable explanation
    run_id: str = ""  # which enforcement run
    turn: int = 0     # which turn in the run

    def __str__(self) -> str:
        return f"[{self.policy}] {self.detail} (run={self.run_id}, turn={self.turn})"


@dataclass
class MaxTurnsExceeded(PolicyViolation):
    """Raised when the agent exceeds the max_turns limit."""

    max_turns: int = 0

    def __post_init__(self):
        if not self.policy:
            self.policy = "max_turns"


@dataclass
class ApprovalRequired(PolicyViolation):
    """Raised when a tool call requires human approval before execution."""

    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.policy:
            self.policy = "require_approval"


@dataclass
class ForbiddenActionDetected(PolicyViolation):
    """Raised when an LLM response matches a forbidden action pattern."""

    action: str = ""         # which forbidden action was matched
    response_text: str = ""  # the response that triggered it

    def __post_init__(self):
        if not self.policy:
            self.policy = "forbidden_actions"
