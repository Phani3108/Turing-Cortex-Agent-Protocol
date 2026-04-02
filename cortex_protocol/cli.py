"""Cortex Protocol CLI — init, validate, compile, list-targets."""

from __future__ import annotations

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
    Always cite your sources when possible.

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
  temperature: 0.7
'''
    path = Path(output)
    if path.exists():
        click.echo(f"Error: {output} already exists. Use a different name.", err=True)
        sys.exit(1)

    path.write_text(example)
    click.echo(f"Created {output}")
    click.echo(f"Next: cortex-protocol validate {output}")


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


@main.command("list-targets")
def list_targets():
    """List available compilation targets."""
    click.echo("Available targets:\n")
    for name, cls in TARGET_REGISTRY.items():
        target = cls() if name != "system-prompt" else cls()
        click.echo(f"  {name:<16} {target.description}")
    click.echo(f"\n  {'all':<16} Compile to all targets at once")


if __name__ == "__main__":
    main()
