"""MCP tool definitions for the Turing server.

Every tool is a thin delegate over an existing Cortex Protocol function.
We never duplicate business logic here — if you find yourself writing
more than a few lines of transformation, the logic probably belongs in
the underlying module instead.

All tools return plain JSON-serializable dicts. Errors surface as
`{"ok": False, "error": "..."}` rather than exceptions so the MCP client
gets a structured result it can reason about.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _spec_from_yaml(yaml_text: str):
    from ..models import AgentSpec
    return AgentSpec.from_yaml_str(yaml_text)


def _err(msg: str, **extra) -> dict:
    return {"ok": False, "error": msg, **extra}


def _ok(**data) -> dict:
    return {"ok": True, **data}


# ---------------------------------------------------------------------------
# validate / lint / diff / compile
# ---------------------------------------------------------------------------

def validate_spec(yaml_text: str) -> dict:
    """Validate an agent spec YAML against the Cortex Protocol schema.

    Returns: {ok, valid, errors[], spec_name?}
    """
    import tempfile
    from ..validator import validate_file

    # validate_file wants a path; write a tmp file so we reuse its rules.
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        tmp = f.name
    try:
        spec, errors = validate_file(tmp)
    finally:
        Path(tmp).unlink(missing_ok=True)

    return _ok(
        valid=spec is not None and not errors,
        errors=list(errors),
        spec_name=spec.agent.name if spec else None,
    )


def lint_spec(yaml_text: str, fail_on: str = "error") -> dict:
    """Lint an agent spec and return score + grade + findings.

    fail_on: "error" | "warning" | "any"
    Returns: {ok, score, grade, passed, findings[]}
    """
    from ..linter import lint

    try:
        spec = _spec_from_yaml(yaml_text)
    except Exception as e:
        return _err(f"Invalid spec: {e}")

    report = lint(spec)
    findings = [
        {
            "rule": r.rule.id,
            "severity": r.rule.severity.value,
            "passed": r.passed,
            "message": r.rule.message,
            "detail": r.detail,
            "weight": r.rule.weight,
        }
        for r in report.results
    ]
    failing = [f for f in findings if not f["passed"]]
    if fail_on == "any":
        passed = not failing
    elif fail_on == "warning":
        passed = not any(f["severity"] in ("error", "warning") for f in failing)
    else:
        passed = not any(f["severity"] == "error" for f in failing)

    return _ok(
        score=report.score,
        grade=report.grade,
        passed=passed,
        findings=findings,
    )


def diff_specs(yaml_a: str, yaml_b: str) -> dict:
    """Diff two agent specs. Returns tool/policy/model deltas and breaking flag."""
    from ..differ import diff_specs as _diff

    try:
        a = _spec_from_yaml(yaml_a)
        b = _spec_from_yaml(yaml_b)
    except Exception as e:
        return _err(f"Invalid spec: {e}")

    d = _diff(a, b)
    return _ok(
        breaking=d.has_breaking_changes,
        tools_added=list(d.tools_added),
        tools_removed=list(d.tools_removed),
        tools_modified=[
            {"name": t.name, "kind": t.kind, "detail": t.detail} for t in d.tools_modified
        ],
        policy_changes=[
            {"field": p.field, "from": p.old_value, "to": p.new_value}
            for p in d.policy_changes
        ],
        model_changes=[
            {"field": p.field, "from": p.old_value, "to": p.new_value}
            for p in d.model_changes
        ],
    )


def compile_spec(yaml_text: str, target: str = "system-prompt") -> dict:
    """Compile an agent spec to a target runtime.

    target: one of system-prompt, openai-sdk, claude-sdk, langgraph, crewai, semantic-kernel
    Returns: {ok, target, files: {filename: content}}
    """
    try:
        spec = _spec_from_yaml(yaml_text)
    except Exception as e:
        return _err(f"Invalid spec: {e}")

    if target == "system-prompt":
        from ..compiler import compile_system_prompt
        return _ok(target=target, files=[
            {"path": "system_prompt.txt", "content": compile_system_prompt(spec)}
        ])

    from ..targets import TARGET_REGISTRY
    tgt_cls = TARGET_REGISTRY.get(target)
    if tgt_cls is None:
        return _err(
            f"Unknown compilation target '{target}'",
            known=sorted(TARGET_REGISTRY.keys()) + ["system-prompt"],
        )

    try:
        outputs = tgt_cls().compile(spec)
    except Exception as e:
        return _err(f"Compilation failed: {e}")
    return _ok(
        target=target,
        files=[
            {"path": o.path, "content": o.content, "description": o.description}
            for o in outputs
        ],
    )


# ---------------------------------------------------------------------------
# Runtime policy check (dry-run)
# ---------------------------------------------------------------------------

def check_policy(yaml_text: str, tool_name: str, tool_input: Optional[dict] = None) -> dict:
    """Dry-run a single tool call through PolicyEnforcer and report the outcome.

    Returns: {ok, allowed, policy?, detail, event_type}
    """
    from ..governance.enforcer import PolicyEnforcer
    from ..governance.exceptions import (
        ApprovalRequired, MaxTurnsExceeded, BudgetExceeded, ForbiddenActionDetected,
    )

    try:
        spec = _spec_from_yaml(yaml_text)
    except Exception as e:
        return _err(f"Invalid spec: {e}")

    enforcer = PolicyEnforcer(spec)
    enforcer.increment_turn()
    try:
        result = enforcer.check_tool_call(tool_name, tool_input or {})
        return _ok(
            allowed=result.allowed,
            event_type=result.event_type,
            detail=result.detail,
        )
    except (ApprovalRequired, MaxTurnsExceeded, BudgetExceeded, ForbiddenActionDetected) as v:
        return _ok(
            allowed=False,
            policy=v.policy,
            detail=v.detail,
            event_type="blocked",
        )


# ---------------------------------------------------------------------------
# Audit / drift / compliance / fleet
# ---------------------------------------------------------------------------

def audit_query(log_path: str, run_id: Optional[str] = None, limit: int = 200) -> dict:
    """Query an audit log file. Optionally filter by run_id."""
    from ..governance.audit import AuditLog

    path = Path(log_path).expanduser()
    if not path.exists():
        return _err(f"Audit log not found: {path}")
    log = AuditLog.from_file(path)
    events = log.events_for_run(run_id) if run_id else log.events()
    events = events[-limit:]
    return _ok(
        count=len(events),
        total=len(log.events()),
        summary=log.summary(),
        events=[
            {
                "timestamp": e.timestamp,
                "run_id": e.run_id,
                "turn": e.turn,
                "event_type": e.event_type,
                "allowed": e.allowed,
                "policy": e.policy,
                "tool_name": e.tool_name,
                "detail": e.detail,
                "cost_usd": e.cost_usd,
                "run_cost_usd": e.run_cost_usd,
            }
            for e in events
        ],
    )


def drift_check(spec_path: str, log_path: str) -> dict:
    """Compare spec to audit log. Returns compliance score and drift details."""
    from ..validator import validate_file
    from ..governance.audit import AuditLog
    from ..governance.drift import detect_drift

    spec, errors = validate_file(spec_path)
    if not spec or errors:
        return _err("Spec invalid", validation_errors=list(errors))
    log = AuditLog.from_file(Path(log_path).expanduser())
    return _ok(**detect_drift(spec, log).to_dict())


def compliance_report(log_path: str, standard: str = "soc2",
                      spec_path: Optional[str] = None) -> dict:
    """Generate compliance report (soc2|hipaa|pci-dss|gdpr|general) as JSON."""
    from ..governance.audit import AuditLog
    from ..governance.compliance import export_compliance_json

    log = AuditLog.from_file(Path(log_path).expanduser())
    spec = None
    if spec_path:
        from ..validator import validate_file
        spec, _ = validate_file(spec_path)
    return _ok(**export_compliance_json(log, standard=standard, spec=spec))


def fleet_report(log_globs: list[str], standard: str = "soc2") -> dict:
    """Fleet-wide compliance roll-up across multiple audit logs."""
    from ..governance.fleet import generate_fleet_report

    paths = []
    for pattern in log_globs:
        # Allow plain paths as well as globs.
        p = Path(pattern).expanduser()
        if p.exists():
            paths.append(p)
            continue
        paths.extend(Path().glob(pattern))

    if not paths:
        return _err("No log files matched the given patterns")

    md = generate_fleet_report(paths, standard=standard)
    return _ok(report_markdown=md, log_count=len(paths))


# ---------------------------------------------------------------------------
# Registry / packs / MCP server catalog
# ---------------------------------------------------------------------------

def list_registry(tag: Optional[str] = None, compliance: Optional[str] = None,
                  owner: Optional[str] = None, name_contains: Optional[str] = None) -> dict:
    """List agents in the local registry, optionally filtered."""
    from ..registry.local import LocalRegistry

    reg = LocalRegistry()
    results = reg.search(
        tags=[tag] if tag else None,
        compliance=[compliance] if compliance else None,
        owner=owner,
        name_contains=name_contains,
    )
    return _ok(
        count=len(results),
        agents=[
            {
                "name": meta.name,
                "latest": meta.latest,
                "versions": [v.version for v in meta.versions],
                "description": spec.agent.description,
                "tags": spec.metadata.tags if spec.metadata else [],
                "compliance": spec.metadata.compliance if spec.metadata else [],
            }
            for meta, spec in results
        ],
    )


def list_packs() -> dict:
    """List built-in agent packs."""
    from ..packs import PACK_REGISTRY
    return _ok(packs=list(PACK_REGISTRY))


def install_pack(pack_name: str, output_dir: str) -> dict:
    """Install a built-in pack into a directory."""
    from ..packs import install_pack as _install
    paths = _install(pack_name, Path(output_dir).expanduser())
    if paths is None:
        return _err(f"Unknown pack '{pack_name}'")
    return _ok(pack=pack_name, files=list(paths))


def list_mcp_servers() -> dict:
    """List the bundled MCP server catalog."""
    from ..network.mcp import MCPServerRegistry

    reg = MCPServerRegistry()
    return _ok(
        servers=[
            {
                "name": s.name,
                "package": s.package,
                "description": s.description,
                "transport": s.transport,
                "tools": list(s.tools),
                "env_vars": list(s.env_vars),
            }
            for s in reg.list_servers()
        ]
    )


def suggest_mcp_for_tool(tool_description: str) -> dict:
    """Suggest MCP servers whose tool names best match a description.

    Heuristic-only (no LLM). Matches on server + tool name substrings.
    """
    from ..network.mcp import MCPServerRegistry

    reg = MCPServerRegistry()
    words = [w for w in tool_description.lower().split() if len(w) > 2]
    scored = []
    for s in reg.list_servers():
        haystack = " ".join([s.name, s.description, *s.tools]).lower()
        hits = sum(1 for w in words if w in haystack)
        if hits:
            scored.append((hits, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return _ok(
        suggestions=[
            {"name": s.name, "score": hits, "package": s.package,
             "tools": list(s.tools), "description": s.description}
            for hits, s in scored[:5]
        ]
    )


# Registered set — used by server.py to attach tools in one pass.
TURING_TOOLS: list[tuple[str, Any, str]] = [
    ("validate_spec", validate_spec,
     "Validate a Cortex Protocol agent spec YAML."),
    ("lint_spec", lint_spec,
     "Lint an agent spec; returns 0-100 score, letter grade, and findings."),
    ("diff_specs", diff_specs,
     "Diff two agent specs. Flags breaking changes."),
    ("compile_spec", compile_spec,
     "Compile an agent spec to a target runtime (system-prompt, openai-sdk, claude-sdk, langgraph, crewai, semantic-kernel)."),
    ("check_policy", check_policy,
     "Dry-run a single tool call through PolicyEnforcer. Returns whether the call would be allowed."),
    ("audit_query", audit_query,
     "Query an audit log file, optionally filtered by run_id."),
    ("drift_check", drift_check,
     "Compare an agent spec to its audit log. Returns compliance score + drift details."),
    ("compliance_report", compliance_report,
     "Generate a SOC2/HIPAA/PCI-DSS/GDPR compliance report from an audit log."),
    ("fleet_report", fleet_report,
     "Fleet-wide compliance roll-up across multiple audit logs."),
    ("list_registry", list_registry,
     "List agents in the local Turing registry with optional filters."),
    ("list_packs", list_packs,
     "List built-in agent packs shipped with Turing."),
    ("install_pack", install_pack,
     "Install a built-in agent pack into a directory."),
    ("list_mcp_servers", list_mcp_servers,
     "List the bundled catalog of external MCP servers Turing knows how to wire."),
    ("suggest_mcp_for_tool", suggest_mcp_for_tool,
     "Suggest MCP servers whose tools match a natural-language description."),
]
