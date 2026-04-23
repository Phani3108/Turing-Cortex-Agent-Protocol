"""Tests for the Turing licensing module.

Tests generate a throwaway Ed25519 keypair at runtime, sign a sample
license with the private half, and inject the public half via the
CORTEX_LICENSE_PUBKEY env var so verification reaches the same key.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from cortex_protocol.licensing import (
    EntitlementRequired,
    Entitlements,
    Feature,
    LicenseError,
    LicenseFile,
    Tier,
    canonical_json,
    current_entitlements,
    downgrade_to_standard_for_tests,
    generate_keypair,
    grant_for_tests,
    has_feature,
    has_tier,
    install_license,
    load_license_file,
    parse_features,
    parse_tier,
    public_key_to_pem,
    remove_license,
    requires_feature,
    requires_tier,
    set_entitlements,
    sign_payload,
    verify_license,
    verify_signature,
)


@pytest.fixture
def keypair():
    return generate_keypair()


@pytest.fixture(autouse=True)
def reset_entitlements():
    # Every test starts with freshly-resolved entitlements.
    set_entitlements(None)
    yield
    set_entitlements(None)


def _mint_license(
    priv,
    tier: str = "pro",
    features=("hosted_registry", "signed_audit"),
    expires_at: str | None = None,
    issued_at: str | None = None,
    workspace_id: str = "ws_test",
    issued_to: str = "tester@example.com",
    key: str = "cx-test-001",
) -> str:
    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "key": key,
        "tier": tier,
        "issued_to": issued_to,
        "workspace_id": workspace_id,
        "features": list(features),
        "issued_at": issued_at or now.isoformat(),
        "expires_at": expires_at or (now + _dt.timedelta(days=365)).isoformat(),
    }
    sig = sign_payload(priv, payload)
    payload["signature"] = sig
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# canonical JSON + crypto round-trip
# ---------------------------------------------------------------------------

class TestCrypto:
    def test_canonical_json_is_stable(self):
        a = canonical_json({"b": 2, "a": 1})
        b = canonical_json({"a": 1, "b": 2})
        assert a == b

    def test_sign_and_verify(self, keypair):
        priv, pub = keypair
        payload = {"hello": "world", "n": 42}
        sig = sign_payload(priv, payload)
        assert sig.startswith("ed25519:")
        assert verify_signature(pub, payload, sig)

    def test_verify_rejects_tampered_payload(self, keypair):
        priv, pub = keypair
        sig = sign_payload(priv, {"v": 1})
        assert not verify_signature(pub, {"v": 2}, sig)

    def test_verify_rejects_bad_prefix(self, keypair):
        _, pub = keypair
        assert not verify_signature(pub, {"v": 1}, "rsa:xxx")

    def test_verify_rejects_garbage_signature(self, keypair):
        _, pub = keypair
        assert not verify_signature(pub, {"v": 1}, "ed25519:not-base64!!!")


# ---------------------------------------------------------------------------
# license file loading
# ---------------------------------------------------------------------------

class TestLicenseFile:
    def test_missing_file_returns_none(self, tmp_path):
        assert load_license_file(tmp_path / "nope.json") is None

    def test_malformed_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not: json")
        with pytest.raises(LicenseError):
            load_license_file(p)

    def test_missing_required_field_raises(self, tmp_path):
        p = tmp_path / "lic.json"
        p.write_text(json.dumps({"tier": "pro", "signature": "ed25519:xxx"}))
        with pytest.raises(LicenseError):
            load_license_file(p)

    def test_round_trip(self, keypair, tmp_path):
        priv, pub = keypair
        monkey_env(pub)
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv))
        lic = load_license_file(p)
        assert lic is not None
        assert lic.tier == "pro"
        assert lic.issued_to == "tester@example.com"
        assert lic.signature.startswith("ed25519:")


def monkey_env(pubkey):
    """Install a public key into the env so verify_license picks it up."""
    import os
    os.environ["CORTEX_LICENSE_PUBKEY"] = public_key_to_pem(pubkey)


@pytest.fixture
def pubkey_env(keypair, monkeypatch):
    _, pub = keypair
    monkeypatch.setenv("CORTEX_LICENSE_PUBKEY", public_key_to_pem(pub))
    return pub


# ---------------------------------------------------------------------------
# verify_license (signature, expiry, grace)
# ---------------------------------------------------------------------------

class TestVerifyLicense:
    def test_happy_path(self, keypair, pubkey_env, tmp_path):
        priv, _ = keypair
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv, tier="enterprise"))
        ent = verify_license(load_license_file(p))
        assert ent.tier == Tier.ENTERPRISE
        assert not ent.in_grace

    def test_bad_signature_raises(self, keypair, pubkey_env, tmp_path):
        priv, _ = keypair
        text = _mint_license(priv)
        # Tamper with a field AFTER signing.
        doc = json.loads(text)
        doc["tier"] = "enterprise"
        p = tmp_path / "lic.json"
        p.write_text(json.dumps(doc))
        with pytest.raises(LicenseError, match="signature"):
            verify_license(load_license_file(p))

    def test_expired_but_in_grace(self, keypair, pubkey_env, tmp_path):
        priv, _ = keypair
        past = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=5)).isoformat()
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv, expires_at=past))
        ent = verify_license(load_license_file(p))
        assert ent.in_grace is True

    def test_expired_past_grace_raises(self, keypair, pubkey_env, tmp_path):
        priv, _ = keypair
        long_ago = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=100)).isoformat()
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv, expires_at=long_ago))
        with pytest.raises(LicenseError, match="grace"):
            verify_license(load_license_file(p))

    def test_issued_in_future_raises(self, keypair, pubkey_env, tmp_path):
        priv, _ = keypair
        future = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=7)).isoformat()
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv, issued_at=future))
        with pytest.raises(LicenseError, match="future"):
            verify_license(load_license_file(p))

    def test_grace_window_override_via_env(self, keypair, pubkey_env, tmp_path, monkeypatch):
        priv, _ = keypair
        # 2 days past expiry with a 1-day grace => should fail.
        two_days_ago = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=2)).isoformat()
        p = tmp_path / "lic.json"
        p.write_text(_mint_license(priv, expires_at=two_days_ago))
        monkeypatch.setenv("CORTEX_LICENSE_GRACE", "1")
        with pytest.raises(LicenseError):
            verify_license(load_license_file(p))


# ---------------------------------------------------------------------------
# current_entitlements fallback behavior
# ---------------------------------------------------------------------------

class TestCurrentEntitlements:
    def test_no_file_is_standard(self, tmp_path):
        ent = current_entitlements(path=tmp_path / "nope.json")
        assert ent.tier == Tier.STANDARD

    def test_bad_file_silently_standard(self, tmp_path):
        p = tmp_path / "lic.json"
        p.write_text("junk{")
        ent = current_entitlements(path=p)
        assert ent.tier == Tier.STANDARD

    def test_bad_file_strict_raises(self, tmp_path):
        p = tmp_path / "lic.json"
        p.write_text("junk{")
        with pytest.raises(LicenseError):
            current_entitlements(path=p, strict=True)


# ---------------------------------------------------------------------------
# entitlement semantics
# ---------------------------------------------------------------------------

class TestEntitlements:
    def test_standard_has_nothing(self):
        e = Entitlements(tier=Tier.STANDARD)
        assert not e.has(Feature.HOSTED_REGISTRY)
        assert not e.at_least(Tier.PRO)

    def test_pro_includes_pro_features(self):
        e = Entitlements(tier=Tier.PRO)
        assert e.has(Feature.HOSTED_REGISTRY)
        assert e.has(Feature.SIGNED_AUDIT)
        assert not e.has(Feature.SAML_SSO)  # enterprise-only
        assert e.at_least(Tier.PRO)
        assert not e.at_least(Tier.ENTERPRISE)

    def test_enterprise_includes_everything(self):
        e = Entitlements(tier=Tier.ENTERPRISE)
        assert e.has(Feature.SAML_SSO)
        assert e.has(Feature.HOSTED_REGISTRY)
        assert e.at_least(Tier.ENTERPRISE)

    def test_extra_features_layer_over_tier(self):
        e = Entitlements(tier=Tier.STANDARD,
                         extra_features=frozenset({Feature.SIGNED_AUDIT}))
        assert e.has(Feature.SIGNED_AUDIT)
        assert not e.has(Feature.HOSTED_REGISTRY)

    def test_parse_features_drops_unknown(self):
        out = parse_features(["hosted_registry", "non_existent_feature"])
        assert Feature.HOSTED_REGISTRY in out
        assert len(out) == 1

    def test_parse_tier_unknown_defaults_standard(self):
        assert parse_tier("bogus") == Tier.STANDARD


# ---------------------------------------------------------------------------
# gate decorators
# ---------------------------------------------------------------------------

class TestGates:
    def test_requires_tier_blocks_below(self):
        downgrade_to_standard_for_tests()

        @requires_tier(Tier.PRO)
        def pro_only():
            return "did the pro thing"

        with pytest.raises(EntitlementRequired) as exc:
            pro_only()
        assert exc.value.required == "tier:pro"

    def test_requires_tier_allows_when_met(self):
        grant_for_tests(tier=Tier.PRO)

        @requires_tier(Tier.PRO)
        def pro_only():
            return "ok"

        assert pro_only() == "ok"

    def test_requires_feature_blocks_without_grant(self):
        downgrade_to_standard_for_tests()

        @requires_feature(Feature.SIGNED_AUDIT)
        def signed_audit_op():
            return "ok"

        with pytest.raises(EntitlementRequired):
            signed_audit_op()

    def test_requires_feature_allows_via_extra(self):
        set_entitlements(Entitlements(
            tier=Tier.STANDARD,
            extra_features=frozenset({Feature.SIGNED_AUDIT}),
        ))

        @requires_feature(Feature.SIGNED_AUDIT)
        def op():
            return "ok"

        assert op() == "ok"

    def test_has_tier_and_feature_helpers(self):
        grant_for_tests(tier=Tier.ENTERPRISE)
        assert has_tier(Tier.PRO)
        assert has_feature(Feature.SAML_SSO)


# ---------------------------------------------------------------------------
# activate / license CLI
# ---------------------------------------------------------------------------

class TestLicenseCLI:
    def test_activate_and_license_status(self, keypair, pubkey_env, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol import platform as plat

        lic_path = tmp_path / "license.json"
        monkeypatch.setattr(plat, "license_path", lambda: lic_path)
        # Also patch through the licensing import — same function-level capture
        # as the MCP config case earlier.
        from cortex_protocol.licensing import license as lic_mod
        monkeypatch.setattr(lic_mod, "license_path", lambda: lic_path)

        priv, _ = keypair
        src = tmp_path / "incoming.json"
        src.write_text(_mint_license(priv, tier="pro"))

        runner = CliRunner()
        result = runner.invoke(main, ["activate", str(src)])
        assert result.exit_code == 0, result.output
        assert lic_path.exists()
        assert "pro" in result.output

        set_entitlements(None)  # force re-resolve after activation

        result2 = runner.invoke(main, ["license", "--format", "json"])
        assert result2.exit_code == 0, result2.output
        payload = json.loads(result2.output)
        assert payload["tier"] == "pro"
        assert payload["license_present"] is True
        assert "hosted_registry" in payload["features"]

    def test_deactivate(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol import platform as plat
        from cortex_protocol.licensing import license as lic_mod

        lic_path = tmp_path / "license.json"
        lic_path.write_text("{}")  # contents don't matter for removal
        monkeypatch.setattr(plat, "license_path", lambda: lic_path)
        monkeypatch.setattr(lic_mod, "license_path", lambda: lic_path)

        runner = CliRunner()
        result = runner.invoke(main, ["deactivate"])
        assert result.exit_code == 0
        assert not lic_path.exists()

    def test_license_shows_standard_when_missing(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol import platform as plat
        from cortex_protocol.licensing import license as lic_mod

        lic_path = tmp_path / "missing.json"
        monkeypatch.setattr(plat, "license_path", lambda: lic_path)
        monkeypatch.setattr(lic_mod, "license_path", lambda: lic_path)

        runner = CliRunner()
        result = runner.invoke(main, ["license"])
        assert result.exit_code == 0
        assert "standard" in result.output.lower()
