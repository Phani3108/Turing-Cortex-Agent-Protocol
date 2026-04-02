"""Tests for the built-in pack registry."""

import tempfile
from pathlib import Path

import pytest
import yaml

from cortex_protocol.packs import (
    PACK_REGISTRY,
    install_pack,
    get_pack_spec_content,
)
from cortex_protocol.models import AgentSpec


class TestPackRegistry:
    def test_registry_has_three_packs(self):
        assert len(PACK_REGISTRY) == 3

    def test_pack_names_are_unique(self):
        names = [p["name"] for p in PACK_REGISTRY]
        assert len(names) == len(set(names))

    def test_each_pack_has_required_fields(self):
        for pack in PACK_REGISTRY:
            assert "name" in pack
            assert "description" in pack
            assert "agents" in pack
            assert "tags" in pack

    def test_known_pack_names(self):
        names = {p["name"] for p in PACK_REGISTRY}
        assert "incident-response" in names
        assert "customer-support" in names
        assert "code-review" in names


class TestInstallPack:
    def test_install_unknown_pack_returns_none(self, tmp_path):
        result = install_pack("nonexistent-pack", tmp_path)
        assert result is None

    def test_install_incident_response(self, tmp_path):
        files = install_pack("incident-response", tmp_path)
        assert files is not None
        assert len(files) > 0

    def test_install_creates_yaml_files(self, tmp_path):
        files = install_pack("customer-support", tmp_path)
        for fname in files:
            assert (tmp_path / fname).exists()

    def test_install_all_packs(self, tmp_path):
        for pack in PACK_REGISTRY:
            pack_dir = tmp_path / pack["name"]
            files = install_pack(pack["name"], pack_dir)
            assert files is not None
            assert len(files) > 0


class TestPackSpecValidity:
    """Installed specs must be valid Cortex Protocol agent specs."""

    def test_incident_response_spec_is_valid(self):
        content = get_pack_spec_content("incident-response", "incident-commander.yaml")
        assert content is not None
        spec = AgentSpec.from_yaml_str(content)
        assert spec.agent.name == "incident-commander"
        assert len(spec.tools) > 0
        assert spec.policies is not None

    def test_customer_support_spec_is_valid(self):
        content = get_pack_spec_content("customer-support", "support-agent.yaml")
        assert content is not None
        spec = AgentSpec.from_yaml_str(content)
        assert spec.agent.name == "support-agent"

    def test_code_review_spec_is_valid(self):
        content = get_pack_spec_content("code-review", "code-reviewer.yaml")
        assert content is not None
        spec = AgentSpec.from_yaml_str(content)
        assert spec.agent.name == "code-reviewer"

    def test_all_pack_specs_parse_as_valid_yaml(self):
        for pack in PACK_REGISTRY:
            pack_name = pack["name"]
            for agent in pack["agents"]:
                content = get_pack_spec_content(pack_name, f"{agent}.yaml")
                assert content is not None, f"No content for {pack_name}/{agent}"
                data = yaml.safe_load(content)
                assert "version" in data
                assert "agent" in data

    def test_all_pack_specs_have_policies(self):
        for pack in PACK_REGISTRY:
            for agent in pack["agents"]:
                content = get_pack_spec_content(pack["name"], f"{agent}.yaml")
                spec = AgentSpec.from_yaml_str(content)
                assert spec.policies is not None
                # All built-in packs should have forbidden actions
                assert len(spec.policies.forbidden_actions) > 0

    def test_all_pack_specs_have_model_fallback(self):
        for pack in PACK_REGISTRY:
            for agent in pack["agents"]:
                content = get_pack_spec_content(pack["name"], f"{agent}.yaml")
                spec = AgentSpec.from_yaml_str(content)
                assert spec.model is not None
                assert spec.model.fallback is not None, (
                    f"{pack['name']}/{agent} missing model.fallback"
                )

    def test_incident_response_requires_pager_approval(self):
        content = get_pack_spec_content("incident-response", "incident-commander.yaml")
        spec = AgentSpec.from_yaml_str(content)
        assert "pager" in spec.policies.require_approval

    def test_customer_support_has_refund_approval(self):
        content = get_pack_spec_content("customer-support", "support-agent.yaml")
        spec = AgentSpec.from_yaml_str(content)
        assert "process-refund" in spec.policies.require_approval


class TestGetPackSpecContent:
    def test_returns_none_for_unknown_pack(self):
        assert get_pack_spec_content("nonexistent", "agent.yaml") is None

    def test_returns_none_for_unknown_agent(self):
        assert get_pack_spec_content("incident-response", "nonexistent.yaml") is None

    def test_returns_string_content(self):
        content = get_pack_spec_content("code-review", "code-reviewer.yaml")
        assert isinstance(content, str)
        assert len(content) > 100
