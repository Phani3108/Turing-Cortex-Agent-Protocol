"""Convenience wrapper for one-liner policy enforcement.

    from cortex_protocol.governance import enforce

    safe_agent = enforce(my_agent_fn, spec="./agent.yaml")
    result = safe_agent("Process this refund")

This wraps any (str) -> str callable with PolicyEnforcer checks:
- increment_turn at each call
- check_response on the output
- audit logging of every interaction

For tool-level enforcement (check_tool_call, check_escalation), use
PolicyEnforcer directly — the convenience wrapper only handles the
turn + response loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Union

from ..models import AgentSpec
from .audit import AuditLog
from .enforcer import PolicyEnforcer


class EnforcedAgent:
    """A wrapped agent callable with policy enforcement."""

    def __init__(
        self,
        agent_fn: Callable[[str], str],
        enforcer: PolicyEnforcer,
    ):
        self._agent_fn = agent_fn
        self._enforcer = enforcer

    def __call__(self, message: str) -> str:
        """Run the agent with policy enforcement.

        1. Increment turn (raises MaxTurnsExceeded if at limit)
        2. Call the agent function
        3. Check response against forbidden_actions
        4. Return the response
        """
        self._enforcer.increment_turn()
        response = self._agent_fn(message)
        self._enforcer.check_response(response)
        return response

    @property
    def enforcer(self) -> PolicyEnforcer:
        """Access the underlying PolicyEnforcer for tool-level checks."""
        return self._enforcer


def enforce(
    agent_fn: Callable[[str], str],
    spec: Union[str, Path, AgentSpec],
    *,
    audit_dir: Optional[Union[str, Path]] = None,
    strict_forbidden: bool = False,
) -> EnforcedAgent:
    """Wrap a callable agent with policy enforcement.

    Args:
        agent_fn: A function that takes a message string and returns a response string.
        spec: Path to a YAML spec file, or an AgentSpec object.
        audit_dir: Directory for JSONL audit log files. None = in-memory only.
        strict_forbidden: If True, forbidden_actions violations are blocking.

    Returns:
        An EnforcedAgent callable with the same (str) -> str interface.

    Example:
        def my_agent(msg):
            return "I'll help with that!"

        safe = enforce(my_agent, "./agent.yaml", audit_dir="./logs")
        result = safe("Process this refund")  # enforced + audited
    """
    if isinstance(spec, (str, Path)):
        spec = AgentSpec.from_yaml(str(spec))

    audit_log = None
    if audit_dir:
        audit_path = Path(audit_dir)
        audit_path.mkdir(parents=True, exist_ok=True)
        log_file = audit_path / f"audit_{spec.agent.name}.jsonl"
        audit_log = AuditLog(path=log_file)

    enforcer = PolicyEnforcer(
        spec,
        audit_log=audit_log,
        strict_forbidden=strict_forbidden,
    )

    return EnforcedAgent(agent_fn, enforcer)
