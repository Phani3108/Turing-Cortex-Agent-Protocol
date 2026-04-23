"""Evidence packets — auditor-ready bundles of signed audit + compliance data.

A packet is a single ZIP with a stable layout:

    manifest.json              issuer metadata (signature, hashes, timestamps)
    spec.yaml                  agent spec at time of report
    audit.jsonl                the source audit log (signed chain preserved)
    drift.json                 drift report vs. spec
    compliance.json            SOC2/HIPAA/PCI-DSS control results (JSON)
    compliance.md              same, markdown — readable by a human auditor
    chain_verification.json    pass/fail of the signature-chain verification
    README.md                  auditor-facing instructions

If a private key is provided, the manifest itself is Ed25519-signed so an
external verifier can trust the packet end-to-end without touching the
Cloud service. If no key is passed, the manifest is still written but
carries `signature: null` — useful for local builds.

Verification of a packet consists of:
    1. Re-hash each file, compare to `manifest.files[<name>].sha256`
    2. Re-verify audit.jsonl's internal signed chain
    3. Verify the manifest's own signature (if present)
"""

from __future__ import annotations

import datetime as _dt
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..licensing.crypto import (
    canonical_json,
    public_key_to_pem,
    sha256_hex,
    sign_payload,
    verify_signature,
)
from .audit import AuditLog
from .signed_audit import verify_chain

PACKET_SCHEMA_VERSION = "1.0"


@dataclass
class PacketBuildResult:
    path: Path
    packet_id: str
    manifest_signed: bool
    chain_verified: bool
    files: dict[str, str]  # filename -> sha256


def _file_sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return sha256_hex(content)


def build_evidence_packet(
    *,
    audit_path: Path,
    spec_path: Path,
    output_path: Path,
    standard: str = "soc2",
    private_key: Optional[Ed25519PrivateKey] = None,
    public_key: Optional[Ed25519PublicKey] = None,
    reviewer: str = "",
    now: Optional[_dt.datetime] = None,
) -> PacketBuildResult:
    """Build an evidence packet ZIP at `output_path`.

    `private_key` signs the manifest; omit to produce an unsigned local build.
    `public_key` (if signed audits are present) is used to verify the chain
    and embed the verdict in the packet; omit to skip chain verification.
    """
    from ..validator import validate_file
    from .compliance import generate_compliance_report, export_compliance_json
    from .drift import detect_drift

    now = now or _dt.datetime.now(_dt.timezone.utc)
    audit_path = Path(audit_path)
    spec_path = Path(spec_path)
    output_path = Path(output_path)

    spec, errors = validate_file(str(spec_path))
    if spec is None:
        raise ValueError(f"Spec at {spec_path} did not validate: {errors}")
    audit_log = AuditLog.from_file(audit_path)

    drift = detect_drift(spec, audit_log)
    compliance_md = generate_compliance_report(audit_log, standard=standard, spec=spec)
    compliance_json = export_compliance_json(audit_log, standard=standard, spec=spec)

    chain_ok: Optional[bool] = None
    chain_findings: list[str] = []
    if public_key is not None:
        chain_ok, chain_findings = verify_chain(audit_log.events(), public_key)

    # Prepare file bytes up-front so the manifest can embed their hashes.
    spec_bytes = spec_path.read_bytes()
    audit_bytes = audit_path.read_bytes()
    drift_bytes = json.dumps(drift.to_dict(), indent=2).encode("utf-8")
    compliance_md_bytes = compliance_md.encode("utf-8")
    compliance_json_bytes = json.dumps(compliance_json, indent=2).encode("utf-8")
    chain_bytes = json.dumps(
        {"ok": chain_ok, "findings": chain_findings},
        indent=2,
    ).encode("utf-8")
    readme_bytes = _README_TEMPLATE.encode("utf-8")

    files = {
        "spec.yaml":               spec_bytes,
        "audit.jsonl":             audit_bytes,
        "drift.json":               drift_bytes,
        "compliance.md":            compliance_md_bytes,
        "compliance.json":          compliance_json_bytes,
        "chain_verification.json":  chain_bytes,
        "README.md":                readme_bytes,
    }
    file_hashes = {name: _file_sha256(data) for name, data in files.items()}

    packet_id = f"ep-{uuid.uuid4().hex[:12]}"
    manifest_payload = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "packet_id": packet_id,
        "created_at": now.isoformat(),
        "agent": spec.agent.name,
        "spec_version": spec.version,
        "standard": standard,
        "reviewer": reviewer,
        "drift_compliance_score": drift.compliance_score,
        "chain_verified": chain_ok,
        "files": {
            name: {"sha256": sha, "size": len(files[name])}
            for name, sha in file_hashes.items()
        },
    }

    signature = None
    if private_key is not None:
        signature = sign_payload(private_key, manifest_payload)
    manifest = dict(manifest_payload)
    manifest["signature"] = signature
    if public_key is not None:
        manifest["public_key"] = public_key_to_pem(public_key)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        for name, data in files.items():
            zf.writestr(name, data)

    return PacketBuildResult(
        path=output_path,
        packet_id=packet_id,
        manifest_signed=signature is not None,
        chain_verified=bool(chain_ok),
        files=file_hashes,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class PacketVerifyResult:
    ok: bool
    packet_id: str
    findings: list[str]


def verify_evidence_packet(
    packet_path: Path,
    *,
    public_key: Optional[Ed25519PublicKey] = None,
) -> PacketVerifyResult:
    """Open a packet, re-hash every file, re-verify manifest signature.

    If `public_key` is None but the manifest embeds a `public_key` field,
    that key is trusted transitively (equivalent to a self-signed packet
    — useful for quick local checks, not for formal assurance).
    """
    findings: list[str] = []
    ok = True
    path = Path(packet_path)
    with ZipFile(path) as zf:
        with zf.open("manifest.json") as f:
            manifest = json.loads(f.read().decode("utf-8"))

        # Hash check each file.
        for name, meta in manifest.get("files", {}).items():
            try:
                with zf.open(name) as f:
                    data = f.read()
            except KeyError:
                findings.append(f"  [!] missing file in packet: {name}")
                ok = False
                continue
            actual = _file_sha256(data)
            if actual != meta["sha256"]:
                findings.append(f"  [!] hash mismatch on {name}")
                ok = False
            else:
                findings.append(f"  [ok] {name}")

        # Manifest signature.
        sig = manifest.get("signature")
        if sig is None:
            findings.append("  [..] manifest is unsigned")
        else:
            pk = public_key
            if pk is None and manifest.get("public_key"):
                from ..licensing.crypto import load_public_key
                pk = load_public_key(manifest["public_key"])
            if pk is None:
                findings.append("  [!] signed manifest but no public key supplied")
                ok = False
            else:
                signed_payload = {k: v for k, v in manifest.items()
                                  if k not in {"signature", "public_key"}}
                if verify_signature(pk, signed_payload, sig):
                    findings.append("  [ok] manifest signature verified")
                else:
                    findings.append("  [!] manifest signature INVALID")
                    ok = False

    return PacketVerifyResult(
        ok=ok,
        packet_id=manifest.get("packet_id", "unknown"),
        findings=findings,
    )


_README_TEMPLATE = """\
# Turing Evidence Packet

This ZIP is a tamper-evident bundle of governance evidence produced by
Turing (Cortex Protocol). Every file listed in `manifest.json` is hashed
(SHA-256), and if the manifest carries a `signature`, the whole bundle is
Ed25519-signed by the issuer.

## Contents

- `manifest.json`              Issuer metadata, file hashes, signature
- `spec.yaml`                  The agent specification under review
- `audit.jsonl`                The source audit log (signed chain if present)
- `drift.json`                 Drift between declared spec and observed behavior
- `compliance.md` / `.json`    SOC2 / HIPAA / PCI-DSS / GDPR control evaluation
- `chain_verification.json`    Result of re-verifying the audit log's signature chain

## How to verify

Using Turing:

    cortex-protocol evidence-verify <packet.zip>

Programmatically:

    from cortex_protocol.governance.evidence import verify_evidence_packet
    result = verify_evidence_packet("packet.zip", public_key=<pubkey>)
    assert result.ok

Without Turing (hash check only):

    unzip -p packet.zip manifest.json | jq -r '.files | to_entries[] | \"\\(.value.sha256)  \\(.key)\"' \\
      | (cd /tmp/unpacked && shasum -a 256 -c -)
"""
