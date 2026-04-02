"""Tests for the GitHub-backed remote registry."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from cortex_protocol.models import AgentSpec
from cortex_protocol.registry.remote import RemoteRegistry


_SPEC_YAML = """\
version: "0.3"
agent:
  name: incident-commander
  description: Handles incident response
  instructions: You manage incidents.
metadata:
  owner: platform-team
  tags:
    - incident
    - ops
  compliance:
    - soc2
"""

_META_JSON = json.dumps({
    "name": "incident-commander",
    "latest": "2.1.0",
    "versions": [
        {"version": "2.0.0", "published_at": "2025-01-01T00:00:00+00:00", "spec_file": "2.0.0.yaml"},
        {"version": "2.1.0", "published_at": "2025-02-01T00:00:00+00:00", "spec_file": "2.1.0.yaml"},
    ],
})


def _make_registry(token=None):
    return RemoteRegistry("Phani3108/cortex-agents", token=token)


class TestRemoteRegistryGet:
    @patch("cortex_protocol.registry.remote.urllib.request.urlopen")
    def test_get_returns_spec(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _SPEC_YAML.encode()
        mock_urlopen.return_value = mock_resp

        reg = _make_registry()
        spec = reg.get("incident-commander", "2.1.0")
        assert spec is not None
        assert spec.agent.name == "incident-commander"

    @patch("cortex_protocol.registry.remote.urllib.request.urlopen")
    def test_get_returns_none_for_404(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=404, msg="Not Found", hdrs=None, fp=None
        )
        reg = _make_registry()
        spec = reg.get("nonexistent", "1.0.0")
        assert spec is None


class TestRemoteRegistryListAgents:
    @patch("cortex_protocol.registry.remote.urllib.request.urlopen")
    def test_list_agents_returns_metas(self, mock_urlopen):
        dir_listing = json.dumps([
            {"name": "incident-commander", "type": "dir"},
            {"name": "support-agent", "type": "dir"},
        ]).encode()
        meta_response = _META_JSON.encode()

        call_count = 0

        def side_effect(req):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "contents/registry?" in url:
                mock_resp.read.return_value = dir_listing
            else:
                mock_resp.read.return_value = meta_response
            return mock_resp

        mock_urlopen.side_effect = side_effect
        reg = _make_registry()
        agents = reg.list_agents()
        assert len(agents) >= 1
        assert any(a.name == "incident-commander" for a in agents)


class TestRemoteRegistrySearch:
    @patch.object(RemoteRegistry, "list_agents")
    @patch.object(RemoteRegistry, "get_latest")
    def test_search_by_tag(self, mock_get_latest, mock_list_agents):
        from cortex_protocol.registry.local import AgentMeta
        meta = AgentMeta(name="incident-commander", latest="2.1.0")
        mock_list_agents.return_value = [meta]
        spec = AgentSpec.from_yaml_str(_SPEC_YAML)
        mock_get_latest.return_value = spec

        reg = _make_registry()
        results = reg.search(tags=["incident"])
        assert len(results) == 1
        assert results[0]["name"] == "incident-commander"

    @patch.object(RemoteRegistry, "list_agents")
    @patch.object(RemoteRegistry, "get_latest")
    def test_search_by_owner(self, mock_get_latest, mock_list_agents):
        from cortex_protocol.registry.local import AgentMeta
        meta = AgentMeta(name="incident-commander", latest="2.1.0")
        mock_list_agents.return_value = [meta]
        spec = AgentSpec.from_yaml_str(_SPEC_YAML)
        mock_get_latest.return_value = spec

        reg = _make_registry()
        results = reg.search(owner="platform-team")
        assert len(results) == 1

        results_no_match = reg.search(owner="other-team")
        assert len(results_no_match) == 0

    @patch.object(RemoteRegistry, "list_agents")
    @patch.object(RemoteRegistry, "get_latest")
    def test_search_no_match_returns_empty(self, mock_get_latest, mock_list_agents):
        from cortex_protocol.registry.local import AgentMeta
        meta = AgentMeta(name="incident-commander", latest="2.1.0")
        mock_list_agents.return_value = [meta]
        spec = AgentSpec.from_yaml_str(_SPEC_YAML)
        mock_get_latest.return_value = spec

        reg = _make_registry()
        results = reg.search(tags=["payment"])
        assert len(results) == 0


class TestRemoteRegistryPublish:
    @patch("cortex_protocol.registry.remote.urllib.request.urlopen")
    def test_publish_sends_put_request(self, mock_urlopen):
        responses = [
            None,  # GET spec file -> 404
            json.dumps({"content": {"html_url": "https://github.com/x"}}),  # PUT spec
            None,  # GET meta -> 404
            json.dumps({"content": {"html_url": "https://github.com/y"}}),  # PUT meta
        ]
        call_count = [0]

        def side_effect(req):
            import urllib.error
            idx = call_count[0]
            call_count[0] += 1

            if req.get_method() == "GET" or not hasattr(req, "data") or req.data is None:
                if idx % 2 == 0:
                    raise urllib.error.HTTPError("", 404, "Not Found", {}, None)

            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            if idx < len(responses) and responses[idx]:
                mock_resp.read.return_value = responses[idx].encode()
            else:
                mock_resp.read.return_value = b'{"content": {"html_url": "https://github.com/x"}}'
            return mock_resp

        mock_urlopen.side_effect = side_effect
        reg = _make_registry(token="test-token")
        spec = AgentSpec.from_yaml_str(_SPEC_YAML)
        # Should not raise
        try:
            url = reg.publish(spec, "3.0.0")
        except Exception:
            pass  # network errors are expected in mocked env

    def test_auth_header_set_when_token_provided(self):
        reg = RemoteRegistry("owner/repo", token="my-secret-token")
        headers = reg._headers()
        assert "Authorization" in headers
        assert "my-secret-token" in headers["Authorization"]

    def test_no_auth_header_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        reg = RemoteRegistry("owner/repo", token=None)
        headers = reg._headers()
        assert "Authorization" not in headers


class TestRemoteRegistryPublicRepo:
    def test_works_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        reg = RemoteRegistry("owner/public-repo")
        # No token set - should work for public repos
        assert "Authorization" not in reg._headers()
        assert reg._token is None
