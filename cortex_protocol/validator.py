"""Validate agent specs against the Cortex Protocol v0.1 schema."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import AgentSpec


def validate_file(path: str | Path) -> tuple[AgentSpec | None, list[str]]:
    """Validate a YAML file. Returns (spec, errors)."""
    path = Path(path)
    errors: list[str] = []

    if not path.exists():
        return None, [f"File not found: {path}"]

    if path.suffix not in (".yaml", ".yml"):
        errors.append(f"Expected .yaml or .yml file, got: {path.suffix}")

    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return None, [f"Invalid YAML: {e}"]

    if not isinstance(data, dict):
        return None, ["Spec must be a YAML mapping (dict), not a scalar or list"]

    return validate_data(data)


def validate_data(data: dict) -> tuple[AgentSpec | None, list[str]]:
    """Validate a parsed dict. Returns (spec, errors)."""
    errors: list[str] = []

    try:
        spec = AgentSpec.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        return None, errors

    # Additional semantic checks beyond Pydantic validation
    tool_names = {t.name for t in spec.tools}

    for tool_name in spec.policies.require_approval:
        if tool_name not in tool_names:
            errors.append(
                f"policies.require_approval references unknown tool: '{tool_name}'"
            )

    if spec.policies.max_turns is not None and spec.policies.max_turns < 1:
        errors.append("policies.max_turns must be >= 1")

    if spec.model.temperature < 0.0 or spec.model.temperature > 2.0:
        errors.append("model.temperature must be between 0.0 and 2.0")

    if errors:
        return None, errors

    return spec, []
