"""Shared test fixtures."""

from pathlib import Path

import pytest

from cortex_protocol.models import AgentSpec

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def basic_spec() -> AgentSpec:
    return AgentSpec.from_yaml(str(FIXTURES / "basic_agent.yaml"))


@pytest.fixture
def policy_spec() -> AgentSpec:
    return AgentSpec.from_yaml(str(FIXTURES / "policy_agent.yaml"))
