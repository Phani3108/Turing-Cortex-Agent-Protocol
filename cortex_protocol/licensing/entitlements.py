"""Tier + feature entitlements for Turing.

Three tiers: Standard (free), Pro ($20/seat/mo), Enterprise (custom).
Each tier has a canonical set of feature flags; a license file can grant
individual features a la carte (e.g. a trial that unlocks one Pro feature
for 30 days).

The `Entitlements` object is the single source of truth the rest of the
codebase consults — the licensing module resolves a license file into
one of these, caches it for the process lifetime, and `gate.py` then
decorates CLI commands / MCP tools against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# Feature flags used throughout Turing. New features gated by tier should
# add their flag here and reference it in `gate.py` — the set here is the
# authoritative catalog of paywalled capabilities.
class Feature(str, Enum):
    # Pro
    HOSTED_REGISTRY   = "hosted_registry"
    CLOUD_AUDIT       = "cloud_audit"
    SLACK_APPROVALS   = "slack_approvals"
    PAGERDUTY_APPROVALS = "pagerduty_approvals"
    TEAMS_APPROVALS   = "teams_approvals"
    GOOGLE_SSO        = "google_sso"
    OTEL_EXPORT       = "otel_export"
    SIGNED_AUDIT      = "signed_audit"
    COST_DASHBOARD    = "cost_dashboard"
    EVIDENCE_PACKET   = "evidence_packet"
    # Enterprise
    SAML_SSO          = "saml_sso"
    ON_PREM           = "on_prem"
    RFC3161_NOTARIZE  = "rfc3161_notarize"
    CUSTOM_COMPLIANCE = "custom_compliance"
    POLICY_MARKETPLACE_PRIVATE = "policy_marketplace_private"
    K8S_OPERATOR      = "k8s_operator"
    SLA               = "sla"


class Tier(str, Enum):
    STANDARD   = "standard"
    PRO        = "pro"
    ENTERPRISE = "enterprise"


_PRO_FEATURES: frozenset[Feature] = frozenset({
    Feature.HOSTED_REGISTRY,
    Feature.CLOUD_AUDIT,
    Feature.SLACK_APPROVALS,
    Feature.PAGERDUTY_APPROVALS,
    Feature.TEAMS_APPROVALS,
    Feature.GOOGLE_SSO,
    Feature.OTEL_EXPORT,
    Feature.SIGNED_AUDIT,
    Feature.COST_DASHBOARD,
    Feature.EVIDENCE_PACKET,
})

_ENTERPRISE_FEATURES: frozenset[Feature] = _PRO_FEATURES | frozenset({
    Feature.SAML_SSO,
    Feature.ON_PREM,
    Feature.RFC3161_NOTARIZE,
    Feature.CUSTOM_COMPLIANCE,
    Feature.POLICY_MARKETPLACE_PRIVATE,
    Feature.K8S_OPERATOR,
    Feature.SLA,
})


TIERS: dict[Tier, frozenset[Feature]] = {
    Tier.STANDARD:   frozenset(),
    Tier.PRO:        _PRO_FEATURES,
    Tier.ENTERPRISE: _ENTERPRISE_FEATURES,
}


@dataclass(frozen=True)
class Entitlements:
    """Resolved license state for the current process.

    `tier` drives the default feature set; `extra_features` are a la carte
    grants layered on top (for trials, promo grants, or partial unlocks).
    `in_grace` is True if the license has expired but we're still within
    the 14-day grace window.
    """

    tier: Tier = Tier.STANDARD
    extra_features: frozenset[Feature] = field(default_factory=frozenset)
    issued_to: str = ""
    workspace_id: str = ""
    expires_at: str = ""
    in_grace: bool = False

    @property
    def features(self) -> frozenset[Feature]:
        return TIERS.get(self.tier, frozenset()) | self.extra_features

    def has(self, feature: Feature | str) -> bool:
        if isinstance(feature, str):
            try:
                feature = Feature(feature)
            except ValueError:
                return False
        return feature in self.features

    def at_least(self, tier: Tier | str) -> bool:
        if isinstance(tier, str):
            tier = Tier(tier)
        order = {Tier.STANDARD: 0, Tier.PRO: 1, Tier.ENTERPRISE: 2}
        return order[self.tier] >= order[tier]


def parse_features(values: list[str]) -> frozenset[Feature]:
    """Coerce a list of feature strings into the canonical enum set.

    Unknown values are silently dropped — a license from a newer issuer
    may reference features this wheel doesn't know about yet; forward
    compatibility beats hard failure.
    """
    out = set()
    for v in values or []:
        try:
            out.add(Feature(v))
        except ValueError:
            continue
    return frozenset(out)


def parse_tier(value: str) -> Tier:
    try:
        return Tier(value.lower())
    except (AttributeError, ValueError):
        return Tier.STANDARD


# Default entitlement when no license file is present. Created here so
# callers can import a single sentinel rather than constructing ad-hoc.
STANDARD = Entitlements(tier=Tier.STANDARD)
