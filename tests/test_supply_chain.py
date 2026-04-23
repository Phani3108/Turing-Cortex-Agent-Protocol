"""Tests for the supply-chain manifest (SBOM) builder + verifier."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.models import (
    AgentIdentity, AgentSpec, ModelConfig, PolicySpec, ToolParameter, ToolSpec,
)
from cortex_protocol.licensing.crypto import generate_keypair, public_key_to_pem
from cortex_protocol.supply_chain import (
    build_manifest,
    load_manifest,
    verify_manifest,
    write_manifest,
)


def _spec():
    return AgentSpec(
        version="0.3",
        agent=AgentIdentity(name="sc-test", description="supply chain",
                             instructions="You do things. Cite sources. Escalate when unsure."),
        tools=[
            ToolSpec(name="process-payment",
                     description="Charge a card",
                     parameters=ToolParameter(type="object",
                                               properties={"amount": {"type": "number"}},
                                               required=["amount"]),
                     mcp="mcp-server-stripe@1.0.0"),
        ],
        policies=PolicySpec(max_turns=5,
                             require_approval=["process-payment"],
                             forbidden_actions=["log credentials"]),
        model=ModelConfig(preferred="claude-sonnet-4", fallback="gpt-4o"),
    )


class TestBuild:
    def test_basic_fields(self):
        spec = _spec()
        m = build_manifest(
            spec=spec, target="claude-sdk",
            spec_yaml=spec.to_yaml(),
            output_files={"agent.py": "print('hi')\n", "README.md": "docs"},
        )
        assert m.agent["name"] == "sc-test"
        assert m.target == "claude-sdk"
        assert m.turing_version  # non-empty
        assert m.outputs["agent.py"]["size"] == len("print('hi')\n")
        assert m.outputs["agent.py"]["sha256"]

    def test_resolves_mcp_package(self):
        spec = _spec()
        m = build_manifest(
            spec=spec, target="openai-sdk",
            spec_yaml=spec.to_yaml(),
            output_files={},
        )
        tool = m.tools[0]
        assert tool.mcp == "mcp-server-stripe@1.0.0"
        assert tool.package  # resolved from the bundled registry
        assert "STRIPE_API_KEY" in tool.env_vars

    def test_parameters_hash_stable(self):
        spec = _spec()
        m1 = build_manifest(spec=spec, target="claude-sdk",
                             spec_yaml=spec.to_yaml(), output_files={})
        m2 = build_manifest(spec=spec, target="claude-sdk",
                             spec_yaml=spec.to_yaml(), output_files={})
        assert m1.tools[0].declared_parameters_sha256 == m2.tools[0].declared_parameters_sha256

    def test_sign_attaches_signature_and_embeds_pubkey(self):
        spec = _spec()
        priv, pub = generate_keypair()
        m = build_manifest(
            spec=spec, target="claude-sdk",
            spec_yaml=spec.to_yaml(),
            output_files={"agent.py": "x"},
            private_key=priv, public_key=pub,
        )
        assert m.signature and m.signature.startswith("ed25519:")
        assert m.public_key and "BEGIN PUBLIC KEY" in m.public_key

    def test_unsigned_builds(self):
        spec = _spec()
        m = build_manifest(
            spec=spec, target="claude-sdk",
            spec_yaml=spec.to_yaml(),
            output_files={"agent.py": "x"},
        )
        assert m.signature is None


class TestRoundTrip:
    def test_write_and_load(self, tmp_path):
        spec = _spec()
        m = build_manifest(spec=spec, target="claude-sdk",
                            spec_yaml=spec.to_yaml(), output_files={"a.py": "x"})
        path = tmp_path / "manifest.json"
        write_manifest(m, path)
        loaded = load_manifest(path)
        assert loaded.agent["name"] == "sc-test"
        assert loaded.tools[0].name == "process-payment"


class TestVerify:
    def test_happy_path(self, tmp_path):
        spec = _spec()
        priv, pub = generate_keypair()

        # Build artifacts + manifest in the same dir.
        work = tmp_path / "out"
        work.mkdir()
        (work / "agent.py").write_text("print('hi')\n")
        (work / "README.md").write_text("docs")

        m = build_manifest(
            spec=spec, target="claude-sdk",
            spec_yaml=spec.to_yaml(),
            output_files={"agent.py": (work / "agent.py").read_bytes(),
                           "README.md": (work / "README.md").read_bytes()},
            private_key=priv, public_key=pub,
        )
        mpath = work / "manifest.json"
        write_manifest(m, mpath)

        result = verify_manifest(mpath)  # pubkey is embedded
        assert result.ok
        assert any("agent.py" in line and "ok" in line for line in result.findings)

    def test_missing_file_detected(self, tmp_path):
        spec = _spec()
        work = tmp_path / "out"
        work.mkdir()
        (work / "agent.py").write_text("x")
        m = build_manifest(spec=spec, target="claude-sdk",
                            spec_yaml=spec.to_yaml(),
                            output_files={"agent.py": b"x",
                                           "gone.md": b"removed later"})
        mpath = work / "manifest.json"
        write_manifest(m, mpath)
        result = verify_manifest(mpath)
        assert not result.ok
        assert any("missing" in line for line in result.findings)

    def test_tampered_file_detected(self, tmp_path):
        spec = _spec()
        work = tmp_path / "out"
        work.mkdir()
        (work / "agent.py").write_text("original")
        m = build_manifest(spec=spec, target="claude-sdk",
                            spec_yaml=spec.to_yaml(),
                            output_files={"agent.py": b"original"})
        mpath = work / "manifest.json"
        write_manifest(m, mpath)

        # Change the file after manifest write.
        (work / "agent.py").write_text("tampered")
        result = verify_manifest(mpath)
        assert not result.ok
        assert any("hash mismatch" in line for line in result.findings)

    def test_bad_signature_detected(self, tmp_path):
        spec = _spec()
        priv, pub = generate_keypair()
        work = tmp_path / "out"
        work.mkdir()
        (work / "a.py").write_text("hello")
        m = build_manifest(spec=spec, target="claude-sdk",
                            spec_yaml=spec.to_yaml(),
                            output_files={"a.py": b"hello"},
                            private_key=priv, public_key=pub)
        mpath = work / "manifest.json"
        write_manifest(m, mpath)

        # Mutate the manifest in place (e.g. attacker bumps turing_version).
        data = json.loads(mpath.read_text())
        data["turing_version"] = "999.0.0"
        mpath.write_text(json.dumps(data))

        result = verify_manifest(mpath)
        assert not result.ok
        assert any("signature INVALID" in line for line in result.findings)


class TestCLIIntegration:
    def test_compile_emits_manifest(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec_path = tmp_path / "agent.yaml"
        spec_path.write_text(_spec().to_yaml())

        out = tmp_path / "out"
        manifest = tmp_path / "manifest.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "compile", str(spec_path),
            "--target", "system-prompt",
            "--output", str(out),
            "--manifest", str(manifest),
        ])
        assert result.exit_code == 0, result.output
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data["agent"]["name"] == "sc-test"
        assert data["outputs"]

    def test_manifest_verify_cli(self, tmp_path):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        spec_path = tmp_path / "agent.yaml"
        spec_path.write_text(_spec().to_yaml())
        out = tmp_path / "out"
        manifest = tmp_path / "manifest.json"

        runner = CliRunner()
        runner.invoke(main, [
            "compile", str(spec_path),
            "--target", "system-prompt",
            "--output", str(out),
            "--manifest", str(manifest),
        ])
        result = runner.invoke(main, [
            "manifest-verify", str(manifest),
            "--artifacts-dir", str(out),
            "--format", "json",
        ])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True
