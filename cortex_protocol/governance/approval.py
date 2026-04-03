"""Built-in approval handlers for PolicyEnforcer."""
from __future__ import annotations
from typing import Callable


def always_approve(tool_name: str, tool_input: dict, context: dict) -> bool:
    return True


def always_deny(tool_name: str, tool_input: dict, context: dict) -> bool:
    return False


def allowlist_handler(*allowed_tools: str) -> Callable[[str, dict, dict], bool]:
    def handler(tool_name: str, tool_input: dict, context: dict) -> bool:
        return tool_name in allowed_tools
    return handler


def log_and_approve(log_fn: Callable[[str], None]) -> Callable[[str, dict, dict], bool]:
    def handler(tool_name: str, tool_input: dict, context: dict) -> bool:
        log_fn(f"Auto-approved: {tool_name} in run {context.get('run_id', '?')}")
        return True
    return handler
