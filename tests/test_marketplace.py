"""Tests for the policy pack marketplace (local + Cloud) and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cortex_protocol.licensing import (
    Tier,
    downgrade_to_standard_for_tests,
    grant_for_tests,
    set_entitlements,
)
from cortex_protocol.registry.marketplace import (
    CloudPolicyMarketplace,
    LocalPolicyMarketplace,
    PolicyPack,
)


def _pack(name="my-pack", version="1.0.0", tags=("payment",)):
    return PolicyPack(
        name=name,
        version=version,
        description="Demo pack",
        author="tester",
        tags=list(tags),
        compliance=["pci-dss"],
        policy={
            "max_turns": 10,
            "require_approval": ["process-payment"],
            "forbidden_actions": ["log card data"],
        },
    )


@pytest.fixture(autouse=True)
def _reset():
    set_entitlements(None)
    yield
    set_entitlements(None)


class TestLocalMarketplace:
    def test_install_and_get(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        path = market.install(_pack())
        assert path.exists()
        rv = market.get("my-pack")
        assert rv and rv.version == "1.0.0"

    def test_latest_semver_resolution(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack(version="1.0.0"))
        market.install(_pack(version="1.2.0"))
        market.install(_pack(version="0.9.0"))
        assert market.get("my-pack").version == "1.2.0"

    def test_list_packs(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack(name="alpha"))
        market.install(_pack(name="beta"))
        rows = market.list_packs()
        assert {r.name for r in rows} == {"alpha", "beta"}

    def test_search_by_tag(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack(name="pay", tags=["payment"]))
        market.install(_pack(name="health", tags=["phi"]))
        assert {p.name for p in market.search(tag="payment")} == {"pay"}

    def test_search_by_query_description(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        p = _pack(name="x")
        p.description = "Handles credit card flow safely"
        market.install(p)
        hits = market.search(query="credit card")
        assert hits and hits[0].name == "x"

    def test_uninstall(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack())
        assert market.uninstall("my-pack") is True
        assert market.get("my-pack") is None

    def test_as_policy_spec_roundtrip(self, tmp_path):
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack())
        pack = market.get("my-pack")
        spec = pack.as_policy_spec()
        assert spec.max_turns == 10
        assert "process-payment" in spec.require_approval

    def test_register_installed_as_templates(self, tmp_path):
        from cortex_protocol.governance.templates import get_template, unregister_template
        market = LocalPolicyMarketplace(root=tmp_path / "packs")
        market.install(_pack(name="payment-strict"))
        names = market.register_installed_packs_as_templates()
        try:
            assert "payment-strict" in names
            tmpl = get_template("payment-strict")
            assert tmpl and "process-payment" in tmpl.require_approval
        finally:
            unregister_template("payment-strict")


class TestCloudMarketplace:
    class _T:
        def __init__(self):
            self.calls = []
            self.routes = {}
        def __call__(self, method, url, *, headers=None, body=None, timeout=30.0):
            self.calls.append((method, url, body))
            for (m, suffix), r in self.routes.items():
                if m == method and url.endswith(suffix):
                    return r
            return (404, {}, {})

    def _client(self, transport):
        from cortex_protocol.cloud.client import CloudClient
        return CloudClient(base_url="https://cloud.example", token="tok",
                           http=transport)

    def test_search_builds_query(self):
        t = self._T()
        t.routes[("GET", "/packs?tag=payment")] = (200, {}, {
            "packs": [{"name": "p", "version": "1.0.0",
                        "pack_yaml": _pack("p").to_yaml()}],
        })
        mp = CloudPolicyMarketplace(self._client(t))
        results = mp.search(tag="payment")
        assert len(results) == 1 and results[0].name == "p"

    def test_get_latest(self):
        t = self._T()
        t.routes[("GET", "/packs/p/latest")] = (200, {}, {
            "pack_yaml": _pack("p").to_yaml(),
        })
        mp = CloudPolicyMarketplace(self._client(t))
        rv = mp.get("p")
        assert rv and rv.name == "p"

    def test_get_missing_returns_none(self):
        t = self._T()
        t.routes[("GET", "/packs/nope/latest")] = (404, {}, {})
        mp = CloudPolicyMarketplace(self._client(t))
        assert mp.get("nope") is None

    def test_publish(self):
        t = self._T()
        t.routes[("POST", "/packs/p/versions")] = (200, {}, {
            "url": "https://cloud.example/marketplace/p@1.0.0",
        })
        mp = CloudPolicyMarketplace(self._client(t))
        url = mp.publish(_pack("p"))
        assert url.endswith("1.0.0")


class TestPolicyCLI:
    def _patch_dir(self, monkeypatch, tmp_path):
        root = tmp_path / "data"
        # Point LocalPolicyMarketplace at the test dir by patching data_dir().
        from cortex_protocol.registry import marketplace as mod
        monkeypatch.setattr(mod, "data_dir", lambda: root)
        return root

    def test_install_from_local_file(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        self._patch_dir(monkeypatch, tmp_path)
        pack_path = tmp_path / "pack.yaml"
        pack_path.write_text(_pack().to_yaml())

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "install", str(pack_path)])
        assert result.exit_code == 0, result.output
        assert "my-pack" in result.output

        # And listing shows it.
        result2 = runner.invoke(main, ["policy", "list", "--format", "json"])
        assert result2.exit_code == 0
        rows = json.loads(result2.output)
        assert any(r["name"] == "my-pack" for r in rows)

    def test_remote_install_requires_pro(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        self._patch_dir(monkeypatch, tmp_path)
        downgrade_to_standard_for_tests()
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "install", "some-remote-pack"])
        assert result.exit_code != 0
        assert "Pro tier" in result.output

    def test_search_local(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        self._patch_dir(monkeypatch, tmp_path)
        pack_path = tmp_path / "pack.yaml"
        pack_path.write_text(_pack(tags=["payment"]).to_yaml())
        runner = CliRunner()
        runner.invoke(main, ["policy", "install", str(pack_path)])
        result = runner.invoke(main, ["policy", "search", "--tag", "payment"])
        assert result.exit_code == 0
        assert "my-pack" in result.output

    def test_uninstall(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from cortex_protocol.cli import main

        self._patch_dir(monkeypatch, tmp_path)
        pack_path = tmp_path / "pack.yaml"
        pack_path.write_text(_pack().to_yaml())
        runner = CliRunner()
        runner.invoke(main, ["policy", "install", str(pack_path)])
        result = runner.invoke(main, ["policy", "uninstall", "my-pack"])
        assert result.exit_code == 0
        assert "Removed" in result.output
