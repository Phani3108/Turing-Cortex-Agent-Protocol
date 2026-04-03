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


def webhook_handler(
    url: str,
    timeout: int = 30,
    on_error: str = "deny",
    headers: dict | None = None,
) -> Callable[[str, dict, dict], bool]:
    """Approval via HTTP webhook. POSTs JSON, expects {"approved": bool}.

    on_error: "deny" (fail-closed), "allow" (fail-open), "raise" (propagate)
    """
    import json
    import urllib.request
    import urllib.error

    def handler(tool_name: str, tool_input: dict, context: dict) -> bool:
        payload = json.dumps({
            "tool_name": tool_name,
            "tool_input": tool_input,
            "context": context,
        }).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode())
                return bool(body.get("approved", False))
        except Exception:
            if on_error == "allow":
                return True
            elif on_error == "raise":
                raise
            return False  # deny by default
    return handler
