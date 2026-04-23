"""Tests for the Cortex Cloud audit event exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.cloud.audit_exporter import (
    CloudAuditExporter,
    drain_fallback,
)
from cortex_protocol.cloud.client import CloudClient, CloudHTTPError
from cortex_protocol.governance.audit import AuditEvent, AuditLog
from cortex_protocol.licensing import Feature, Tier, grant_for_tests, set_entitlements


@pytest.fixture(autouse=True)
def _reset_entitlements():
    set_entitlements(None)
    yield
    set_entitlements(None)


class _FakeTransport:
    """Records calls and returns programmed responses per endpoint."""

    def __init__(self, responses=None, fail_times=0, fail_status=503):
        self.calls: list[tuple[str, str, dict]] = []
        self._responses = list(responses or [])
        self._fail_times = fail_times
        self._fail_status = fail_status

    def __call__(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.calls.append((method, url, body))
        if self._fail_times > 0:
            self._fail_times -= 1
            return (self._fail_status, {}, {"error": "transient"})
        if self._responses:
            return self._responses.pop(0)
        return (200, {}, {"accepted": True})


def _mkevent(i: int) -> AuditEvent:
    return AuditEvent.now(
        run_id="r", agent="a", turn=i,
        event_type="tool_call", allowed=True, tool_name=f"t{i}",
    )


class TestExporter:
    def test_requires_cloud_audit_feature(self):
        # No grant => Standard tier => exporter degrades to no-op.
        client = CloudClient(base_url="https://x", token="t", http=_FakeTransport())
        warnings = []
        exp = CloudAuditExporter(client, warn=warnings.append)
        assert exp.degraded
        exp.export_event(_mkevent(1))
        assert not client._http.calls  # nothing sent
        assert warnings  # warning was printed

    def test_flushes_on_batch_size(self):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport()
        client = CloudClient(base_url="https://x", token="t", http=transport)
        exp = CloudAuditExporter(client, batch_size=3, flush_interval_seconds=1000)
        for i in range(3):
            exp.export_event(_mkevent(i))
        # Exactly one POST fired with 3 events.
        post_calls = [c for c in transport.calls if c[0] == "POST"]
        assert len(post_calls) == 1
        body = post_calls[0][2]
        assert len(body["events"]) == 3

    def test_flushes_on_interval(self):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport()
        client = CloudClient(base_url="https://x", token="t", http=transport)
        ts = [0.0]
        exp = CloudAuditExporter(
            client, batch_size=1000, flush_interval_seconds=1.0,
            clock=lambda: ts[0],
        )
        exp.export_event(_mkevent(1))
        assert not transport.calls  # under interval
        ts[0] = 2.0  # fast-forward past the interval
        exp.export_event(_mkevent(2))
        assert any(c[0] == "POST" for c in transport.calls)

    def test_explicit_flush_sends_pending(self):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport()
        client = CloudClient(base_url="https://x", token="t", http=transport)
        exp = CloudAuditExporter(client, batch_size=100, flush_interval_seconds=1000)
        exp.export_event(_mkevent(1))
        exp.flush()
        post_calls = [c for c in transport.calls if c[0] == "POST"]
        assert len(post_calls) == 1

    def test_retries_transient_5xx(self, monkeypatch):
        grant_for_tests(tier=Tier.PRO)
        # Pre-program 2 failures then success.
        transport = _FakeTransport(fail_times=2, fail_status=503)
        client = CloudClient(base_url="https://x", token="t", http=transport)
        monkeypatch.setattr("cortex_protocol.cloud.audit_exporter.time.sleep",
                            lambda _s: None)
        exp = CloudAuditExporter(client, batch_size=1, flush_interval_seconds=1000, max_retries=3)
        exp.export_event(_mkevent(1))
        # Three attempts total: 2 fails + 1 success.
        assert len(transport.calls) == 3

    def test_gives_up_after_max_retries_and_falls_back(self, tmp_path, monkeypatch):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport(fail_times=100, fail_status=503)
        client = CloudClient(base_url="https://x", token="t", http=transport)
        monkeypatch.setattr("cortex_protocol.cloud.audit_exporter.time.sleep",
                            lambda _s: None)
        fb = tmp_path / "fallback.jsonl"
        warnings = []
        exp = CloudAuditExporter(
            client, batch_size=1, flush_interval_seconds=1000, max_retries=2,
            fallback_path=fb, warn=warnings.append,
        )
        exp.export_event(_mkevent(1))
        # max_retries=2 => 3 calls total.
        assert len(transport.calls) == 3
        assert fb.exists()
        rows = [line for line in fb.read_text().splitlines() if line.strip()]
        assert len(rows) == 1
        assert any("failed" in w.lower() for w in warnings)

    def test_does_not_retry_on_4xx(self, tmp_path, monkeypatch):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport(fail_times=100, fail_status=400)
        client = CloudClient(base_url="https://x", token="t", http=transport)
        monkeypatch.setattr("cortex_protocol.cloud.audit_exporter.time.sleep",
                            lambda _s: None)
        exp = CloudAuditExporter(
            client, batch_size=1, flush_interval_seconds=1000, max_retries=5,
            fallback_path=tmp_path / "fb.jsonl",
        )
        exp.export_event(_mkevent(1))
        assert len(transport.calls) == 1  # 4xx => no retry

    def test_integration_with_auditlog(self, tmp_path):
        grant_for_tests(tier=Tier.PRO)
        transport = _FakeTransport()
        client = CloudClient(base_url="https://x", token="t", http=transport)
        exp = CloudAuditExporter(client, batch_size=1, flush_interval_seconds=1000)
        log = AuditLog(path=tmp_path / "audit.jsonl", exporters=[exp])
        log.write(_mkevent(1))
        assert any(c[0] == "POST" for c in transport.calls)


class TestDrainFallback:
    def test_replays_everything_when_endpoint_succeeds(self, tmp_path):
        grant_for_tests(tier=Tier.PRO)
        fb = tmp_path / "fb.jsonl"
        fb.write_text(
            json.dumps(_mkevent(1).to_dict()) + "\n"
            + json.dumps(_mkevent(2).to_dict()) + "\n"
        )
        transport = _FakeTransport()
        client = CloudClient(base_url="https://x", token="t", http=transport)
        sent, remaining = drain_fallback(fb, client, batch_size=10)
        assert sent == 2 and remaining == 0
        assert not fb.exists()

    def test_keeps_unsent_on_failure(self, tmp_path):
        grant_for_tests(tier=Tier.PRO)
        fb = tmp_path / "fb.jsonl"
        fb.write_text(
            json.dumps(_mkevent(1).to_dict()) + "\n"
            + json.dumps(_mkevent(2).to_dict()) + "\n"
        )
        transport = _FakeTransport(fail_times=100, fail_status=503)
        client = CloudClient(base_url="https://x", token="t", http=transport)
        sent, remaining = drain_fallback(fb, client, batch_size=2)
        assert sent == 0 and remaining == 2
        assert fb.exists()
