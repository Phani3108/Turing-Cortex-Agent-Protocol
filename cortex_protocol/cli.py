"""Cortex Protocol CLI — 15 commands for agent specification, governance, and network orchestration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from . import __version__
from .targets import TARGET_REGISTRY


@click.group()
@click.version_option(__version__, prog_name="cortex-protocol")
def main():
    """Cortex Protocol — Portable Agent Specification Layer.

    Define an agent once, compile to any runtime.
    """
    pass


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@main.command()
@click.argument("output", default="agent.yaml")
def init(output: str):
    """Create an example agent spec file."""
    example = '''\
version: "0.1"

agent:
  name: my-agent
  description: A helpful assistant that answers questions
  instructions: |
    You are a helpful assistant. Answer questions clearly and concisely.
    Always cite your sources when possible. If you are unsure, say so rather
    than guessing. Escalate to a human when the user requests it.

tools:
  - name: search
    description: Search for information
    parameters:
      type: object
      properties:
        query:
          type: string
          description: The search query
      required:
        - query

policies:
  max_turns: 10
  require_approval: []
  forbidden_actions:
    - Share confidential information
    - Make up facts
  escalation:
    trigger: user requests human assistance
    target: human-support

model:
  preferred: claude-sonnet-4
  fallback: gpt-4o
  temperature: 0.7
'''
    path = Path(output)
    if path.exists():
        click.echo(f"Error: {output} already exists. Use a different name.", err=True)
        sys.exit(1)

    path.write_text(example)
    click.echo(f"Created {output}")
    click.echo(f"Next: cortex-protocol validate {output}")


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True))
def validate(file: str):
    """Validate an agent spec file against the schema."""
    from .validator import validate_file

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation FAILED:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    click.echo(f"Valid: {spec.agent.name} — {spec.agent.description}")
    click.echo(f"  Tools: {', '.join(t.name for t in spec.tools) or 'none'}")
    click.echo(f"  Model: {spec.model.preferred}")
    click.echo(f"  Policies: max_turns={spec.policies.max_turns}, "
               f"approval={spec.policies.require_approval}, "
               f"forbidden={len(spec.policies.forbidden_actions)} rules")


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--target", "-t", required=True,
              help="Target runtime (or 'all')")
@click.option("--output", "-o", default="./output",
              help="Output directory")
@click.option("--model", "-m", default=None,
              help="Override model hint for system prompt generation")
@click.option("--registry-dir", default=None,
              help="Custom registry directory (default: ~/.cortex-protocol/registry)")
@click.option("--no-extends", is_flag=True, default=False,
              help="Skip extends resolution")
def compile(file: str, target: str, output: str, model: str, registry_dir: str, no_extends: bool):
    """Compile an agent spec to a target runtime."""
    from .validator import validate_file

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation failed — fix these errors first:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    if spec.extends and not no_extends:
        from .registry.local import LocalRegistry
        from .registry.resolver import resolve_extends
        reg = LocalRegistry(Path(registry_dir)) if registry_dir else LocalRegistry()
        spec = resolve_extends(spec, reg)

    if spec.policies.from_template:
        from .governance.templates import resolve_policy_template
        spec = spec.model_copy(update={"policies": resolve_policy_template(spec.policies)})

    if target == "all":
        targets = list(TARGET_REGISTRY.keys())
    elif target in TARGET_REGISTRY:
        targets = [target]
    else:
        click.echo(f"Unknown target: {target}", err=True)
        click.echo(f"Available: {', '.join(TARGET_REGISTRY.keys())}, all", err=True)
        sys.exit(1)

    output_root = Path(output)

    for target_name in targets:
        target_cls = TARGET_REGISTRY[target_name]

        if target_name == "system-prompt" and model:
            target_instance = target_cls(model_hint=model)
        else:
            target_instance = target_cls()

        files = target_instance.compile(spec)
        target_dir = output_root / target_name if len(targets) > 1 else output_root

        for f in files:
            fpath = target_dir / f.path
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(f.content)

        click.echo(f"[{target_name}] {len(files)} files → {target_dir}/")
        for f in files:
            click.echo(f"  {f.path} — {f.description}")

    click.echo(f"\nDone. Compiled {spec.agent.name} to {len(targets)} target(s).")


# ---------------------------------------------------------------------------
# lint  (Phase 2)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]),
              help="Output format (text or json)")
@click.option("--fail-on", "fail_on",
              type=click.Choice(["error", "warning", "any"]),
              default=None,
              help="Exit with code 1 if issues at this severity or above are found")
def lint(file: str, fmt: str, fail_on: str):
    """Lint an agent spec for policy completeness and governance quality.

    Scores the spec 0-100 and assigns a letter grade (A-F).
    Use --fail-on error in CI to block specs with critical issues.
    """
    from .linter import lint_file, Severity

    report = lint_file(file)

    if fmt == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        grade_color = {"A": "green", "B": "green", "C": "yellow", "D": "red", "F": "red"}
        grade = report.grade
        score_str = click.style(f"Score: {report.score}/100  Grade: {grade}",
                                fg=grade_color.get(grade, "white"), bold=True)
        click.echo(f"\n  {score_str}  ({report.spec_name})\n")

        for result in report.results:
            color = "green" if result.passed else (
                "red" if result.rule.severity == Severity.ERROR else
                "yellow" if result.rule.severity == Severity.WARNING else "blue"
            )
            icon = click.style(result.icon, fg=color)
            label = click.style(f"[{result.rule.severity.value.upper()}]", fg=color)
            click.echo(f"  {icon} {label} {result.rule.message}")
            if not result.passed and result.detail:
                click.echo(f"       {result.detail}")

        click.echo()

        if report.errors:
            click.echo(click.style(f"  {len(report.errors)} error(s)", fg="red"))
        if report.warnings:
            click.echo(click.style(f"  {len(report.warnings)} warning(s)", fg="yellow"))
        if not report.errors and not report.warnings:
            click.echo(click.style("  All checks passed", fg="green"))
        click.echo()

    # Exit codes for CI integration
    if fail_on:
        should_fail = False
        if fail_on == "any" and (report.errors or report.warnings or report.infos):
            should_fail = True
        elif fail_on == "warning" and (report.errors or report.warnings):
            should_fail = True
        elif fail_on == "error" and report.errors:
            should_fail = True
        if should_fail:
            sys.exit(1)


# ---------------------------------------------------------------------------
# diff  (Phase 2)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file_a", type=click.Path(exists=True))
@click.argument("file_b", type=click.Path(exists=True))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]),
              help="Output format (text or json)")
def diff(file_a: str, file_b: str, fmt: str):
    """Diff two agent spec files to see what changed.

    Highlights tool additions/removals, policy changes, and model config changes.
    Flags breaking changes that could affect deployed consumers.
    """
    from .differ import diff_files

    result = diff_files(file_a, file_b)

    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
        return

    click.echo(f"\n  Diff: {file_a} → {file_b}\n")

    if result.is_empty:
        click.echo(click.style("  No differences found.", fg="green"))
    else:
        if result.has_breaking_changes:
            click.echo(click.style("  ⚠  Breaking changes detected", fg="red", bold=True))
            click.echo()

        for line in result.summary_lines():
            if line.startswith("  +"):
                click.echo(click.style(line, fg="green"))
            elif line.startswith("  -"):
                click.echo(click.style(line, fg="red"))
            elif line.startswith("  ~"):
                click.echo(click.style(line, fg="yellow"))
            elif line.startswith("  ⚠"):
                pass  # already printed above
            else:
                click.echo(line)

    click.echo()


# ---------------------------------------------------------------------------
# list-targets
# ---------------------------------------------------------------------------

@main.command("list-targets")
def list_targets():
    """List available compilation targets."""
    click.echo("Available targets:\n")
    for name, cls in TARGET_REGISTRY.items():
        target = cls()
        click.echo(f"  {name:<20} {target.description}")
    click.echo(f"\n  {'all':<20} Compile to all targets at once")


# ---------------------------------------------------------------------------
# list-packs  (Phase 3)
# ---------------------------------------------------------------------------

@main.command("list-packs")
def list_packs():
    """List available agent packs from the built-in registry."""
    from .packs import PACK_REGISTRY

    click.echo("\n  Available packs:\n")
    for pack in PACK_REGISTRY:
        click.echo(f"  {pack['name']:<28} {pack['description']}")
        click.echo(f"  {'':28} agents: {', '.join(pack['agents'])}")
        click.echo()

    click.echo(f"  Install: cortex-protocol install <pack-name>")
    click.echo()


# ---------------------------------------------------------------------------
# install  (Phase 3)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("pack_name")
@click.option("--output", "-o", default=".", help="Directory to install into")
def install(pack_name: str, output: str):
    """Install an agent pack from the built-in registry.

    Example:
        cortex-protocol install incident-response
        cortex-protocol install customer-support --output ./agents
    """
    from .packs import install_pack

    out_dir = Path(output)
    installed = install_pack(pack_name, out_dir)

    if installed is None:
        click.echo(f"Error: pack '{pack_name}' not found.", err=True)
        click.echo("Run 'cortex-protocol list-packs' to see available packs.", err=True)
        sys.exit(1)

    click.echo(f"\n  Installed pack: {pack_name} → {out_dir}/\n")
    for fname in installed:
        click.echo(f"  {fname}")
    click.echo()
    click.echo("  Next: cortex-protocol validate <agent.yaml>")
    click.echo()


# ---------------------------------------------------------------------------
# generate-ci  (Phase 4)
# ---------------------------------------------------------------------------

@main.command("generate-ci")
@click.option("--platform", default="github",
              type=click.Choice(["github"]),
              help="CI platform to generate workflow for")
@click.option("--output", "-o", default=".github/workflows/cortex-protocol.yml",
              help="Output path for the workflow file")
@click.option("--spec", default="agent.yaml",
              help="Path to the agent spec file (relative to repo root)")
@click.option("--include-drift", is_flag=True, default=False,
              help="Include a drift-check job in the workflow")
@click.option("--drift-threshold", type=float, default=None,
              help="Minimum compliance score for drift check (e.g. 0.9)")
@click.option("--audit-log", default="./logs/audit_*.jsonl",
              help="Audit log path or glob pattern for drift check")
def generate_ci(platform: str, output: str, spec: str, include_drift: bool, drift_threshold: float, audit_log: str):
    """Generate a CI workflow that validates, lints, and compiles your agent spec.

    The generated workflow runs on every pull request and push to main.
    Use --fail-on to control what severity blocks merges.

    Example:
        cortex-protocol generate-ci
        cortex-protocol generate-ci --spec agents/my_agent.yaml
        cortex-protocol generate-ci --include-drift --drift-threshold 0.9
    """
    from .ci import generate_github_action

    drift_spec = spec if include_drift else None
    threshold = drift_threshold if include_drift else None
    content = generate_github_action(
        spec_path=spec,
        drift_spec=drift_spec,
        drift_threshold=threshold,
        audit_log_pattern=audit_log if include_drift else None,
    )
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)

    click.echo(f"\n  Generated CI workflow → {output}\n")
    click.echo("  What it does:")
    click.echo("    • validate — schema checks on every PR")
    click.echo("    • lint     — governance scoring (fails on errors)")
    click.echo("    • compile  — compiles to all 5 targets (dry-run check)")
    click.echo()
    click.echo("  Commit it: git add .github/workflows/cortex-protocol.yml")
    click.echo()


# ---------------------------------------------------------------------------
# audit  (Phase 4)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("log_file", type=click.Path(exists=True))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]),
              help="Output format (text or json)")
@click.option("--run", "run_id", default=None,
              help="Filter events by run ID")
def audit(log_file: str, fmt: str, run_id: str):
    """View and summarize a runtime audit log.

    Reads a JSONL audit log produced by PolicyEnforcer and displays
    enforcement events, violations, and aggregate stats.

    Example:
        cortex-protocol audit ./logs/audit_support-agent.jsonl
        cortex-protocol audit audit.jsonl --format json
        cortex-protocol audit audit.jsonl --run abc123def456
    """
    from .governance.audit import AuditLog

    log = AuditLog.from_file(Path(log_file))
    events = log.events_for_run(run_id) if run_id else log.events()

    if fmt == "json":
        summary = log.summary()
        if run_id:
            summary["filter_run_id"] = run_id
            summary["total_events"] = len(events)
            summary["violations"] = len([e for e in events if not e.allowed])
        click.echo(json.dumps(summary, indent=2))
        return

    # Text output
    summary = log.summary()
    total = summary["total_events"]
    violations = summary["violations"]

    click.echo(f"\n  Audit Log: {log_file}")
    click.echo(f"  Events: {total}  Violations: {violations}  Runs: {summary['runs']}")

    if summary["policies_triggered"]:
        click.echo(f"  Policies triggered: {', '.join(summary['policies_triggered'])}")

    if run_id:
        click.echo(f"  Filter: run_id={run_id} ({len(events)} events)")

    click.echo()

    for event in events:
        color = "green" if event.allowed else "red"
        icon = click.style("✓" if event.allowed else "✗", fg=color)
        ts = event.timestamp[:19]  # trim microseconds
        type_label = click.style(f"[{event.event_type}]", fg=color)
        parts = [f"  {icon} {ts} {type_label}"]

        if event.tool_name:
            parts.append(f"tool={event.tool_name}")
        if event.policy:
            parts.append(f"policy={event.policy}")
        if event.detail:
            parts.append(event.detail)

        click.echo("  ".join(parts))

    click.echo()


# ---------------------------------------------------------------------------
# publish  (Phase 3)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--version", "-v", "ver", required=True,
              help="Semver version to publish (e.g. 1.0.0)")
@click.option("--registry-dir", default=None,
              help="Custom registry directory (default: ~/.cortex-protocol/registry)")
@click.option("--remote", default=None,
              help="Remote GitHub registry, e.g. github:owner/repo")
def publish(file: str, ver: str, registry_dir: str, remote: str):
    """Publish an agent spec to the local or remote registry.

    Example:
        cortex-protocol publish agent.yaml --version 1.0.0
        cortex-protocol publish agent.yaml -v 2.0.0
        cortex-protocol publish agent.yaml -v 1.0.0 --remote github:Phani3108/cortex-agents
    """
    from .validator import validate_file
    from .registry.local import LocalRegistry

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation failed:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    if remote:
        from .registry.remote import RemoteRegistry
        repo = remote.removeprefix("github:")
        reg = RemoteRegistry(repo)
        try:
            url = reg.publish(spec, ver)
            click.echo(f"Published {spec.agent.name}@{ver} -> {url}")
        except Exception as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)
    else:
        reg = LocalRegistry(Path(registry_dir)) if registry_dir else LocalRegistry()
        try:
            path = reg.publish(spec, ver)
            click.echo(f"Published {spec.agent.name}@{ver} -> {path}")
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(1)


# ---------------------------------------------------------------------------
# search  (Phase 3)
# ---------------------------------------------------------------------------

@main.command()
@click.option("--tag", "-t", multiple=True, help="Filter by tag")
@click.option("--compliance", "-c", multiple=True, help="Filter by compliance standard")
@click.option("--owner", "-o", default=None, help="Filter by owner")
@click.option("--name", "-n", default=None, help="Filter by name substring")
@click.option("--registry-dir", default=None, help="Custom registry directory")
@click.option("--remote", default=None, help="Remote GitHub registry, e.g. github:owner/repo")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def search(tag, compliance, owner, name, registry_dir, remote, fmt):
    """Search the registry for agents by metadata.

    Example:
        cortex-protocol search --tag payment
        cortex-protocol search --compliance pci-dss --format json
        cortex-protocol search --owner platform-team
        cortex-protocol search --tag payment --remote github:Phani3108/cortex-agents
    """
    if remote:
        from .registry.remote import RemoteRegistry
        repo = remote.removeprefix("github:")
        reg = RemoteRegistry(repo)
        results_list = reg.search(
            tags=list(tag) if tag else None,
            compliance=list(compliance) if compliance else None,
            owner=owner,
            name_contains=name,
        )
        if fmt == "json":
            click.echo(json.dumps(results_list, indent=2))
            return
        if not results_list:
            click.echo("  No agents found matching criteria.")
            return
        click.echo(f"\n  Found {len(results_list)} agent(s):\n")
        for r in results_list:
            click.echo(f"  {r['name']}@{r['version']}")
            click.echo(f"    {r['description']}")
            if r.get("tags"):
                click.echo(f"    tags: {', '.join(r['tags'])}")
        return

    from .registry.local import LocalRegistry

    reg = LocalRegistry(Path(registry_dir)) if registry_dir else LocalRegistry()
    results = reg.search(
        tags=list(tag) if tag else None,
        compliance=list(compliance) if compliance else None,
        owner=owner,
        name_contains=name,
    )

    if fmt == "json":
        out = [
            {
                "name": meta.name,
                "version": meta.latest,
                "description": spec.agent.description,
                "owner": spec.metadata.owner if spec.metadata else "",
                "tags": spec.metadata.tags if spec.metadata else [],
            }
            for meta, spec in results
        ]
        click.echo(json.dumps(out, indent=2))
        return

    if not results:
        click.echo("  No agents found matching criteria.")
        return

    click.echo(f"\n  Found {len(results)} agent(s):\n")
    for meta, spec in results:
        click.echo(f"  {meta.name}@{meta.latest}")
        click.echo(f"    {spec.agent.description}")
        if spec.metadata:
            if spec.metadata.tags:
                click.echo(f"    tags: {', '.join(spec.metadata.tags)}")
            if spec.metadata.owner:
                click.echo(f"    owner: {spec.metadata.owner}")
        click.echo()


# ---------------------------------------------------------------------------
# registry-list  (Phase 3)
# ---------------------------------------------------------------------------

@main.command("registry-list")
@click.option("--registry-dir", default=None, help="Custom registry directory")
def registry_list(registry_dir: str):
    """List all agents in the local registry."""
    from .registry.local import LocalRegistry

    reg = LocalRegistry(Path(registry_dir)) if registry_dir else LocalRegistry()
    agents = reg.list_agents()

    if not agents:
        click.echo("  Registry is empty. Publish with: cortex-protocol publish <file> -v 1.0.0")
        return

    click.echo(f"\n  {len(agents)} agent(s) in registry:\n")
    for meta in agents:
        versions = ", ".join(v.version for v in meta.versions)
        click.echo(f"  {meta.name:<28} latest: {meta.latest}  versions: [{versions}]")
    click.echo()


# ---------------------------------------------------------------------------
# compile-network  (Phase 6)
# ---------------------------------------------------------------------------

@main.command("compile-network")
@click.argument("file", type=click.Path(exists=True))
@click.option("--target", "-t", default="langgraph",
              type=click.Choice(["langgraph", "openai-sdk", "system-prompt"]),
              help="Target runtime for the multi-agent network")
@click.option("--output", "-o", default=None,
              help="Output file path (default: stdout)")
@click.option("--a2a-cards", "a2a_cards", is_flag=True, default=False,
              help="Also generate A2A agent cards for each agent")
@click.option("--base-url", default="http://localhost",
              help="Base URL for A2A agent cards")
def compile_network(file: str, target: str, output: str, a2a_cards: bool, base_url: str):
    """Compile a multi-agent network spec into orchestration code.

    Takes a network YAML file that defines multiple agents, their routes,
    shared tools, and policies — and generates a multi-agent scaffold.

    Example:
        cortex-protocol compile-network network.yaml --target langgraph
        cortex-protocol compile-network network.yaml --target openai-sdk -o network.py
        cortex-protocol compile-network network.yaml --a2a-cards
    """
    from .network.models import NetworkSpec
    from .network.graph import validate_network, compile_network as _compile, resolve_agent_specs
    from .network.a2a import generate_network_a2a_cards

    try:
        network = NetworkSpec.from_yaml(file)
    except Exception as e:
        click.echo(f"Error parsing network spec: {e}", err=True)
        sys.exit(1)

    # Validate
    result = validate_network(network)
    if not result.valid:
        click.echo("Network validation failed:", err=True)
        for err in result.errors:
            click.echo(f"  ERROR: {err}", err=True)
        sys.exit(1)

    for warning in result.warnings:
        click.echo(f"  WARNING: {warning}", err=True)

    # Resolve agent specs from file paths
    base_dir = Path(file).parent
    agent_specs = resolve_agent_specs(network, base_dir)
    resolved_count = sum(1 for s in agent_specs.values() if s is not None)

    # Compile
    code = _compile(network, target=target, agent_specs=agent_specs)

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(code)
        click.echo(f"Compiled network '{network.name}' → {output}")
    else:
        click.echo(code)

    click.echo(f"\n  Network: {network.name} ({len(network.agents)} agents, {len(network.routes)} routes)")
    click.echo(f"  Target: {target}")
    click.echo(f"  Resolved specs: {resolved_count}/{len(network.agents)}")

    # A2A cards
    if a2a_cards:
        cards = generate_network_a2a_cards(network, agent_specs, base_url=base_url)
        cards_dir = Path(output).parent / "a2a_cards" if output else Path("a2a_cards")
        cards_dir.mkdir(parents=True, exist_ok=True)

        for name, card in cards.items():
            card_path = cards_dir / f"{name}.agent.json"
            card_path.write_text(json.dumps(card, indent=2))
            click.echo(f"  A2A card: {card_path}")

        click.echo(f"\n  Generated {len(cards)} A2A agent cards → {cards_dir}/")

    click.echo()


# ---------------------------------------------------------------------------
# generate-a2a  (Phase 6)
# ---------------------------------------------------------------------------

@main.command("generate-a2a")
@click.argument("file", type=click.Path(exists=True))
@click.option("--framework", "-f", default="fastapi",
              type=click.Choice(["fastapi", "flask"]),
              help="Web framework for the A2A handler")
@click.option("--output", "-o", default=None,
              help="Output file path (default: a2a_server.py)")
@click.option("--url", default="http://localhost:8000",
              help="Base URL for the agent card")
def generate_a2a(file: str, framework: str, output: str, url: str):
    """Generate an A2A (Agent-to-Agent) server from an agent spec.

    Creates a web server that implements Google's A2A protocol,
    with agent card discovery and JSON-RPC task endpoints.

    Example:
        cortex-protocol generate-a2a agent.yaml
        cortex-protocol generate-a2a agent.yaml --framework flask
        cortex-protocol generate-a2a agent.yaml --url https://my-agent.example.com
    """
    from .validator import validate_file
    from .network.a2a import generate_a2a_handler, generate_a2a_card_json

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation failed:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    handler_code = generate_a2a_handler(spec, framework=framework)
    out_path = Path(output) if output else Path("a2a_server.py")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(handler_code)

    click.echo(f"\n  Generated A2A server: {out_path}")
    click.echo(f"  Framework: {framework}")
    click.echo(f"  Agent: {spec.agent.name}")
    click.echo(f"  Skills: {len(spec.tools)}")
    click.echo(f"\n  Run: uvicorn {out_path.stem}:app --reload" if framework == "fastapi"
               else f"\n  Run: python {out_path}")
    click.echo(f"  Card: {url}/.well-known/agent.json")
    click.echo()


# ---------------------------------------------------------------------------
# compliance-report  (Phase 10)
# ---------------------------------------------------------------------------

@main.command("compliance-report")
@click.argument("log_file", type=click.Path(exists=True))
@click.option("--standard", default="general",
              type=click.Choice(["general", "soc2", "gdpr", "hipaa", "pci-dss"]),
              help="Compliance standard to map to")
@click.option("--output", "-o", default=None,
              help="Write report to file instead of stdout")
@click.option("--agent-version", default="", help="Agent version to include in report")
@click.option("--spec", "spec_file", default=None, type=click.Path(exists=True),
              help="Agent spec file for richer control evaluation")
def compliance_report(log_file: str, standard: str, output: str, agent_version: str, spec_file: str):
    """Generate a compliance report from an audit log.

    Example:
        cortex-protocol compliance-report audit.jsonl
        cortex-protocol compliance-report audit.jsonl --standard soc2
        cortex-protocol compliance-report audit.jsonl --output report.md
    """
    from .governance.audit import AuditLog
    from .governance.compliance import generate_compliance_report

    log = AuditLog.from_file(Path(log_file))
    spec = None
    if spec_file:
        from .validator import validate_file
        spec, errors = validate_file(spec_file)
        if errors:
            spec = None
    report = generate_compliance_report(log, standard=standard, agent_version=agent_version, spec=spec)

    if output:
        Path(output).write_text(report)
        click.echo(f"Compliance report ({standard}) -> {output}")
    else:
        click.echo(report)


# ---------------------------------------------------------------------------
# migrate  (Phase 9)
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--output", "-o", default=None,
              help="Write migrated spec to this file instead of in-place")
def migrate(file: str, output: str):
    """Migrate an agent spec to the latest schema version.

    Migrates in-place with a .bak backup unless --output is given.

    Example:
        cortex-protocol migrate agent.yaml
        cortex-protocol migrate agent.yaml --output agent_v3.yaml
    """
    import shutil
    import yaml as _yaml
    from .migrations import migrate as _migrate

    with open(file) as f:
        spec_dict = _yaml.safe_load(f)

    original_version = spec_dict.get("version", "0.1")
    migrated = _migrate(spec_dict)
    new_version = migrated.get("version", "0.1")

    content = _yaml.dump(migrated, default_flow_style=False, sort_keys=False)

    if output:
        Path(output).write_text(content)
        click.echo(f"Migrated {file} ({original_version} -> {new_version}) -> {output}")
    else:
        backup = file + ".bak"
        shutil.copy2(file, backup)
        Path(file).write_text(content)
        click.echo(f"Migrated {file} ({original_version} -> {new_version}) [backup: {backup}]")


# ---------------------------------------------------------------------------
# list-templates
# ---------------------------------------------------------------------------

@main.command("list-templates")
def list_templates_cmd():
    """List available built-in policy templates."""
    from .governance.templates import list_templates

    templates = list_templates()
    click.echo("\n  Built-in policy templates:\n")
    for name, info in templates.items():
        click.echo(f"  {name}")
        click.echo(f"    max_turns: {info['max_turns']}")
        if info["require_approval"]:
            click.echo(f"    require_approval: {', '.join(info['require_approval'])}")
        if info["forbidden_actions"]:
            click.echo(f"    forbidden_actions: {', '.join(info['forbidden_actions'])}")
        click.echo()


# ---------------------------------------------------------------------------
# fleet-report
# ---------------------------------------------------------------------------

@main.command("fleet-report")
@click.argument("log_files", nargs=-1, type=click.Path(exists=True))
@click.option("--standard", default="general", type=click.Choice(["general", "soc2", "gdpr"]))
@click.option("--output", "-o", default=None)
@click.option("--specs-dir", default=None, type=click.Path(exists=True),
              help="Directory of agent YAML specs for drift detection")
def fleet_report(log_files, standard, output, specs_dir):
    """Generate a fleet-wide compliance report from multiple audit logs."""
    from .governance.fleet import generate_fleet_report

    if not log_files:
        click.echo("Error: provide at least one log file.", err=True)
        sys.exit(1)

    paths = [Path(f) for f in log_files]

    specs = None
    if specs_dir:
        from .validator import validate_file
        specs = {}
        for yaml_file in Path(specs_dir).glob("*.yaml"):
            spec, errors = validate_file(str(yaml_file))
            if spec and not errors:
                specs[spec.agent.name] = spec

    report = generate_fleet_report(paths, standard=standard, specs=specs)

    if output:
        Path(output).write_text(report)
        click.echo(f"Fleet report written to {output}")
    else:
        click.echo(report)


# ---------------------------------------------------------------------------
# drift-check
# ---------------------------------------------------------------------------

@main.command("drift-check")
@click.argument("spec_file", type=click.Path(exists=True))
@click.argument("log_file", type=click.Path(exists=True))
@click.option("--fail-on", "fail_threshold", type=float, default=None,
              help="Exit code 1 if compliance score below this (e.g. 0.9)")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def drift_check(spec_file, log_file, fail_threshold, fmt):
    """Compare agent behavior (audit log) against its spec.
    Detects undeclared tools, policy violations, and approval bypasses."""
    from .validator import validate_file
    from .governance.audit import AuditLog
    from .governance.drift import detect_drift

    spec, errors = validate_file(spec_file)
    if errors:
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    log = AuditLog.from_file(Path(log_file))
    report = detect_drift(spec, log)

    if fmt == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        color = "green" if report.compliance_score >= 0.9 else "yellow" if report.compliance_score >= 0.7 else "red"
        click.echo(f"\n  Drift Check: {report.agent_name}")
        click.echo(click.style(f"  Compliance Score: {report.compliance_score:.1%}", fg=color, bold=True))
        click.echo(f"  Runs: {report.total_runs}  Events: {report.total_events}")
        click.echo()
        for detail in report.details:
            icon = "!" if "exceeded" in detail or "without" in detail or "Undeclared" in detail else "i"
            click.echo(f"  [{icon}] {detail}")
        click.echo()

    if fail_threshold is not None and report.compliance_score < fail_threshold:
        sys.exit(1)


if __name__ == "__main__":
    main()
