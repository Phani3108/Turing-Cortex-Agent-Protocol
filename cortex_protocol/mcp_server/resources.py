"""Static MCP resources exposed by the Turing MCP server.

Resources are read-only catalogs — registry contents, pack listings,
policy templates, known MCP servers, compliance reference docs. An MCP
client can `read_resource()` any of these without triggering tool calls.
"""

from __future__ import annotations

import json


def _packs() -> str:
    from ..packs import PACK_REGISTRY
    return json.dumps(list(PACK_REGISTRY), indent=2)


def _policy_templates() -> str:
    from ..governance.templates import list_templates
    return json.dumps(list_templates(), indent=2, default=str)


def _mcp_servers() -> str:
    from ..network.mcp import MCPServerRegistry

    reg = MCPServerRegistry()
    return json.dumps(
        [
            {
                "name": s.name,
                "package": s.package,
                "description": s.description,
                "transport": s.transport,
                "tools": list(s.tools),
                "env_vars": list(s.env_vars),
            }
            for s in reg.list_servers()
        ],
        indent=2,
    )


def _registry_agents() -> str:
    from ..registry.local import LocalRegistry

    reg = LocalRegistry()
    return json.dumps(
        [
            {"name": m.name, "latest": m.latest,
             "versions": [v.version for v in m.versions]}
            for m in reg.list_agents()
        ],
        indent=2,
    )


def _soc2_reference() -> str:
    return (
        "Turing maps audit events to SOC2 Trust Services Criteria "
        "CC6.1/CC6.2/CC6.3 (logical access), CC7.1/CC7.2 (detection + "
        "anomaly monitoring), and CC8.1 (change management). Use the "
        "cortex.compliance_report tool to evaluate a specific audit log."
    )


RESOURCES: dict[str, tuple[str, callable]] = {
    "cortex://packs":             ("Built-in agent packs", _packs),
    "cortex://policy-templates":  ("Built-in policy templates", _policy_templates),
    "cortex://mcp-servers":       ("Bundled MCP server catalog", _mcp_servers),
    "cortex://registry/agents":   ("Local registry agent index", _registry_agents),
    "cortex://compliance/soc2":   ("SOC2 mapping reference", _soc2_reference),
}
