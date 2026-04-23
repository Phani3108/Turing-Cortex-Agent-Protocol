"""Tests for the signed audit chain (SignedAuditLog + verify_chain)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.governance.audit import AuditEvent, AuditLog
from cortex_protocol.governance.signed_audit import (
    GENESIS,
    SignedAuditLog,
    event_hash,
    verify_chain,
    verify_event_signature,
)
from cortex_protocol.licensing.crypto import (
    generate_keypair,
    public_key_to_pem,
)


@pytest.fixture
def keypair():
    return generate_keypair()


def _mk_event(n: int) -> AuditEvent:
    return AuditEvent.now(
        run_id="r1", agent="a", turn=n,
        event_type="tool_call", allowed=True, tool_name=f"t{n}",
        detail=f"event {n}",
    )


class TestSignedWrite:
    def test_chain_starts_at_genesis(self, keypair, tmp_path):
        priv, _ = keypair
        log = SignedAuditLog(priv, path=tmp_path / "signed.jsonl")
        log.write(_mk_event(1))
        first = log.events()[0]
        assert first.chain_index == 0
        assert first.prev_hash == GENESIS
        assert first.signature and first.signature.startswith("ed25519:")

    def test_chain_links_forward(self, keypair, tmp_path):
        priv, _ = keypair
        log = SignedAuditLog(priv, path=tmp_path / "signed.jsonl")
        for i in range(1, 4):
            log.write(_mk_event(i))
        events = log.events()
        assert events[0].prev_hash == GENESIS
        assert events[1].prev_hash == event_hash(events[0])
        assert events[2].prev_hash == event_hash(events[1])
        assert [e.chain_index for e in events] == [0, 1, 2]

    def test_persisted_json_round_trips(self, keypair, tmp_path):
        priv, _ = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        log.write(_mk_event(1))
        log.write(_mk_event(2))

        reloaded = AuditLog.from_file(path)
        events = reloaded.events()
        assert len(events) == 2
        assert events[0].signature is not None
        assert events[1].prev_hash == event_hash(events[0])

    def test_append_after_reopen(self, keypair, tmp_path):
        priv, _ = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        log.write(_mk_event(1))

        # Re-open and append — chain must continue, not restart at GENESIS.
        log2 = SignedAuditLog(priv, path=path)
        log2.write(_mk_event(2))

        reloaded = AuditLog.from_file(path)
        events = reloaded.events()
        assert events[1].chain_index == 1
        assert events[1].prev_hash == event_hash(events[0])


class TestVerification:
    def test_happy_path(self, keypair, tmp_path):
        priv, pub = keypair
        log = SignedAuditLog(priv, path=tmp_path / "signed.jsonl")
        for i in range(1, 5):
            log.write(_mk_event(i))

        ok, findings = verify_chain(log.events(), pub)
        assert ok
        assert all("[ok]" in line for line in findings)

    def test_tampered_field_detected(self, keypair, tmp_path):
        priv, pub = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        log.write(_mk_event(1))
        log.write(_mk_event(2))

        # Rewrite the on-disk file with one event's detail tampered.
        raw = path.read_text().splitlines()
        modified = []
        for i, line in enumerate(raw):
            obj = json.loads(line)
            if i == 0:
                obj["detail"] = "EVIL"  # without re-signing
            modified.append(json.dumps(obj))
        path.write_text("\n".join(modified) + "\n")

        reloaded = AuditLog.from_file(path)
        ok, findings = verify_chain(reloaded.events(), pub)
        assert not ok
        # The tampered event 0 fails signature AND event 1's prev_hash no longer matches.
        text = "\n".join(findings)
        assert "signature failed" in text or "prev_hash mismatch" in text

    def test_reordered_events_detected(self, keypair, tmp_path):
        priv, pub = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        for i in range(1, 4):
            log.write(_mk_event(i))

        # Swap events 1 and 2 on disk.
        lines = path.read_text().splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        path.write_text("\n".join(lines) + "\n")

        reloaded = AuditLog.from_file(path)
        ok, findings = verify_chain(reloaded.events(), pub)
        assert not ok

    def test_wrong_public_key_fails(self, keypair, tmp_path):
        priv, _ = keypair
        log = SignedAuditLog(priv, path=tmp_path / "signed.jsonl")
        log.write(_mk_event(1))
        # Different keypair than the signer.
        _, other_pub = generate_keypair()
        ok, _ = verify_chain(log.events(), other_pub)
        assert not ok

    def test_unsigned_event_in_stream_fails(self, keypair, tmp_path):
        priv, pub = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        log.write(_mk_event(1))

        # Sneak in an unsigned event through the raw AuditLog API.
        plain = AuditLog(path=path)
        plain.write(_mk_event(2))  # no signature

        reloaded = AuditLog.from_file(path)
        ok, _ = verify_chain(reloaded.events(), pub)
        assert not ok


class TestAuditVerifyCLI:
    def test_cli_verifies_signed_log(self, keypair, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        priv, pub = keypair
        log = SignedAuditLog(priv, path=tmp_path / "signed.jsonl")
        log.write(_mk_event(1))
        log.write(_mk_event(2))

        monkeypatch.setenv("CORTEX_LICENSE_PUBKEY", public_key_to_pem(pub))
        runner = CliRunner()
        result = runner.invoke(main, [
            "audit-verify", str(tmp_path / "signed.jsonl"), "--format", "json",
        ])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["event_count"] == 2

    def test_cli_fails_on_tampered_log(self, keypair, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        priv, pub = keypair
        path = tmp_path / "signed.jsonl"
        log = SignedAuditLog(priv, path=path)
        log.write(_mk_event(1))
        log.write(_mk_event(2))

        # Mutate the first line without re-signing.
        lines = path.read_text().splitlines()
        obj = json.loads(lines[0])
        obj["detail"] = "tampered"
        lines[0] = json.dumps(obj)
        path.write_text("\n".join(lines) + "\n")

        monkeypatch.setenv("CORTEX_LICENSE_PUBKEY", public_key_to_pem(pub))
        runner = CliRunner()
        result = runner.invoke(main, ["audit-verify", str(path)])
        assert result.exit_code == 1
        assert "TAMPERED" in result.output
