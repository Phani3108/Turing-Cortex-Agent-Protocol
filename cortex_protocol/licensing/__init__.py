"""Turing licensing — Ed25519 license verification, tier/feature gates.

Requires the `[enterprise]` extra (pulls in `cryptography`). Import lazily
from code that might run with the extra absent — or, better, gate the
calling command with `@requires_tier('pro')` which needs the extra anyway.
"""

from __future__ import annotations

from .crypto import (
    canonical_json,
    generate_keypair,
    load_private_key,
    load_public_key,
    private_key_to_pem,
    public_key_to_pem,
    sha256_hex,
    sign_payload,
    verify_signature,
)
from .entitlements import (
    STANDARD,
    TIERS,
    Entitlements,
    Feature,
    Tier,
    parse_features,
    parse_tier,
)
from .gate import (
    EntitlementRequired,
    downgrade_to_standard_for_tests,
    get_entitlements,
    grant_for_tests,
    has_feature,
    has_tier,
    requires_feature,
    requires_tier,
    set_entitlements,
)
from .license import (
    GRACE_DAYS_DEFAULT,
    LicenseError,
    LicenseFile,
    current_entitlements,
    install_license,
    load_license_file,
    remove_license,
    verify_license,
)

__all__ = [
    "STANDARD", "TIERS",
    "Entitlements", "Feature", "Tier",
    "parse_features", "parse_tier",
    "EntitlementRequired", "requires_tier", "requires_feature",
    "has_tier", "has_feature", "get_entitlements", "set_entitlements",
    "grant_for_tests", "downgrade_to_standard_for_tests",
    "GRACE_DAYS_DEFAULT", "LicenseError", "LicenseFile",
    "current_entitlements", "install_license", "load_license_file",
    "remove_license", "verify_license",
    "canonical_json", "sign_payload", "verify_signature",
    "sha256_hex",
    "generate_keypair", "load_public_key", "load_private_key",
    "public_key_to_pem", "private_key_to_pem",
]
