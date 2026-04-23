"""MCP prompts exposed by the Turing server.

Prompts are reusable message templates that an MCP client can instantiate.
We keep the templates deliberately brief — they frame a task; the LLM
does the reasoning, often calling Turing tools (`cortex.validate_spec`,
`cortex.lint_spec`, `cortex.drift_check`, etc.) along the way.
"""

from __future__ import annotations


def _governance_review(spec_yaml: str) -> str:
    return (
        "Review the following Cortex Protocol agent spec for governance "
        "completeness. Call cortex.validate_spec and cortex.lint_spec on it, "
        "then summarize any missing or weak policies. Flag each gap by "
        "severity (error / warning / info), and propose concrete remediations "
        "anchored in the spec's tools, approval gates, and compliance metadata.\n\n"
        "```yaml\n"
        f"{spec_yaml}\n"
        "```"
    )


def _incident_postmortem(audit_log_path: str) -> str:
    return (
        "Produce a blameless incident postmortem from the audit log at "
        f"`{audit_log_path}`. First call cortex.audit_query to read the log. "
        "For each run that contained a blocked event (`allowed: false`), "
        "walk through: what triggered it, which policy caught it, what the "
        "agent attempted, and whether the policy should be tightened, "
        "relaxed, or left as-is. End with a short list of recommended "
        "spec edits."
    )


def _draft_policy(use_case: str) -> str:
    return (
        "Draft a Cortex Protocol `policies:` block for the following use case. "
        "Use `from_template:` where an existing template fits; otherwise write "
        "explicit fields (`max_turns`, `require_approval`, `forbidden_actions`, "
        "`escalation`, and — if the agent spends money or runs for long — "
        "`max_cost_usd`, `max_tokens_per_run`, `max_tool_calls_per_run`).\n\n"
        f"Use case: {use_case}"
    )


PROMPTS: dict[str, tuple[str, callable]] = {
    "governance_review":  ("Review a Turing agent spec for governance completeness.", _governance_review),
    "incident_postmortem": ("Produce a postmortem from a Turing audit log.", _incident_postmortem),
    "draft_policy":       ("Draft a Cortex Protocol policies block for a given use case.", _draft_policy),
}
