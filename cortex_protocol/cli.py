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

_DEFAULT_SPEC_YAML = '''\
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


@main.command()
@click.argument("output", default="agent.yaml")
@click.option("--interactive", "-i", is_flag=True,
              help="Walk through prompts to seed an agent spec from a pack.")
def init(output: str, interactive: bool):
    """Create an example agent spec file."""
    path = Path(output)
    if path.exists():
        click.echo(f"Error: {output} already exists. Use a different name.", err=True)
        sys.exit(1)

    if interactive:
        content, name = _interactive_init()
        if name:
            path = Path(name if name.endswith((".yaml", ".yml")) else f"{name}.yaml")
            if path.exists():
                click.echo(f"Error: {path} already exists.", err=True)
                sys.exit(1)
    else:
        content = _DEFAULT_SPEC_YAML

    path.write_text(content)
    click.echo(f"Created {path}")

    # Inline validate + lint feedback so the user sees governance quality
    # immediately rather than having to chain another command.
    try:
        from .validator import validate_file
        from .linter import lint_file
        spec, errors = validate_file(str(path))
        if errors:
            click.echo("  ! validation issues:")
            for e in errors:
                click.echo(f"    - {e}")
        else:
            report = lint_file(str(path))
            click.echo(f"  lint: {report.score}/100 (grade {report.grade})")
    except Exception as e:
        click.echo(f"  (skipped inline checks: {e})")

    click.echo(f"\nNext:  cortex-protocol connect && cortex-protocol compile {path} --target claude-sdk --run")


def _interactive_init() -> tuple[str, str | None]:
    """Run the interactive wizard; return (yaml_content, filename_hint)."""
    from .packs import PACK_REGISTRY, get_pack_spec_content, _PACKS

    click.echo("\n  Turing — interactive spec wizard\n")
    name = click.prompt("  agent name", default="my-agent").strip()
    description = click.prompt("  description",
                                default="A helpful assistant").strip()

    click.echo("\n  packs:")
    for i, p in enumerate(PACK_REGISTRY, 1):
        click.echo(f"    {i}. {p['name']:<20} {p['description']}")
    click.echo(f"    {len(PACK_REGISTRY) + 1}. (none — start from the default template)")
    choice = click.prompt("  pick a pack", type=int, default=len(PACK_REGISTRY) + 1)

    if 1 <= choice <= len(PACK_REGISTRY):
        pack_name = PACK_REGISTRY[choice - 1]["name"]
        pack = _PACKS.get(pack_name, {})
        # First YAML file in the pack is a fine default.
        first = next(iter(pack.keys()), None)
        content = get_pack_spec_content(pack_name, first) if first else _DEFAULT_SPEC_YAML
    else:
        content = _DEFAULT_SPEC_YAML

    # Swap in the user's name + description.
    import yaml
    data = yaml.safe_load(content)
    data.setdefault("agent", {})
    data["agent"]["name"] = name
    data["agent"]["description"] = description

    compliance = click.prompt(
        "  compliance tags (comma-separated, blank to skip)", default="").strip()
    if compliance:
        data.setdefault("metadata", {})
        data["metadata"].setdefault("tags", [])
        data["metadata"]["compliance"] = [c.strip() for c in compliance.split(",") if c.strip()]

    max_cost = click.prompt(
        "  max cost per run in USD (blank to skip)", default="", show_default=False).strip()
    if max_cost:
        try:
            data.setdefault("policies", {})["max_cost_usd"] = float(max_cost)
        except ValueError:
            click.echo("  (ignored non-numeric max cost)")

    yaml_text = yaml.dump(data, sort_keys=False, default_flow_style=False)
    return yaml_text, name


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
@click.option("--run", "run_after", is_flag=True, default=False,
              help="After compilation, attach PolicyEnforcer and run a dry turn so you see enforcement in action.")
@click.option("--manifest", "manifest_out", default=None,
              type=click.Path(dir_okay=False),
              help="Write a supply-chain manifest of this build to the given path.")
@click.option("--signing-key", "manifest_signing_key", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Ed25519 PEM private key used to sign the manifest (when --manifest is set).")
def compile(file: str, target: str, output: str, model: str, registry_dir: str,
             no_extends: bool, run_after: bool,
             manifest_out: str | None, manifest_signing_key: str | None):
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

    if manifest_out:
        _emit_manifest(
            spec, target=targets[0] if len(targets) == 1 else "all",
            spec_yaml=Path(file).read_text(),
            output_root=output_root,
            manifest_path=Path(manifest_out),
            signing_key_path=manifest_signing_key,
        )

    if run_after:
        _dry_run_enforcement(spec)


def _emit_manifest(spec, *, target: str, spec_yaml: str, output_root: Path,
                   manifest_path: Path, signing_key_path: str | None) -> None:
    from .supply_chain import build_manifest, write_manifest
    from .licensing import load_private_key

    output_files: dict[str, bytes] = {}
    for fpath in output_root.rglob("*"):
        if fpath.is_file():
            rel = fpath.relative_to(output_root).as_posix()
            output_files[rel] = fpath.read_bytes()

    priv = None
    pub = None
    if signing_key_path:
        priv = load_private_key(Path(signing_key_path).read_text())
        pub = priv.public_key()

    manifest = build_manifest(
        spec=spec, target=target, spec_yaml=spec_yaml,
        output_files=output_files, private_key=priv, public_key=pub,
    )
    write_manifest(manifest, manifest_path)
    click.echo(f"  manifest → {manifest_path}"
               f"{'  (signed)' if manifest.signature else ''}")


def _dry_run_enforcement(spec) -> None:
    """Show the spec executing through PolicyEnforcer — no real model call.

    For an agent to actually run end-to-end we'd need API keys and framework
    deps. Instead, we attach PolicyEnforcer, increment a turn, and exercise
    each declared tool. The user sees which tools would pass, which would
    require approval, and which would be blocked.
    """
    from .governance.enforcer import PolicyEnforcer
    from .governance.exceptions import (
        ApprovalRequired, MaxTurnsExceeded, BudgetExceeded, ForbiddenActionDetected,
    )

    click.echo("\n  Dry run — PolicyEnforcer attached")
    click.echo(f"  agent: {spec.agent.name}")

    enforcer = PolicyEnforcer(spec)
    enforcer.increment_turn()

    for tool in spec.tools:
        try:
            enforcer.check_tool_call(tool.name, {})
            click.echo(f"    [allowed] {tool.name}")
        except (ApprovalRequired, BudgetExceeded) as v:
            click.echo(f"    [blocked] {tool.name} — {v.policy}: {v.detail}")
        except (MaxTurnsExceeded, ForbiddenActionDetected) as v:
            click.echo(f"    [blocked] {tool.name} — {v.policy}")

    click.echo(f"  run_id: {enforcer.run_id}  turn: {enforcer.turn_count}")
    click.echo("\n  To run the agent against a real model, open the generated files and fill in the tool bodies.")


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


# ---------------------------------------------------------------------------
# cost-report
# ---------------------------------------------------------------------------

@main.command("cost-report")
@click.argument("log_file", type=click.Path(exists=True))
@click.option("--by", "group_by", default="agent",
              type=click.Choice(["agent", "run", "tool", "model", "day"]),
              help="How to group the totals.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def cost_report(log_file, group_by, fmt):
    """Aggregate token usage + USD cost from an audit log."""
    from .governance.audit import AuditLog

    log = AuditLog.from_file(Path(log_file))

    # Keep only usage events; each carries model, tokens, cost.
    usage = [e for e in log.events() if e.event_type == "usage"]
    budget_blocks = [e for e in log.events() if e.event_type == "budget_blocked"]

    buckets: dict[str, dict] = {}
    for e in usage:
        if group_by == "agent":
            key = e.agent or "unknown"
        elif group_by == "run":
            key = e.run_id or "unknown"
        elif group_by == "tool":
            key = e.tool_name or "(llm)"
        elif group_by == "model":
            key = e.model or "unknown"
        else:  # day
            key = (e.timestamp or "unknown")[:10]
        row = buckets.setdefault(key, {
            "input_tokens": 0, "output_tokens": 0,
            "cost_usd": 0.0, "events": 0,
        })
        row["input_tokens"] += e.input_tokens or 0
        row["output_tokens"] += e.output_tokens or 0
        row["cost_usd"] += e.cost_usd or 0.0
        row["events"] += 1

    totals = {
        "input_tokens": sum(r["input_tokens"] for r in buckets.values()),
        "output_tokens": sum(r["output_tokens"] for r in buckets.values()),
        "cost_usd": sum(r["cost_usd"] for r in buckets.values()),
        "events": sum(r["events"] for r in buckets.values()),
        "budget_blocks": len(budget_blocks),
    }

    if fmt == "json":
        click.echo(json.dumps(
            {"group_by": group_by, "buckets": buckets, "totals": totals},
            indent=2,
        ))
        return

    click.echo(f"\n  Cost Report ({group_by})")
    click.echo(f"  {'key':<24} {'events':>7} {'in_tok':>10} {'out_tok':>10} {'cost_usd':>12}")
    click.echo("  " + "-" * 65)
    for key in sorted(buckets, key=lambda k: buckets[k]["cost_usd"], reverse=True):
        r = buckets[key]
        click.echo(
            f"  {str(key)[:24]:<24} {r['events']:>7} "
            f"{r['input_tokens']:>10} {r['output_tokens']:>10} "
            f"${r['cost_usd']:>10.4f}"
        )
    click.echo("  " + "-" * 65)
    click.echo(
        f"  {'TOTAL':<24} {totals['events']:>7} "
        f"{totals['input_tokens']:>10} {totals['output_tokens']:>10} "
        f"${totals['cost_usd']:>10.4f}"
    )
    if totals["budget_blocks"]:
        click.echo()
        click.echo(click.style(
            f"  {totals['budget_blocks']} budget_blocked event(s) in this log.",
            fg="yellow",
        ))
    click.echo()


# ---------------------------------------------------------------------------
# policy — policy pack marketplace
# ---------------------------------------------------------------------------

@main.group("policy")
def policy_group():
    """Browse, install, and publish policy packs (templates)."""
    pass


@policy_group.command("list")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def policy_list(fmt):
    """List locally-installed policy packs."""
    from .registry.marketplace import LocalPolicyMarketplace

    market = LocalPolicyMarketplace()
    rows = market.list_packs()
    if fmt == "json":
        click.echo(json.dumps([r.to_dict() for r in rows], indent=2))
        return
    if not rows:
        click.echo("  (no packs installed — try `policy search` or `policy install`)")
        return
    click.echo("\n  Installed policy packs:")
    for m in rows:
        click.echo(f"  - {m.name:<28} latest={m.latest}  ({len(m.versions)} version(s))")


@policy_group.command("install")
@click.argument("source")
@click.option("--version", default=None, help="Specific version (defaults to latest).")
def policy_install(source, version):
    """Install a policy pack from a local YAML file or the Cloud marketplace.

    If SOURCE is a path, the file is installed verbatim. Otherwise it is
    treated as a pack name and pulled from the Cloud marketplace (Pro).
    """
    from .registry.marketplace import (
        CloudPolicyMarketplace,
        LocalPolicyMarketplace,
        PolicyPack,
    )

    local = LocalPolicyMarketplace()
    p = Path(source)

    if p.exists() and p.is_file():
        pack = PolicyPack.from_yaml(p.read_text())
    else:
        from .cloud import CloudClient
        from .licensing import Feature, get_entitlements, has_feature

        if not has_feature(Feature.HOSTED_REGISTRY):
            ent = get_entitlements()
            click.echo(
                f"Error: Cloud marketplace install requires the Pro tier. "
                f"Current tier: {ent.tier.value}.",
                err=True,
            )
            sys.exit(1)
        client = CloudClient.from_environment()
        remote = CloudPolicyMarketplace(client)
        pack = remote.get(source, version)
        if pack is None:
            click.echo(f"Error: pack '{source}' not found.", err=True)
            sys.exit(1)

    path = local.install(pack)
    click.echo(f"  Installed {pack.name}@{pack.version} → {path}")


@policy_group.command("uninstall")
@click.argument("name")
def policy_uninstall(name):
    """Remove all versions of an installed policy pack."""
    from .registry.marketplace import LocalPolicyMarketplace

    if LocalPolicyMarketplace().uninstall(name):
        click.echo(f"  Removed {name}")
    else:
        click.echo(f"  Not installed: {name}")


@policy_group.command("search")
@click.option("--tag", default=None)
@click.option("--compliance", default=None)
@click.option("--query", default=None)
@click.option("--remote", is_flag=True, default=False,
              help="Search the Cloud marketplace instead of local packs.")
def policy_search(tag, compliance, query, remote):
    """Search installed packs, or (with --remote) the Cloud marketplace."""
    from .registry.marketplace import (
        CloudPolicyMarketplace,
        LocalPolicyMarketplace,
    )

    if remote:
        from .cloud import CloudClient
        from .licensing import Feature, get_entitlements, has_feature
        if not has_feature(Feature.HOSTED_REGISTRY):
            ent = get_entitlements()
            click.echo(
                f"Error: Cloud marketplace search requires the Pro tier. "
                f"Current tier: {ent.tier.value}.", err=True,
            )
            sys.exit(1)
        packs = CloudPolicyMarketplace(CloudClient.from_environment()).search(
            tag=tag, compliance=compliance, query=query,
        )
    else:
        packs = LocalPolicyMarketplace().search(
            tag=tag, compliance=compliance, query=query,
        )

    if not packs:
        click.echo("  (no matches)")
        return
    for p in packs:
        click.echo(f"  {p.name}@{p.version:<8} {p.description}")
        if p.tags:
            click.echo(f"    tags: {', '.join(p.tags)}")


@policy_group.command("publish")
@click.argument("pack_path", type=click.Path(exists=True, dir_okay=False))
def policy_publish(pack_path):
    """Publish a policy pack YAML to the Cloud marketplace (Pro)."""
    from .cloud import CloudClient
    from .licensing import Feature, get_entitlements, has_feature
    from .registry.marketplace import CloudPolicyMarketplace, PolicyPack

    if not has_feature(Feature.HOSTED_REGISTRY):
        ent = get_entitlements()
        click.echo(
            f"Error: publishing to the Cloud marketplace requires the Pro tier. "
            f"Current tier: {ent.tier.value}.", err=True,
        )
        sys.exit(1)

    pack = PolicyPack.from_yaml(Path(pack_path).read_text())
    client = CloudClient.from_environment()
    url = CloudPolicyMarketplace(client).publish(pack)
    click.echo(f"  Published {pack.name}@{pack.version}")
    if url:
        click.echo(f"  {url}")


# ---------------------------------------------------------------------------
# simulate — offline red-team harness against an agent spec
# ---------------------------------------------------------------------------

@main.command("simulate")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--scenarios", "scenario_paths", multiple=True,
              type=click.Path(exists=True),
              help="Additional scenario file or directory (repeatable).")
@click.option("--no-bundled", is_flag=True, default=False,
              help="Skip the scenarios shipped with Turing.")
@click.option("--fail-on-miss", is_flag=True, default=False,
              help="Exit non-zero if any scenario FAILs.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def simulate(spec_file, scenario_paths, no_bundled, fail_on_miss, fmt):
    """Run adversarial scenarios against a spec. Offline red-team for policies."""
    from .simulate import load_scenarios, run_scenarios
    from .validator import validate_file

    spec, errors = validate_file(spec_file)
    if spec is None:
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    scenarios = load_scenarios(
        [Path(p) for p in scenario_paths],
        include_bundled=not no_bundled,
    )
    if not scenarios:
        click.echo("Error: no scenarios to run.", err=True)
        sys.exit(1)

    report = run_scenarios(spec, scenarios)

    if fmt == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        color = "green" if report.failed == 0 else "red"
        click.echo(f"\n  Simulation: {report.total} scenario(s)")
        click.echo(click.style(
            f"  passed: {report.passed}   failed: {report.failed}   "
            f"({report.pass_rate:.0%})",
            fg=color, bold=True,
        ))
        for r in report.results:
            tag = "PASS" if r.passed else "FAIL"
            tagged = click.style(f"[{tag}]", fg="green" if r.passed else "red")
            click.echo(f"    {tagged} ({r.severity:<8}) {r.scenario_id}  {r.name}")
            if not r.passed:
                for f in r.findings:
                    if "[FAIL]" in f:
                        click.echo(f"      {f.strip()}")
        click.echo()

    if fail_on_miss and report.failed > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# replay — re-decide historical tool calls against the current spec
# ---------------------------------------------------------------------------

@main.command("replay")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("log_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
@click.option("--fail-on-regression", is_flag=True, default=False,
              help="Exit 1 if the replay produces any newly_blocked or newly_allowed decisions.")
def replay_cmd(spec_file, log_file, fmt, fail_on_regression):
    """Replay an audit log against the current spec and report drift in decisions."""
    from .governance.audit import AuditLog
    from .governance.replay import replay
    from .validator import validate_file

    spec, errors = validate_file(spec_file)
    if spec is None:
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    log = AuditLog.from_file(Path(log_file))
    report = replay(spec, log)

    if fmt == "json":
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        color = "green" if report.regression_count == 0 else "yellow"
        click.echo(f"\n  Replay: {report.total_tool_events} tool events")
        click.echo(click.style(
            f"  Regressions: {report.regression_count} "
            f"(newly_blocked={len(report.newly_blocked)}, "
            f"newly_allowed={len(report.newly_allowed)})",
            fg=color, bold=True,
        ))
        for d in report.newly_blocked[:10]:
            click.echo(f"    [!] turn {d.turn} tool={d.tool_name}  "
                       f"was allowed → now blocked by {d.replay_policy}")
        for d in report.newly_allowed[:10]:
            click.echo(f"    [?] turn {d.turn} tool={d.tool_name}  "
                       f"was blocked → now allowed")
        click.echo()

    if fail_on_regression and report.regression_count > 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# manifest-verify — re-hash the compiled outputs against their manifest
# ---------------------------------------------------------------------------

@main.command("manifest-verify")
@click.argument("manifest_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--artifacts-dir", "artifacts_dir", default=None,
              type=click.Path(exists=True, file_okay=False),
              help="Where the compiled outputs live. Defaults to the manifest's dir.")
@click.option("--public-key", "public_key_path", default=None,
              type=click.Path(exists=True, dir_okay=False))
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def manifest_verify(manifest_path, artifacts_dir, public_key_path, fmt):
    """Verify a supply-chain manifest against the compiled files."""
    from .supply_chain import verify_manifest
    from .licensing import load_public_key

    pub = None
    if public_key_path:
        pub = load_public_key(Path(public_key_path).read_text())

    result = verify_manifest(
        Path(manifest_path),
        artifacts_dir=Path(artifacts_dir) if artifacts_dir else None,
        public_key=pub,
    )

    if fmt == "json":
        click.echo(json.dumps({"ok": result.ok, "findings": result.findings}, indent=2))
    else:
        header = click.style(
            "VERIFIED" if result.ok else "INVALID",
            fg="green" if result.ok else "red", bold=True,
        )
        click.echo(f"\n  Manifest: {header}\n")
        for line in result.findings:
            click.echo(line)
        click.echo()
    if not result.ok:
        sys.exit(1)


# ---------------------------------------------------------------------------
# evidence-packet / evidence-verify — auditor-ready bundles
# ---------------------------------------------------------------------------

@main.command("evidence-packet")
@click.argument("audit_file", type=click.Path(exists=True, dir_okay=False))
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default="evidence.zip",
              type=click.Path(dir_okay=False))
@click.option("--standard", default="soc2",
              type=click.Choice(["general", "soc2", "hipaa", "pci-dss", "gdpr"]))
@click.option("--signing-key", "signing_key_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to an Ed25519 PEM private key. Sign the packet manifest.")
@click.option("--public-key", "public_key_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Path to the Ed25519 public key used to verify the audit chain.")
@click.option("--reviewer", default="",
              help="Human reviewer identifier to stamp into the manifest.")
def evidence_packet(audit_file, spec_file, output, standard,
                     signing_key_path, public_key_path, reviewer):
    """Build an auditor-ready evidence packet (Pro feature)."""
    from .governance.evidence import build_evidence_packet
    from .licensing import (
        Feature, get_entitlements, has_feature, load_private_key, load_public_key,
    )

    if not has_feature(Feature.EVIDENCE_PACKET):
        ent = get_entitlements()
        click.echo(
            f"Error: evidence-packet requires the Pro tier. "
            f"Current tier: {ent.tier.value}. "
            f"Upgrade: https://cortexprotocol.dev/upgrade",
            err=True,
        )
        sys.exit(1)

    priv = None
    if signing_key_path:
        priv = load_private_key(Path(signing_key_path).read_text())
    pub = None
    if public_key_path:
        pub = load_public_key(Path(public_key_path).read_text())

    result = build_evidence_packet(
        audit_path=Path(audit_file),
        spec_path=Path(spec_file),
        output_path=Path(output),
        standard=standard,
        private_key=priv,
        public_key=pub,
        reviewer=reviewer,
    )
    click.echo(f"  Built  {result.path}")
    click.echo(f"  id     {result.packet_id}")
    click.echo(f"  signed {'yes' if result.manifest_signed else 'no'}")
    if pub is not None:
        click.echo(f"  chain  {'verified' if result.chain_verified else 'FAILED'}")


@main.command("evidence-verify")
@click.argument("packet_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--public-key", "public_key_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Verify the manifest signature with this key. Defaults to the packet-embedded key.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def evidence_verify(packet_path, public_key_path, fmt):
    """Verify an evidence packet's file hashes and manifest signature."""
    from .governance.evidence import verify_evidence_packet
    from .licensing import load_public_key

    pub = None
    if public_key_path:
        pub = load_public_key(Path(public_key_path).read_text())

    result = verify_evidence_packet(Path(packet_path), public_key=pub)

    if fmt == "json":
        click.echo(json.dumps(
            {"ok": result.ok, "packet_id": result.packet_id, "findings": result.findings},
            indent=2,
        ))
    else:
        header = click.style("VERIFIED" if result.ok else "INVALID",
                              fg="green" if result.ok else "red", bold=True)
        click.echo(f"\n  Packet: {header}")
        click.echo(f"  id:     {result.packet_id}")
        click.echo()
        for line in result.findings:
            click.echo(line)
        click.echo()
    if not result.ok:
        sys.exit(1)


# ---------------------------------------------------------------------------
# push / pull — Cortex Cloud hosted registry
# ---------------------------------------------------------------------------

@main.command("push")
@click.argument("spec_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--version", "-v", required=True, help="Semver version to publish.")
@click.option("--workspace", default=None,
              help="Target workspace. Defaults to $CORTEX_CLOUD_WORKSPACE or the logged-in default.")
def push(spec_file: str, version: str, workspace: str | None):
    """Publish an agent spec to Cortex Cloud (Pro feature)."""
    from .cloud import CloudClient, CloudRegistry, CloudRegistryError, load_credentials
    from .licensing import Feature, get_entitlements, has_feature
    from .validator import validate_file

    if not has_feature(Feature.HOSTED_REGISTRY):
        ent = get_entitlements()
        click.echo(
            f"Error: `push` requires the Pro tier (feature: hosted_registry). "
            f"Current tier: {ent.tier.value}. "
            f"Upgrade: https://cortexprotocol.dev/upgrade",
            err=True,
        )
        sys.exit(1)

    spec, errors = validate_file(spec_file)
    if errors or spec is None:
        click.echo("Validation failed:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)

    creds = load_credentials()
    ws = workspace or (creds.workspace if creds else "") or _env("CORTEX_CLOUD_WORKSPACE", "")
    if not ws:
        click.echo("Error: no workspace. Pass --workspace or set CORTEX_CLOUD_WORKSPACE.", err=True)
        sys.exit(1)

    client = CloudClient.from_environment()
    registry = CloudRegistry(client, workspace=ws)
    try:
        url = registry.publish(spec, version)
    except CloudRegistryError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Published {spec.agent.name}@{version}")
    if url:
        click.echo(f"  {url}")


@main.command("pull")
@click.argument("name")
@click.option("--version", "-v", default=None, help="Specific version (defaults to latest).")
@click.option("--output", "-o", default=None, type=click.Path(dir_okay=False),
              help="Output YAML path. Defaults to <name>.yaml.")
@click.option("--workspace", default=None)
def pull(name: str, version: str | None, output: str | None, workspace: str | None):
    """Fetch an agent spec from Cortex Cloud."""
    from .cloud import CloudClient, CloudRegistry, load_credentials

    creds = load_credentials()
    ws = workspace or (creds.workspace if creds else "") or _env("CORTEX_CLOUD_WORKSPACE", "")
    if not ws:
        click.echo("Error: no workspace. Pass --workspace or set CORTEX_CLOUD_WORKSPACE.", err=True)
        sys.exit(1)

    client = CloudClient.from_environment()
    registry = CloudRegistry(client, workspace=ws)
    spec = registry.get(name, version) if version else registry.get_latest(name)
    if spec is None:
        label = f"{name}@{version}" if version else name
        click.echo(f"Error: not found: {label}", err=True)
        sys.exit(1)

    out_path = Path(output or f"{name}.yaml")
    out_path.write_text(spec.to_yaml())
    click.echo(f"  {out_path}")


def _env(name: str, default: str = "") -> str:
    import os
    return os.environ.get(name, default)


# ---------------------------------------------------------------------------
# login / logout / status — Cortex Cloud
# ---------------------------------------------------------------------------

@main.command("login")
@click.option("--url", default=None,
              help="Override the Cortex Cloud base URL (default: $CORTEX_CLOUD_URL).")
@click.option("--workspace", default=None,
              help="Workspace slug to bind this session to.")
def login(url: str | None, workspace: str | None):
    """Authenticate to Cortex Cloud via OAuth device flow (Pro feature)."""
    from .cloud.client import CloudAuthError, CloudClient, default_cloud_url

    client = CloudClient(base_url=url or default_cloud_url())
    try:
        creds = client.login_device_flow(workspace=workspace)
    except CloudAuthError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(f"  Logged in as {creds.email}")
    if creds.workspace:
        click.echo(f"  workspace: {creds.workspace}")


@main.command("logout")
def logout():
    """Forget stored Cortex Cloud credentials."""
    from .cloud.client import remove_credentials

    if remove_credentials():
        click.echo("  Logged out.")
    else:
        click.echo("  No stored credentials to remove.")


@main.command("status")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def status(fmt: str):
    """Show the current Turing status: tier, workspace, Cloud connection."""
    from .cloud.client import CloudClient, CloudHTTPError, load_credentials
    from .licensing import current_entitlements
    from .platform import credentials_path, license_path

    ent = current_entitlements()
    creds = load_credentials()
    client = CloudClient.from_environment()

    cloud_info: dict[str, Any] = {
        "url": client.base_url,
        "authenticated": client.is_authenticated,
        "email": creds.email if creds else "",
        "workspace": creds.workspace if creds else "",
        "whoami": None,
    }
    if client.is_authenticated:
        try:
            cloud_info["whoami"] = client.whoami()
        except CloudHTTPError as e:
            cloud_info["whoami"] = {"error": str(e), "status": e.status}

    payload = {
        "version": __version__,
        "tier": ent.tier.value,
        "features": sorted(f.value for f in ent.features),
        "license_path": str(license_path()),
        "credentials_path": str(credentials_path()),
        "cloud": cloud_info,
    }

    if fmt == "json":
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"  turing:      v{__version__}")
    click.echo(f"  tier:        {ent.tier.value}")
    if ent.features:
        click.echo(f"  features:    {len(ent.features)} granted")
    click.echo(f"  cloud:       {client.base_url}")
    click.echo(f"  auth:        {'yes' if client.is_authenticated else 'no'}")
    if creds:
        click.echo(f"  email:       {creds.email}")
        click.echo(f"  workspace:   {creds.workspace or '—'}")
    if isinstance(cloud_info["whoami"], dict) and "error" in cloud_info["whoami"]:
        click.echo(click.style(
            f"  cloud check: {cloud_info['whoami']['error']}",
            fg="yellow",
        ))


# ---------------------------------------------------------------------------
# audit-verify — verify a signed audit log chain
# ---------------------------------------------------------------------------

@main.command("audit-verify")
@click.argument("log_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--public-key", "pubkey_path", type=click.Path(exists=True, dir_okay=False),
              default=None,
              help="Path to the Ed25519 public key (PEM). Defaults to the bundled Turing key.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def audit_verify(log_file: str, pubkey_path: str | None, fmt: str):
    """Verify the signature chain on a Turing signed audit log."""
    from .governance.audit import AuditLog
    from .governance.signed_audit import verify_chain
    from .licensing.crypto import load_public_key, public_key_from_env
    from .licensing.pubkey import BUNDLED_PUBKEY_PEM

    if pubkey_path:
        pk = load_public_key(Path(pubkey_path).read_text())
    else:
        env_pk = public_key_from_env()
        pk = env_pk or load_public_key(BUNDLED_PUBKEY_PEM)

    log = AuditLog.from_file(Path(log_file))
    ok, findings = verify_chain(log.events(), pk)

    if fmt == "json":
        click.echo(json.dumps(
            {"ok": ok, "event_count": len(log.events()), "findings": findings},
            indent=2,
        ))
    else:
        header = click.style("VERIFIED" if ok else "TAMPERED", fg="green" if ok else "red", bold=True)
        click.echo(f"\n  Chain: {header}")
        click.echo(f"  events: {len(log.events())}")
        click.echo()
        for line in findings:
            click.echo(line)
        click.echo()
    if not ok:
        sys.exit(1)


# ---------------------------------------------------------------------------
# activate / license — local licensing operations
# ---------------------------------------------------------------------------

@main.command("activate")
@click.argument("license_source", type=click.Path(dir_okay=False))
def activate(license_source: str):
    """Install a Turing license file.

    LICENSE_SOURCE is either a path to a .json license or `-` to read
    the file body from stdin (useful for piping from an email).
    """
    from .licensing import LicenseError, install_license, verify_license, load_license_file
    from .platform import license_path

    if license_source == "-":
        content = sys.stdin.read()
    else:
        src = Path(license_source)
        if not src.exists():
            click.echo(f"Error: license file not found: {src}", err=True)
            sys.exit(1)
        content = src.read_text()

    try:
        written = install_license(content)
    except LicenseError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    lic = load_license_file(written)
    try:
        ent = verify_license(lic)
    except LicenseError as e:
        click.echo(f"Warning: license installed at {written}, but verification failed: {e}", err=True)
        sys.exit(1)

    click.echo(f"  Installed license → {written}")
    click.echo(f"  tier:        {ent.tier.value}")
    click.echo(f"  issued_to:   {ent.issued_to}")
    click.echo(f"  workspace:   {ent.workspace_id or '—'}")
    click.echo(f"  expires:     {ent.expires_at or 'never'}")
    if ent.in_grace:
        click.echo(click.style("  [!] license is in grace period. Renew soon.", fg="yellow"))


@main.command("license")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def license_cmd(fmt: str):
    """Show the currently-active Turing license."""
    from .licensing import current_entitlements, load_license_file
    from .platform import license_path

    path = license_path()
    lic = None
    try:
        lic = load_license_file(path)
    except Exception:
        pass
    ent = current_entitlements()

    if fmt == "json":
        out = {
            "tier": ent.tier.value,
            "issued_to": ent.issued_to,
            "workspace_id": ent.workspace_id,
            "expires_at": ent.expires_at,
            "in_grace": ent.in_grace,
            "features": sorted(f.value for f in ent.features),
            "license_path": str(path),
            "license_present": lic is not None,
        }
        click.echo(json.dumps(out, indent=2))
        return

    click.echo(f"  tier:        {ent.tier.value}")
    click.echo(f"  issued_to:   {ent.issued_to or '—'}")
    click.echo(f"  workspace:   {ent.workspace_id or '—'}")
    click.echo(f"  expires:     {ent.expires_at or 'never'}")
    click.echo(f"  grace:       {'yes' if ent.in_grace else 'no'}")
    if ent.features:
        click.echo(f"  features:    {', '.join(sorted(f.value for f in ent.features))}")
    else:
        click.echo("  features:    (Standard tier — upgrade at https://cortexprotocol.dev/upgrade)")
    click.echo(f"  license file: {path}{' (not present)' if lic is None else ''}")


@main.command("deactivate")
def deactivate():
    """Remove the installed license and revert to Standard tier."""
    from .licensing import remove_license

    if remove_license():
        click.echo("  License removed. Tier: standard.")
    else:
        click.echo("  No license file to remove.")


# ---------------------------------------------------------------------------
# mcp — group for MCP server management
# ---------------------------------------------------------------------------

@main.group("mcp")
def mcp_group():
    """Run, install, and inspect Model Context Protocol servers.

    The first-party Turing MCP server exposes governance tools to any MCP
    client (Cursor, Claude Desktop, VS Code, Windsurf). External MCP
    servers are wired via npx and cached under ~/.cortex-protocol/mcp-cache.
    """
    pass


@mcp_group.command("serve")
@click.option("--transport", default="stdio",
              type=click.Choice(["stdio", "streamable-http", "sse"]),
              help="Transport protocol. stdio for desktop clients; streamable-http for remote.")
@click.option("--host", default="127.0.0.1", help="Bind host for HTTP transports.")
@click.option("--port", default=8077, type=int, help="Bind port for HTTP transports.")
def mcp_serve(transport, host, port):
    """Run the Turing MCP server. Blocks until stopped."""
    try:
        from .mcp_server import serve
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    try:
        serve(transport=transport, host=host, port=port)
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@mcp_group.command("list")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]))
def mcp_list(fmt):
    """List bundled + user-registered MCP servers."""
    from .network.mcp import MCPServerRegistry
    from .mcp_server.config import load_config

    reg = MCPServerRegistry()
    builtin = [
        {
            "name": s.name, "package": s.package,
            "description": s.description, "transport": s.transport,
            "tools": list(s.tools), "env_vars": list(s.env_vars),
            "source": "builtin",
        }
        for s in reg.list_servers()
    ]
    user = [
        {"name": name, "command": e.command, "args": e.args,
         "transport": e.transport, "source": "user"}
        for name, e in load_config().items()
    ]

    if fmt == "json":
        click.echo(json.dumps({"builtin": builtin, "user": user}, indent=2))
        return

    click.echo("\n  Built-in MCP servers:")
    for s in builtin:
        click.echo(f"  - {s['name']:<26} {s['description']}")
    if user:
        click.echo("\n  User-registered MCP servers:")
        for s in user:
            args = " ".join(s["args"])
            click.echo(f"  - {s['name']:<26} {s['command']} {args}")
    click.echo()


@mcp_group.command("install")
@click.argument("server_name", required=False)
@click.option("--all", "install_all", is_flag=True, help="Warm cache for every builtin server.")
def mcp_install(server_name, install_all):
    """Warm the npx cache for a bundled external MCP server."""
    from .network.mcp import MCPServerRegistry
    from .platform import require_node_and_npx, mcp_cache_dir, ensure_dir

    if not (server_name or install_all):
        click.echo("Usage: cortex-protocol mcp install <server> | --all", err=True)
        sys.exit(1)

    try:
        _, npx = require_node_and_npx()
    except RuntimeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    reg = MCPServerRegistry()
    targets = reg.list_servers() if install_all else [reg.get(server_name)]
    if not install_all and (targets[0] is None):
        click.echo(f"Unknown MCP server '{server_name}'. "
                   f"Run `cortex-protocol mcp list` to see options.", err=True)
        sys.exit(1)

    cache = ensure_dir(mcp_cache_dir())
    import subprocess

    for s in targets:
        click.echo(f"  warming {s.name} ({s.package})...")
        # `--version` on the package binary is cheap and forces npx to
        # resolve + cache the package without launching the server.
        result = subprocess.run(
            [npx, "-y", "--no-update-notifier", s.package, "--version"],
            cwd=str(cache),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            # Many MCP servers don't support --version; falling through is fine,
            # the side effect we care about (download to cache) still happened.
            msg = (result.stderr or result.stdout or "").strip().splitlines()
            last = msg[-1] if msg else ""
            click.echo(f"    cached (pkg did not respond to --version: {last[:80]})")
        else:
            click.echo(f"    ok")
    click.echo(f"\n  Cache: {cache}")


@mcp_group.command(
    "add",
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False},
)
@click.option("--env", "-e", multiple=True, metavar="KEY=VALUE",
              help="Environment variable for the server (repeatable).")
@click.option("--overwrite", is_flag=True, help="Replace an existing entry with this name.")
@click.argument("name")
@click.argument("command")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def mcp_add(name, command, args, env, overwrite):
    """Register a custom MCP server in ~/.cortex-protocol/mcp.json."""
    from .mcp_server.config import add_server, McpServerEntry

    env_map = {}
    for kv in env:
        if "=" not in kv:
            click.echo(f"Invalid --env '{kv}'. Use KEY=VALUE.", err=True)
            sys.exit(1)
        k, v = kv.split("=", 1)
        env_map[k] = v

    entry = McpServerEntry(command=command, args=list(args), env=env_map)
    try:
        path = add_server(name, entry, overwrite=overwrite)
    except KeyError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    click.echo(f"  Registered '{name}' → {path}")


@mcp_group.command("connect")
@click.option("--client",
              type=click.Choice(["cursor", "claude-desktop", "vscode", "windsurf", "all", "auto"]),
              default="auto",
              help="Which MCP client to install Turing into.")
@click.option("--dry-run", is_flag=True, help="Show what would change without writing.")
def mcp_connect(client, dry_run):
    """Wire the Turing MCP server into one or more MCP clients' configs."""
    from .mcp_server.install import install_into_clients, all_known_clients
    from .platform import detect_installed_clients

    if client == "auto":
        targets = detect_installed_clients() or all_known_clients()
    elif client == "all":
        targets = all_known_clients()
    else:
        targets = [client]

    results = install_into_clients(targets, dry_run=dry_run)
    if not results:
        click.echo("No MCP clients matched.", err=True)
        sys.exit(1)

    for r in results:
        tag = "would-write" if dry_run else r.action
        click.echo(f"  [{tag}] {r.client:<16} {r.path}")
    if not dry_run:
        click.echo("\n  Restart your MCP client to pick up the new server.")


@mcp_group.command("doctor")
def mcp_doctor():
    """Check that Turing's MCP setup is healthy."""
    from .platform import find_executable, mcp_cache_dir, detect_installed_clients
    from .mcp_server.config import load_config

    problems: list[str] = []

    node = find_executable("node")
    npx = find_executable("npx")
    if node and npx:
        click.echo(f"  [ok]  node: {node}")
        click.echo(f"  [ok]  npx:  {npx}")
    else:
        problems.append("Node.js / npx not on PATH")
        click.echo("  [!!]  node/npx not on PATH — install Node.js (https://nodejs.org)")

    try:
        import mcp  # noqa: F401
        click.echo("  [ok]  mcp SDK installed")
    except ImportError:
        problems.append("mcp SDK not installed")
        click.echo("  [!!]  mcp SDK missing — run: pip install 'cortex-protocol[mcp]'")

    cache = mcp_cache_dir()
    if cache.exists():
        click.echo(f"  [ok]  cache: {cache}")
    else:
        click.echo(f"  [..]  cache: {cache} (empty, populated on first `mcp install`)")

    clients = detect_installed_clients()
    if clients:
        click.echo(f"  [ok]  detected MCP clients: {', '.join(clients)}")
    else:
        click.echo("  [..]  no MCP clients detected (run `cortex-protocol mcp connect` after installing one)")

    user = load_config()
    if user:
        click.echo(f"  [ok]  {len(user)} user-registered MCP server(s)")

    if problems:
        click.echo(f"\n  {len(problems)} issue(s) need attention.")
        sys.exit(1)
    click.echo("\n  All checks passed.")


# Top-level `connect` alias — wires Turing into MCP clients in one word.
@main.command("connect")
@click.option("--client",
              type=click.Choice(["cursor", "claude-desktop", "vscode", "windsurf", "all", "auto"]),
              default="auto")
@click.option("--dry-run", is_flag=True)
@click.pass_context
def connect_alias(ctx, client, dry_run):
    """Alias for `cortex-protocol mcp connect`."""
    ctx.invoke(mcp_connect, client=client, dry_run=dry_run)


if __name__ == "__main__":
    main()
