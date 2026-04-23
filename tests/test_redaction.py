"""Tests for the PII/secrets redaction engine and prebuilt packs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.governance.audit import AuditEvent, AuditLog
from cortex_protocol.governance.redaction import (
    BUILTIN_PACKS,
    RedactingExporter,
    RedactionPipeline,
    RegexRedactor,
    combine_packs,
    gdpr_pack,
    hipaa_pack,
    pci_pack,
    redact_event,
    redact_text,
    secrets_pack,
)
from cortex_protocol.governance.redaction.engine import RedactingAuditLog


class TestRegexRedactor:
    def test_single_match_replaces(self):
        r = RegexRedactor(id="email", pattern=r"\S+@\S+")
        out = r.apply("contact me at user@example.com please")
        assert out.redacted
        assert "user@example.com" not in out.text
        assert "<EMAIL_REDACTED>" in out.text

    def test_no_match_returns_original(self):
        r = RegexRedactor(id="email", pattern=r"\S+@\S+")
        out = r.apply("no email here")
        assert not out.redacted
        assert out.text == "no email here"

    def test_custom_replacement(self):
        r = RegexRedactor(id="email", pattern=r"\S+@\S+", replacement="[REDACTED]")
        out = r.apply("x@y.com")
        assert out.text == "[REDACTED]"

    def test_counts_multiple_hits(self):
        r = RegexRedactor(id="email", pattern=r"\S+@\S+")
        out = r.apply("a@b.com, c@d.com, e@f.com")
        assert out.hits.count("email") == 3


class TestPipeline:
    def test_sequence_of_redactors(self):
        p = RedactionPipeline([
            RegexRedactor(id="email", pattern=r"\S+@\S+"),
            RegexRedactor(id="phone", pattern=r"\d{3}-\d{3}-\d{4}"),
        ])
        out = p.apply("Email u@x.com or call 555-123-4567")
        assert "u@x.com" not in out.text
        assert "555-123-4567" not in out.text
        assert set(out.hits) == {"email", "phone"}

    def test_empty_pipeline_passthrough(self):
        p = RedactionPipeline()
        out = p.apply("anything goes")
        assert out.text == "anything goes"
        assert not out.redacted


class TestGDPRPack:
    def test_email(self):
        out = gdpr_pack().apply("Send receipt to buyer@example.com")
        assert "buyer@example.com" not in out.text
        assert "email" in out.hits

    def test_phone(self):
        out = gdpr_pack().apply("Call +1-555-123-4567 tomorrow")
        assert "555-123-4567" not in out.text
        assert "phone" in out.hits

    def test_ipv4(self):
        out = gdpr_pack().apply("Reached from 203.0.113.42 this morning")
        assert "203.0.113.42" not in out.text
        assert "ipv4" in out.hits

    def test_ipv6(self):
        out = gdpr_pack().apply("source=2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert "2001:0db8" not in out.text


class TestHIPAAPack:
    def test_includes_gdpr(self):
        out = hipaa_pack().apply("patient user@example.com")
        assert "user@example.com" not in out.text

    def test_ssn(self):
        out = hipaa_pack().apply("SSN 123-45-6789 on file")
        assert "123-45-6789" not in out.text

    def test_mrn_labeled(self):
        out = hipaa_pack().apply("MRN 1234567 admitted")
        # The numeric portion must vanish.
        assert "1234567" not in out.text

    def test_dob(self):
        out = hipaa_pack().apply("DOB 04/15/1982 recorded")
        assert "04/15/1982" not in out.text


class TestPCIPack:
    def test_card_number(self):
        out = pci_pack().apply("card 4111 1111 1111 1111 expires soon")
        assert "4111" not in out.text

    def test_cvv(self):
        out = pci_pack().apply("CVV: 123 on the back")
        assert "123" not in out.text

    def test_does_not_nuke_small_numbers(self):
        out = pci_pack().apply("Order 42 has 3 items")
        # The short digit tokens must survive.
        assert "42" in out.text
        assert "3" in out.text


class TestSecretsPack:
    # Fixtures are constructed at import time to avoid tripping GitHub's
    # secret-scanner (which flags on-disk string literals that *look* like
    # real Stripe / GitHub / OpenAI keys). Assembling them from parts means
    # the source file never contains a full key-shaped literal.
    _ALPHA24 = "A" * 24
    _ALPHA36 = "B" * 36
    _ALPHA40 = "C" * 40
    _AWS_EXAMPLE = "AKIA" + ("0" * 16)                     # aws_access_key shape
    _STRIPE_FIXTURE   = "sk" + "_" + "test" + "_" + _ALPHA24   # stripe_key shape
    _GITHUB_FIXTURE   = "ghp" + "_" + _ALPHA36              # github_pat shape
    _OPENAI_FIXTURE   = "sk" + "-" + ("9" * 30)             # openai_key shape
    _ANTHROPIC_FIXTURE = "sk" + "-" + "ant" + "-" + _ALPHA40
    _SLACK_FIXTURE    = "xoxb" + "-" + "0000000000" + "-" + "abcdef"

    @pytest.fixture(
        params=[
            ("aws_access_key", f"key={_AWS_EXAMPLE}"),
            ("stripe_key",    f"stripe={_STRIPE_FIXTURE}"),
            ("github_pat",    f"token={_GITHUB_FIXTURE}"),
            ("openai_key",    f"openai={_OPENAI_FIXTURE}"),
            ("anthropic_key", f"claude={_ANTHROPIC_FIXTURE}"),
            ("slack_token",   f"slack={_SLACK_FIXTURE}"),
            ("bearer_token",  "Authorization: Bearer " + ("z" * 32)),
        ],
        ids=lambda v: v[0],
    )
    def sample(self, request):
        return request.param

    def test_detects(self, sample):
        expected_id, text = sample
        out = secrets_pack().apply(text)
        assert expected_id in out.hits
        # And the sensitive substring vanishes.
        sensitive = text.split("=", 1)[-1].split(": ", 1)[-1].strip()
        assert sensitive not in out.text


class TestCombinePacks:
    def test_dedup_by_id(self):
        merged = combine_packs(gdpr_pack(), hipaa_pack())
        ids = [r.id for r in merged.redactors]
        assert len(ids) == len(set(ids))
        # Both gdpr + hipaa ids should be present.
        assert "email" in ids and "ssn" in ids

    def test_builtin_packs_registry(self):
        assert set(BUILTIN_PACKS) == {"gdpr", "hipaa", "pci", "secrets"}
        for fn in BUILTIN_PACKS.values():
            assert isinstance(fn(), RedactionPipeline)


class TestEventRedaction:
    def test_redacts_detail(self):
        p = gdpr_pack()
        ev = AuditEvent.now(
            run_id="r", agent="a", turn=1,
            event_type="response", allowed=True,
            detail="responded to alice@example.com",
        )
        red, hits = redact_event(ev, p)
        assert "alice@example.com" not in red.detail
        assert hits == ["email"]

    def test_redacts_tool_input_nested(self):
        p = secrets_pack()
        ev = AuditEvent.now(
            run_id="r", agent="a", turn=1,
            event_type="tool_call", allowed=True,
            tool_name="send-email",
            tool_input={"to": "x@y.com",
                          "headers": {"Authorization": "Bearer my.secret.token"}},
            detail="ok",
        )
        red, hits = redact_event(ev, p)
        assert red.tool_input["headers"]["Authorization"] != "Bearer my.secret.token"
        assert "bearer_token" in hits

    def test_preserves_policy_fields(self):
        p = gdpr_pack()
        ev = AuditEvent.now(
            run_id="r", agent="a", turn=1,
            event_type="tool_blocked", allowed=False,
            policy="require_approval",
            tool_name="refund-order",
            detail="alice@example.com requested refund",
        )
        red, _ = redact_event(ev, p)
        assert red.policy == "require_approval"
        assert red.event_type == "tool_blocked"
        assert red.tool_name == "refund-order"
        assert red.allowed is False


class TestExporterAdapter:
    def test_downstream_sees_redacted(self, tmp_path):
        p = gdpr_pack()
        seen: list[AuditEvent] = []
        downstream = type("D", (), {"export_event": lambda self, e: seen.append(e)})()
        exporter = RedactingExporter(downstream, p)

        log = AuditLog(path=tmp_path / "audit.jsonl", exporters=[exporter])
        log.write(AuditEvent.now(
            run_id="r", agent="a", turn=1,
            event_type="response", allowed=True,
            detail="Reply sent to alice@example.com",
        ))

        assert len(seen) == 1
        assert "alice@example.com" not in seen[0].detail
        # But the on-disk file is UNTOUCHED — RedactingExporter only
        # redacts for downstream sinks, not the owning log's file.
        on_disk = (tmp_path / "audit.jsonl").read_text()
        assert "alice@example.com" in on_disk

    def test_on_hit_fires(self, tmp_path):
        p = gdpr_pack()
        calls: list[tuple] = []
        downstream = type("D", (), {"export_event": lambda self, e: None})()
        exporter = RedactingExporter(
            downstream, p, on_hit=lambda ev, hits: calls.append((ev.turn, hits)),
        )
        exporter.export_event(AuditEvent.now(
            run_id="r", agent="a", turn=7,
            event_type="response", allowed=True,
            detail="user@example.com",
        ))
        assert calls and calls[0][0] == 7
        assert "email" in calls[0][1]


class TestRedactingAuditLog:
    def test_on_disk_file_is_redacted(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        wrapped = AuditLog(path=path)
        log = RedactingAuditLog(wrapped, gdpr_pack())
        log.write(AuditEvent.now(
            run_id="r", agent="a", turn=1,
            event_type="response", allowed=True,
            detail="Ship to buyer@example.com",
        ))
        assert "buyer@example.com" not in path.read_text()

    def test_passthrough_attribute_access(self, tmp_path):
        wrapped = AuditLog(path=tmp_path / "audit.jsonl")
        log = RedactingAuditLog(wrapped, RedactionPipeline())
        # `events()` should delegate transparently.
        log.write(AuditEvent.now(run_id="r", agent="a", turn=1,
                                  event_type="tool_call", allowed=True,
                                  tool_name="x"))
        assert len(log.events()) == 1


class TestRedactText:
    def test_trivial_wrapper(self):
        assert redact_text("hi", RedactionPipeline()) == "hi"
        assert redact_text("", gdpr_pack()) == ""

    def test_real_pipeline(self):
        out = redact_text("a@b.com", gdpr_pack())
        assert "a@b.com" not in out
