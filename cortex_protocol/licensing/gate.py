"""Tier / feature gates for CLI commands and MCP tools.

Two decorators:

    @requires_tier(Tier.PRO)        # blocks if current license is below Pro
    @requires_feature(Feature.XYZ)  # blocks if the specific feature is not granted

Both default to *hard-fail* (Click-friendly, non-zero exit). For runtime
code paths that should degrade silently rather than raise, call
`has_tier` / `has_feature` directly and branch.

The `_entitlements_provider` indirection exists so tests can inject a
fake entitlement set without monkey-patching license file loading.
"""

from __future__ import annotations

from dataclasses import replace
from functools import wraps
from typing import Callable, Optional

from .entitlements import Entitlements, Feature, Tier
from .license import current_entitlements


_ENTITLEMENTS: Optional[Entitlements] = None


def get_entitlements() -> Entitlements:
    """Return the current process's entitlements, resolving lazily."""
    global _ENTITLEMENTS
    if _ENTITLEMENTS is None:
        _ENTITLEMENTS = current_entitlements()
    return _ENTITLEMENTS


def set_entitlements(ent: Optional[Entitlements]) -> None:
    """Override the resolved entitlements. Pass None to force a re-resolve."""
    global _ENTITLEMENTS
    _ENTITLEMENTS = ent


def has_tier(tier: Tier | str) -> bool:
    return get_entitlements().at_least(tier)


def has_feature(feature: Feature | str) -> bool:
    return get_entitlements().has(feature)


class EntitlementRequired(Exception):
    """Raised when a gated operation is attempted without the right tier/feature."""

    def __init__(self, message: str, required: str):
        super().__init__(message)
        self.required = required


def requires_tier(tier: Tier | str) -> Callable:
    """Decorator: ensure the current license is at least `tier`."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_tier(tier):
                label = tier.value if isinstance(tier, Tier) else tier
                ent = get_entitlements()
                msg = (
                    f"This command requires the {label} tier. "
                    f"Current tier: {ent.tier.value}. "
                    f"Upgrade: https://cortexprotocol.dev/upgrade"
                )
                _emit_gate_error(msg)
                raise EntitlementRequired(msg, required=f"tier:{label}")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def requires_feature(feature: Feature | str) -> Callable:
    """Decorator: ensure a specific feature is granted."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_feature(feature):
                label = feature.value if isinstance(feature, Feature) else feature
                ent = get_entitlements()
                msg = (
                    f"This command requires the '{label}' feature. "
                    f"Current tier: {ent.tier.value}. "
                    f"Upgrade: https://cortexprotocol.dev/upgrade"
                )
                _emit_gate_error(msg)
                raise EntitlementRequired(msg, required=f"feature:{label}")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def _emit_gate_error(msg: str) -> None:
    """Best-effort CLI-friendly error output. Uses click.echo if available."""
    try:
        import click
        click.echo(f"Error: {msg}", err=True)
    except Exception:  # pragma: no cover
        import sys
        print(f"Error: {msg}", file=sys.stderr)


def downgrade_to_standard_for_tests() -> Entitlements:
    """Test helper: pin entitlements to Standard until reset."""
    ent = Entitlements(tier=Tier.STANDARD)
    set_entitlements(ent)
    return ent


def grant_for_tests(tier: Tier = Tier.ENTERPRISE,
                    extra_features: Optional[set[Feature]] = None) -> Entitlements:
    """Test helper: pin entitlements to a given tier (default Enterprise)."""
    from .entitlements import TIERS
    ent = Entitlements(
        tier=tier,
        extra_features=frozenset(extra_features or set()),
        issued_to="test@example.com",
    )
    set_entitlements(ent)
    return ent
