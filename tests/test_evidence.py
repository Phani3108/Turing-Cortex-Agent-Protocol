"""Tests for the evidence packet builder + verifier."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from cortex_protocol.governance.audit import AuditEvent, AuditLog
from cortex_protocol.governance.evidence import (
    build_evidence_packet,
    verify_evidence_packet,
)
from cortex_protocol.governance.signed_audit import SignedAuditLog
from cortex_protocol.licensing.crypto import (
    generate_keypair,
    private_key_to_pem,
    public_key_to_pem,
)
from cortex_protocol.licensing.gate import grant_for_tests, set_entitlements


_SPEC = """\
version: "0.1"
agent:
  name: evidence-test
  description: Agent used by the evidence-packet tests
  instructions: |
    You do things. Escalate when unsure. Cite sources. Answer concisely.
tools:
  - name: search
    description: Search for information
    parameters:
      type: object
policies:
  max_turns: 5
  require_approval: []
  forbidden_actions: []
model:
  preferred: claude-sonnet-4
"""


@pytest.fixture
def keypair():
    return generate_keypair()


@pytest.fixture
def spec_path(tmp_path):
    p = tmp_path / "spec.yaml"
    p.write_text(_SPEC)
    return p


@pytest.fixture
def audit_path(keypair, tmp_path):
    priv, _ = keypair
    p = tmp_path / "audit.jsonl"
    log = SignedAuditLog(priv, path=p)
    log.write(AuditEvent.now(run_id="r1", agent="evidence-test", turn=1,
                              event_type="tool_call", allowed=True,
                              tool_name="search", detail="ok"))
    log.write(AuditEvent.now(run_id="r1", agent="evidence-test", turn=2,
                              event_type="response", allowed=True,
                              detail="response"))
    return p


class TestBuildPacket:
    def test_builds_zip_with_all_files(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        result = build_evidence_packet(
            audit_path=audit_path,
            spec_path=spec_path,
            output_path=out,
            private_key=priv,
            public_key=pub,
        )
        assert result.path == out
        assert out.exists()
        with ZipFile(out) as zf:
            names = set(zf.namelist())
        expected = {
            "manifest.json", "spec.yaml", "audit.jsonl",
            "drift.json", "compliance.md", "compliance.json",
            "chain_verification.json", "README.md",
        }
        assert expected <= names

    def test_manifest_records_hashes(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        result = build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,
        )
        with ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        for name, sha in result.files.items():
            assert manifest["files"][name]["sha256"] == sha

    def test_unsigned_packet_has_null_signature(self, audit_path, spec_path, tmp_path):
        out = tmp_path / "packet.zip"
        result = build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
        )
        assert not result.manifest_signed
        with ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest["signature"] is None

    def test_chain_verified_field_reflects_signed_log(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        result = build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,
        )
        assert result.chain_verified is True


class TestVerifyPacket:
    def test_valid_packet_verifies(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,
        )
        result = verify_evidence_packet(out, public_key=pub)
        assert result.ok

    def test_self_signed_packet_uses_embedded_pubkey(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,   # embeds pubkey in manifest
        )
        result = verify_evidence_packet(out)    # no explicit pubkey
        assert result.ok

    def test_tampered_file_detected(self, keypair, audit_path, spec_path, tmp_path):
        priv, pub = keypair
        out = tmp_path / "packet.zip"
        build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,
        )

        # Read the ZIP, tamper with drift.json, rewrite it.
        from zipfile import ZipFile, ZIP_DEFLATED
        tmp_zip = tmp_path / "tampered.zip"
        with ZipFile(out) as src, ZipFile(tmp_zip, "w", ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == "drift.json":
                    data = b'{"compliance_score": 0.0}'
                dst.writestr(info, data)

        result = verify_evidence_packet(tmp_zip, public_key=pub)
        assert not result.ok
        assert any("drift.json" in line for line in result.findings)


class TestEvidenceCLI:
    def _grant_pro(self):
        from cortex_protocol.licensing import Tier, Feature
        grant_for_tests(tier=Tier.PRO)

    def test_cli_gated_on_standard_tier(self, keypair, audit_path, spec_path, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol.licensing import downgrade_to_standard_for_tests

        downgrade_to_standard_for_tests()
        out = tmp_path / "packet.zip"
        runner = CliRunner()
        result = runner.invoke(main, [
            "evidence-packet", str(audit_path), str(spec_path), "-o", str(out),
        ])
        assert result.exit_code != 0
        assert "Pro tier" in result.output or "pro" in result.output.lower()
        set_entitlements(None)

    def test_cli_builds_on_pro_tier(self, keypair, audit_path, spec_path, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol.licensing import Tier

        grant_for_tests(tier=Tier.PRO)
        try:
            priv, pub = keypair
            priv_path = tmp_path / "signer.pem"
            priv_path.write_text(private_key_to_pem(priv))
            pub_path = tmp_path / "audit.pub.pem"
            pub_path.write_text(public_key_to_pem(pub))
            out = tmp_path / "packet.zip"

            runner = CliRunner()
            result = runner.invoke(main, [
                "evidence-packet", str(audit_path), str(spec_path),
                "-o", str(out),
                "--signing-key", str(priv_path),
                "--public-key", str(pub_path),
            ])
            assert result.exit_code == 0, result.output
            assert out.exists()
            assert "signed yes" in result.output
        finally:
            set_entitlements(None)

    def test_cli_verify_json_format(self, keypair, audit_path, spec_path, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        priv, pub = keypair
        out = tmp_path / "packet.zip"
        build_evidence_packet(
            audit_path=audit_path, spec_path=spec_path, output_path=out,
            private_key=priv, public_key=pub,
        )
        runner = CliRunner()
        result = runner.invoke(main, ["evidence-verify", str(out), "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["packet_id"].startswith("ep-")
