"""Version resolution and search utilities for the registry.

Handles semver range matching (^, ~, exact) and provides
top-level search functions that work with the default registry.
"""

from __future__ import annotations

import re
from typing import Optional

from .local import LocalRegistry, AgentMeta, _parse_semver
from ..models import AgentSpec, merge_specs


# ---------------------------------------------------------------------------
# Semver range matching
# ---------------------------------------------------------------------------

def _matches_caret(version: str, range_version: str) -> bool:
    """Caret (^) range: compatible with version.
    ^1.2.3 matches >=1.2.3, <2.0.0
    ^0.2.3 matches >=0.2.3, <0.3.0
    """
    v = _parse_semver(version)
    r = _parse_semver(range_version)

    if v < r:
        return False

    if r[0] > 0:
        return v[0] == r[0]
    elif r[1] > 0:
        return v[0] == 0 and v[1] == r[1]
    else:
        return v == r


def _matches_tilde(version: str, range_version: str) -> bool:
    """Tilde (~) range: patch-level changes.
    ~1.2.3 matches >=1.2.3, <1.3.0
    """
    v = _parse_semver(version)
    r = _parse_semver(range_version)
    if v < r:
        return False
    return v[0] == r[0] and v[1] == r[1]


def version_matches(version: str, range_spec: str) -> bool:
    """Check if a version matches a range specification.

    Supported formats:
        "1.2.3"   - exact match
        "^1.2.3"  - caret range (compatible)
        "~1.2.3"  - tilde range (patch-level)
        ">=1.2.3" - greater or equal
    """
    range_spec = range_spec.strip()

    if range_spec.startswith("^"):
        return _matches_caret(version, range_spec[1:])
    elif range_spec.startswith("~"):
        return _matches_tilde(version, range_spec[1:])
    elif range_spec.startswith(">="):
        return _parse_semver(version) >= _parse_semver(range_spec[2:])
    else:
        return version == range_spec


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_version(
    registry: LocalRegistry,
    name: str,
    version_spec: str = "latest",
) -> Optional[str]:
    """Resolve a version spec to a concrete version string.

    Args:
        registry: The registry to search
        name: Agent name
        version_spec: "latest", exact version, or range (^, ~, >=)

    Returns:
        Concrete version string, or None if no match found.
    """
    if version_spec == "latest":
        meta = registry.get_meta(name)
        return meta.latest if meta else None

    versions = registry.list_versions(name)
    if not versions:
        return None

    # Exact match first
    if version_spec in versions:
        return version_spec

    # Range match -- return highest matching version
    matching = [v for v in versions if version_matches(v, version_spec)]
    if not matching:
        return None

    matching.sort(key=_parse_semver, reverse=True)
    return matching[0]


# ---------------------------------------------------------------------------
# Extends resolution
# ---------------------------------------------------------------------------

def _parse_extends_ref(extends_str: str) -> tuple[str, str]:
    """Parse '@org/name@version' or 'name@version' or 'name'.

    Returns (name, version_spec) where version_spec may be 'latest'.
    """
    s = extends_str.strip()
    # Strip leading @org/ prefix
    if s.startswith("@"):
        parts = s[1:].split("/", 1)
        if len(parts) == 2:
            s = parts[1]
        else:
            s = parts[0]
    # Now split name@version
    if "@" in s:
        name, version_spec = s.rsplit("@", 1)
    else:
        name, version_spec = s, "latest"
    return name, version_spec


def resolve_extends(spec: AgentSpec, registry: LocalRegistry) -> AgentSpec:
    """Resolve spec.extends from registry and merge into spec.

    Returns merged spec. If base not found, returns spec unchanged.
    """
    if not spec.extends:
        return spec

    name, version_spec = _parse_extends_ref(spec.extends)
    concrete = resolve_version(registry, name, version_spec)
    if concrete is None:
        return spec

    base = registry.get(name, concrete)
    if base is None:
        return spec

    return merge_specs(base, spec)


# ---------------------------------------------------------------------------
# Top-level search (convenience)
# ---------------------------------------------------------------------------

def search_specs(
    tags: Optional[list[str]] = None,
    compliance: Optional[list[str]] = None,
    owner: Optional[str] = None,
    name_contains: Optional[str] = None,
    registry: Optional[LocalRegistry] = None,
) -> list[dict]:
    """Search the registry and return results as dicts.

    Uses the default registry if none provided.
    Returns list of {name, version, description, owner, tags, compliance}.
    """
    reg = registry or LocalRegistry()
    results = reg.search(
        tags=tags,
        compliance=compliance,
        owner=owner,
        name_contains=name_contains,
    )
    return [
        {
            "name": meta.name,
            "version": meta.latest,
            "description": spec.agent.description,
            "owner": spec.metadata.owner if spec.metadata else "",
            "tags": spec.metadata.tags if spec.metadata else [],
            "compliance": spec.metadata.compliance if spec.metadata else [],
        }
        for meta, spec in results
    ]
