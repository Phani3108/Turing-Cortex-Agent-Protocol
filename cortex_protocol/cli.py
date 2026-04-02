"""Cortex Protocol CLI — init, validate, compile, lint, diff, list-targets, list-packs, install, generate-ci."""

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
def compile(file: str, target: str, output: str, model: str):
    """Compile an agent spec to a target runtime."""
    from .validator import validate_file

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation failed — fix these errors first:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

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
def generate_ci(platform: str, output: str, spec: str):
    """Generate a CI workflow that validates, lints, and compiles your agent spec.

    The generated workflow runs on every pull request and push to main.
    Use --fail-on to control what severity blocks merges.

    Example:
        cortex-protocol generate-ci
        cortex-protocol generate-ci --spec agents/my_agent.yaml
    """
    from .ci import generate_github_action

    content = generate_github_action(spec_path=spec)
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
def publish(file: str, ver: str, registry_dir: str):
    """Publish an agent spec to the local registry with a semver version.

    Example:
        cortex-protocol publish agent.yaml --version 1.0.0
        cortex-protocol publish agent.yaml -v 2.0.0
    """
    from .validator import validate_file
    from .registry.local import LocalRegistry

    spec, errors = validate_file(file)
    if errors:
        click.echo("Validation failed:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

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
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def search(tag, compliance, owner, name, registry_dir, fmt):
    """Search the registry for agents by metadata.

    Example:
        cortex-protocol search --tag payment
        cortex-protocol search --compliance pci-dss --format json
        cortex-protocol search --owner platform-team
    """
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


if __name__ == "__main__":
    main()
