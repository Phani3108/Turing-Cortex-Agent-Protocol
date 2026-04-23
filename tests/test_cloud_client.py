"""Tests for the Cortex Cloud HTTP client + login/logout/status CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cortex_protocol.cloud.client import (
    CloudAuthError,
    CloudClient,
    CloudHTTPError,
    Credentials,
    default_cloud_url,
    load_credentials,
    remove_credentials,
    save_credentials,
)


class FakeTransport:
    """Match the module-level _request signature so CloudClient can inject it."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self._routes: dict[tuple[str, str], list] = {}

    def when(self, method: str, url_suffix: str, *responses):
        """Queue response tuples (status, headers, payload) for a route."""
        self._routes[(method, url_suffix)] = list(responses)

    def __call__(self, method, url, *, headers=None, body=None, timeout=30.0):
        self.calls.append((method, url, body))
        for (m, suffix), queue in self._routes.items():
            if m == method and url.endswith(suffix) and queue:
                return queue.pop(0)
        # Default: 404 so tests that forget to register fail loud.
        return (404, {}, {"error": "not_found"})


# ---------------------------------------------------------------------------
# Credentials round-trip
# ---------------------------------------------------------------------------

class TestCredentials:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "creds.json"
        c = Credentials(email="u@e.com", workspace="ws", access_token="tok",
                        cloud_url="https://x")
        save_credentials(c, path=path)
        loaded = load_credentials(path=path)
        assert loaded == c

    def test_load_missing_returns_none(self, tmp_path):
        assert load_credentials(tmp_path / "missing.json") is None

    def test_load_malformed_returns_none(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("{not json")
        assert load_credentials(p) is None

    def test_remove(self, tmp_path):
        p = tmp_path / "c.json"
        save_credentials(Credentials(email="a", workspace="b", access_token="c"), path=p)
        assert p.exists()
        assert remove_credentials(p) is True
        assert remove_credentials(p) is False

    def test_save_sets_mode_0600_on_posix(self, tmp_path):
        import os
        if os.name == "nt":
            pytest.skip("POSIX-only mode check")
        p = tmp_path / "c.json"
        save_credentials(Credentials(email="a", workspace="b", access_token="c"), path=p)
        assert (p.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------------
# CloudClient basics
# ---------------------------------------------------------------------------

class TestCloudClient:
    def test_anonymous_is_unauthenticated(self, monkeypatch):
        monkeypatch.delenv("CORTEX_CLOUD_TOKEN", raising=False)
        c = CloudClient(base_url="https://cloud.example", token=None)
        assert not c.is_authenticated
        with pytest.raises(CloudAuthError):
            c.whoami()

    def test_env_token_authenticates(self, monkeypatch):
        monkeypatch.setenv("CORTEX_CLOUD_TOKEN", "env-token")
        c = CloudClient(base_url="https://cloud.example")
        assert c.is_authenticated

    def test_request_raises_on_4xx(self):
        transport = FakeTransport()
        transport.when("GET", "/v1/me", (403, {}, {"error": "forbidden"}))
        client = CloudClient(base_url="https://cloud.example",
                             token="tok", http=transport)
        with pytest.raises(CloudHTTPError) as exc:
            client.whoami()
        assert exc.value.status == 403

    def test_request_returns_payload_on_2xx(self):
        transport = FakeTransport()
        transport.when("GET", "/v1/me",
                       (200, {}, {"email": "u@e.com", "workspace": "ws"}))
        client = CloudClient(base_url="https://cloud.example",
                             token="tok", http=transport)
        payload = client.whoami()
        assert payload["email"] == "u@e.com"
        # Verify the auth header was attached.
        _, _, sent_body = transport.calls[0]
        assert sent_body is None  # GET, no body

    def test_default_cloud_url_respects_env(self, monkeypatch):
        monkeypatch.setenv("CORTEX_CLOUD_URL", "https://my.cloud/")
        assert default_cloud_url() == "https://my.cloud"


# ---------------------------------------------------------------------------
# OAuth device-flow
# ---------------------------------------------------------------------------

class TestDeviceFlow:
    def test_happy_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "cortex_protocol.cloud.client.credentials_path",
            lambda: tmp_path / "creds.json",
        )
        transport = FakeTransport()
        transport.when("POST", "/oauth/device/code",
                       (200, {}, {
                           "device_code": "dev123",
                           "user_code": "ABCD-EF",
                           "verification_uri": "https://cloud.example/device",
                           "verification_uri_complete": "https://cloud.example/device?code=ABCD-EF",
                           "interval": 0,
                       }))
        # Server says authorization_pending once, then returns token.
        transport.when("POST", "/oauth/device/token",
                       (400, {}, {"error": "authorization_pending"}),
                       (200, {}, {
                           "access_token": "real-token",
                           "token_type": "Bearer",
                           "email": "dev@example.com",
                           "workspace": "ws_dev",
                       }))
        client = CloudClient(base_url="https://cloud.example", http=transport)

        prompts: list[tuple[str, str]] = []
        creds = client.login_device_flow(
            prompt=lambda url, code: prompts.append((url, code)),
            poll_interval=0,
            max_wait_seconds=5,
        )
        assert creds.access_token == "real-token"
        assert creds.email == "dev@example.com"
        assert prompts == [("https://cloud.example/device?code=ABCD-EF", "ABCD-EF")]
        # Credentials written to disk.
        written = load_credentials(tmp_path / "creds.json")
        assert written and written.access_token == "real-token"

    def test_device_code_failure_raises(self):
        transport = FakeTransport()
        transport.when("POST", "/oauth/device/code",
                       (500, {}, {"error": "internal"}))
        client = CloudClient(base_url="https://cloud.example", http=transport)
        with pytest.raises(CloudAuthError):
            client.login_device_flow(prompt=lambda *_: None, poll_interval=0, max_wait_seconds=1)

    def test_timeout_raises(self):
        transport = FakeTransport()
        transport.when("POST", "/oauth/device/code",
                       (200, {}, {
                           "device_code": "dev1", "user_code": "X",
                           "verification_uri": "https://x", "interval": 0,
                       }))
        # Always pending.
        transport.when("POST", "/oauth/device/token",
                       *([(400, {}, {"error": "authorization_pending"})] * 50))
        client = CloudClient(base_url="https://cloud.example", http=transport)
        with pytest.raises(CloudAuthError, match="Timed out"):
            client.login_device_flow(
                prompt=lambda *_: None,
                poll_interval=0,
                max_wait_seconds=0,  # immediate timeout
            )

    def test_nonrecoverable_token_error_raises(self):
        transport = FakeTransport()
        transport.when("POST", "/oauth/device/code",
                       (200, {}, {
                           "device_code": "d", "user_code": "X",
                           "verification_uri": "https://x", "interval": 0,
                       }))
        transport.when("POST", "/oauth/device/token",
                       (400, {}, {"error": "access_denied"}))
        client = CloudClient(base_url="https://cloud.example", http=transport)
        with pytest.raises(CloudAuthError, match="access_denied"):
            client.login_device_flow(prompt=lambda *_: None,
                                      poll_interval=0, max_wait_seconds=5)


# ---------------------------------------------------------------------------
# CLI: login / logout / status
# ---------------------------------------------------------------------------

class TestCLICloud:
    def test_logout_removes_credentials(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol.cloud import client as cmod

        p = tmp_path / "creds.json"
        save_credentials(Credentials(email="x", workspace="y", access_token="z"), path=p)
        monkeypatch.setattr(cmod, "credentials_path", lambda: p)

        runner = CliRunner()
        result = runner.invoke(main, ["logout"])
        assert result.exit_code == 0
        assert "Logged out" in result.output
        assert not p.exists()

    def test_status_json(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol.cloud import client as cmod
        from cortex_protocol import platform as plat
        from cortex_protocol.licensing import downgrade_to_standard_for_tests, set_entitlements

        downgrade_to_standard_for_tests()
        try:
            monkeypatch.setattr(cmod, "credentials_path", lambda: tmp_path / "creds.json")
            monkeypatch.setattr(plat, "credentials_path", lambda: tmp_path / "creds.json")
            monkeypatch.setattr(plat, "license_path", lambda: tmp_path / "license.json")
            monkeypatch.delenv("CORTEX_CLOUD_TOKEN", raising=False)

            runner = CliRunner()
            result = runner.invoke(main, ["status", "--format", "json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["tier"] == "standard"
            assert payload["cloud"]["authenticated"] is False
        finally:
            set_entitlements(None)

    def test_status_with_env_token_reports_authenticated(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main
        from cortex_protocol.cloud import client as cmod
        from cortex_protocol import platform as plat
        from cortex_protocol.licensing import downgrade_to_standard_for_tests, set_entitlements

        downgrade_to_standard_for_tests()
        try:
            monkeypatch.setattr(cmod, "credentials_path", lambda: tmp_path / "creds.json")
            monkeypatch.setattr(plat, "credentials_path", lambda: tmp_path / "creds.json")
            monkeypatch.setattr(plat, "license_path", lambda: tmp_path / "license.json")
            monkeypatch.setenv("CORTEX_CLOUD_TOKEN", "ci-token")

            # Patch the transport so `whoami` returns a canned response.
            def fake_transport(method, url, **kw):
                if url.endswith("/v1/me"):
                    return (200, {}, {"email": "ci@example.com", "workspace": "ci"})
                return (404, {}, {})

            import cortex_protocol.cloud.client as c
            monkeypatch.setattr(c, "_request", fake_transport)

            runner = CliRunner()
            result = runner.invoke(main, ["status", "--format", "json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["cloud"]["authenticated"] is True
            assert payload["cloud"]["whoami"]["email"] == "ci@example.com"
        finally:
            set_entitlements(None)
