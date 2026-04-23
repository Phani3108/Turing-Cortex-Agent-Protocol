"""Agent compilation manifest — the canonical tool-manifest / SBOM.

Manifest schema (v1.0):

    {
      "schema_version": "1.0",
      "turing_version":  "0.6.0",
      "built_at":        "2026-04-23T12:00:00Z",
      "agent": {
        "name":        "payment-processor",
        "version":     "0.3",
        "spec_sha256": "ab12...",
      },
      "target": "claude-sdk",
      "model":   { "preferred": "claude-sonnet-4", "fallback": "gpt-4o" },
      "tools": [
        { "name": "process-payment", "mcp": "mcp-server-stripe@1.0.0",
          "package": "@anthropic/mcp-server-stripe", "env_vars": ["STRIPE_API_KEY"],
          "declared_parameters_sha256": "..." },
        ...
      ],
      "policy": {
        "template": "payment-safe",
        "max_turns": 10, "max_cost_usd": 5.0,
        "require_approval": ["process-payment"], "forbidden_actions": ["log card data"]
      },
      "outputs": {
        "agent.py":    { "sha256": "...", "size": 1234 },
        "README.md":   { "sha256": "...", "size": 567 }
      },
      "signature": "ed25519:..."   // omitted if unsigned
    }

Signing input is the canonical JSON of everything except `signature`.
Verification matches the evidence-packet story: hash every output file
that exists alongside the manifest and ensure their sha256s match.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .. import __version__
from ..licensing.crypto import canonical_json, sha256_hex, sign_payload, verify_signature
from ..models import AgentSpec


MANIFEST_SCHEMA_VERSION = "1.0"


@dataclass
class ToolEntry:
    name: str
    mcp: str = ""                       # mcp-server-name@version if declared
    package: str = ""                   # resolved npm/pip package name
    env_vars: list[str] = field(default_factory=list)
    declared_parameters_sha256: str = ""


@dataclass
class AgentManifest:
    schema_version: str
    turing_version: str
    built_at: str
    agent: dict
    target: str
    model: dict
    tools: list[ToolEntry]
    policy: dict
    outputs: dict
    signature: Optional[str] = None
    public_key: Optional[str] = None    # bundled with signed manifests for offline verify

    def to_dict(self, *, include_signature: bool = True) -> dict:
        d = asdict(self)
        if not include_signature:
            d.pop("signature", None)
            d.pop("public_key", None)
        return {k: v for k, v in d.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return sha256_hex(data)


def _params_hash(tool) -> str:
    return _sha256_bytes(canonical_json(tool.parameters.model_dump()))


def build_manifest(
    *,
    spec: AgentSpec,
    target: str,
    spec_yaml: str,
    output_files: dict[str, bytes | str],
    private_key: Optional[Ed25519PrivateKey] = None,
    public_key: Optional[Ed25519PublicKey] = None,
    now: Optional[_dt.datetime] = None,
) -> AgentManifest:
    """Assemble a manifest from a compile run.

    `output_files` is filename -> raw bytes (or str, which we encode).
    If `private_key` is provided, the manifest is signed; `public_key` is
    optionally embedded so auditors don't need out-of-band key material.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)

    from ..network.mcp import MCPServerRegistry, parse_mcp_ref
    reg = MCPServerRegistry()

    tools: list[ToolEntry] = []
    for t in spec.tools:
        package = ""
        env_vars: list[str] = []
        if t.mcp:
            name, _version = parse_mcp_ref(t.mcp)
            info = reg.get(name)
            if info:
                package = info.package
                env_vars = list(info.env_vars)
        tools.append(ToolEntry(
            name=t.name,
            mcp=t.mcp or "",
            package=package,
            env_vars=env_vars,
            declared_parameters_sha256=_params_hash(t),
        ))

    outputs = {}
    for name, data in output_files.items():
        if isinstance(data, str):
            data = data.encode("utf-8")
        outputs[name] = {"sha256": _sha256_bytes(data), "size": len(data)}

    policy = spec.policies.model_dump(exclude_none=True)

    manifest = AgentManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        turing_version=__version__,
        built_at=now.isoformat(),
        agent={
            "name": spec.agent.name,
            "version": spec.version,
            "spec_sha256": _sha256_bytes(spec_yaml.encode("utf-8")),
        },
        target=target,
        model={
            "preferred": spec.model.preferred,
            "fallback": spec.model.fallback or "",
        },
        tools=tools,
        policy=policy,
        outputs=outputs,
    )

    if private_key is not None:
        payload = manifest.to_dict(include_signature=False)
        manifest.signature = sign_payload(private_key, payload)
        if public_key is not None:
            from ..licensing.crypto import public_key_to_pem
            manifest.public_key = public_key_to_pem(public_key)

    return manifest


def write_manifest(manifest: AgentManifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.to_json())
    return path


def load_manifest(path: Path) -> AgentManifest:
    data = json.loads(Path(path).read_text())
    return AgentManifest(
        schema_version=data.get("schema_version", "1.0"),
        turing_version=data.get("turing_version", ""),
        built_at=data.get("built_at", ""),
        agent=data.get("agent", {}),
        target=data.get("target", ""),
        model=data.get("model", {}),
        tools=[ToolEntry(**t) for t in data.get("tools", [])],
        policy=data.get("policy", {}),
        outputs=data.get("outputs", {}),
        signature=data.get("signature"),
        public_key=data.get("public_key"),
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

@dataclass
class ManifestVerifyResult:
    ok: bool
    findings: list[str]


def verify_manifest(
    manifest_path: Path,
    *,
    artifacts_dir: Optional[Path] = None,
    public_key: Optional[Ed25519PublicKey] = None,
) -> ManifestVerifyResult:
    """Re-hash every output file and optionally verify the manifest signature.

    `artifacts_dir` is where the output files live. Defaults to the
    directory containing the manifest.
    """
    findings: list[str] = []
    ok = True
    manifest = load_manifest(Path(manifest_path))
    base = Path(artifacts_dir or Path(manifest_path).parent)

    for name, meta in manifest.outputs.items():
        fpath = base / name
        if not fpath.exists():
            findings.append(f"  [!] missing output: {name}")
            ok = False
            continue
        actual = _sha256_bytes(fpath.read_bytes())
        if actual != meta["sha256"]:
            findings.append(f"  [!] hash mismatch on {name}")
            ok = False
        else:
            findings.append(f"  [ok] {name}")

    if manifest.signature is None:
        findings.append("  [..] manifest is unsigned")
    else:
        pk = public_key
        if pk is None and manifest.public_key:
            from ..licensing.crypto import load_public_key
            pk = load_public_key(manifest.public_key)
        if pk is None:
            findings.append("  [!] signed manifest but no public key supplied")
            ok = False
        else:
            payload = manifest.to_dict(include_signature=False)
            if verify_signature(pk, payload, manifest.signature):
                findings.append("  [ok] manifest signature verified")
            else:
                findings.append("  [!] manifest signature INVALID")
                ok = False

    return ManifestVerifyResult(ok=ok, findings=findings)
