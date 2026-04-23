"""Offline red-team / simulation harness for agent specs.

Scenarios are YAML documents bundled with Turing (or user-provided) that
describe adversarial interactions a specification should survive. Each
scenario declares:

  - `id`, `name`, `category` (prompt_injection | jailbreak | exfiltration | ...)
  - `severity` (low | medium | high | critical)
  - `steps`: ordered list of tool_call / response / usage events to feed
             through a fresh `PolicyEnforcer`
  - `expected`: which policies the scenario SHOULD trigger, e.g.
                `block_tools: [refund-order]` or `forbidden_match: ["log credentials"]`

The harness loads the target spec, instantiates a `PolicyEnforcer` with
auto-deny approvals, plays each step, and scores the scenario pass/fail:

  PASS = all `expected` conditions fired (the policy caught the attack)
  FAIL = at least one expected block did not fire (the policy missed)

No model / network calls are involved — this is a pure specification
exercise. It catches policy *holes* before the agent ever hits prod.
"""

from __future__ import annotations

from .harness import (
    Scenario,
    ScenarioResult,
    ScenarioStep,
    SimulationReport,
    load_scenarios,
    run_scenarios,
)

__all__ = [
    "Scenario",
    "ScenarioResult",
    "ScenarioStep",
    "SimulationReport",
    "load_scenarios",
    "run_scenarios",
]
