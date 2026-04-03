# 🧠 Cortex Protocol

> **The governance layer for enterprise AI agents.**
> Define once. Enforce everywhere. Audit everything.

Stop guessing what your agents are doing in production. Cortex Protocol wraps any agent - in any framework - with policy enforcement, an immutable audit trail, and compliance reporting that satisfies your auditors.

[![Tests](https://img.shields.io/badge/tests-510%20passing-brightgreen)](https://github.com/Phani3108/Turing-Cortex-Agent-Protocol)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.3.0-orange)](https://github.com/Phani3108/Turing-Cortex-Agent-Protocol)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## ❓ The Problem

Your auditor asks: *"Which agents can access payment systems, who approved them, and what changed last week?"*

Today that answer is scattered across 6 repos, 4 frameworks, and 12 team Slack threads. Cortex Protocol makes it a 10-second CLI command.

---

## ⚡ Quickstart

```bash
pip install cortex-protocol

# 1. Define your agent
cortex-protocol init agent.yaml

# 2. Validate + lint for governance quality
cortex-protocol validate agent.yaml
cortex-protocol lint agent.yaml

# 3. Compile to your framework
cortex-protocol compile agent.yaml --target openai-sdk --output ./out

# 4. Wrap any existing agent with enforcement
```

```python
from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.enforcer import PolicyEnforcer

spec = AgentSpec.from_yaml("agent.yaml")
enforcer = PolicyEnforcer(spec)

# Blocks gated tools, checks forbidden actions, logs everything
enforcer.check_tool_call("process-refund", {"amount": 500})
enforcer.increment_turn()
```

---

## 🏛️ Three Pillars

### 🪪 Identity - *What is this agent?*
- Versioned YAML spec with name, tools, policies, model config
- Publish to local or GitHub-backed registry with semver
- `extends:` inheritance - child specs override base specs (multi-level, cycle-detected)
- `from_template:` policy presets - mix and compose across standards

### 🛡️ Governance - *What can it do, and did it comply?*
- Runtime enforcement with fail-closed semantics
- Approval gates, forbidden action checks, turn limits
- Immutable JSONL audit trail - every decision logged
- SOC2 / HIPAA / PCI-DSS compliance reports with real control IDs

### 🌐 Network - *How does it connect?*
- MCP (Model Context Protocol) wiring in all 6 compilation targets
- A2A (Agent-to-Agent) agent cards and server handlers
- Multi-agent network specs with route validation
- Shared policies across agent fleets

---

## 🔐 Runtime Enforcement

```python
from cortex_protocol.governance import PolicyEnforcer, enforce
from cortex_protocol.governance.approval import webhook_handler, allowlist_handler

# Simple one-liner wrap
safe_agent = enforce(my_agent_fn, "agent.yaml", audit_dir="./logs")
result = safe_agent("Process this refund")

# Full control with approval delegation
enforcer = PolicyEnforcer(
    spec,
    approval_handler=webhook_handler(
        url="https://hooks.slack.com/services/...",
        on_error="deny",   # fail-closed
    ),
    strict_forbidden=True,
)

# Async support
await enforcer.async_check_tool_call("delete-user", {"user_id": "123"})
```

**Pattern matching in approval gates:**
```yaml
policies:
  require_approval:
    - "*"             # all tools
    - "db-*"          # glob: any db- prefixed tool
    - "/^delete-.*/"  # regex
    - "send-email"    # exact
```

---

## 📋 Policy Templates

```yaml
policies:
  from_template: ["read-only", "payment-safe"]  # compose multiple
  forbidden_actions:
    - "access admin"   # merged on top of template
```

**Built-in templates:**
- 🔒 `strict` - all tools require approval, broad forbidden actions
- 👁️ `read-only` - blocks all write/delete/create operations
- 💳 `payment-safe` - gates payment tools, prevents PII sharing
- 🏥 `hipaa` - gates patient data access, prevents PHI leaks
- ⚡ `minimal` - high turn limit, no restrictions

```python
from cortex_protocol.governance.templates import register_template

# Register org-specific templates
register_template("my-org-standard", PolicySpec(
    max_turns=15,
    require_approval=["external-api-call"],
    forbidden_actions=["log credentials"],
))
```

---

## 📊 Compliance Reporting

```bash
# Real SOC2 control IDs with PASS/FAIL
cortex-protocol compliance-report audit.jsonl --standard soc2

# HIPAA 164.312 series
cortex-protocol compliance-report audit.jsonl --standard hipaa --spec agent.yaml

# PCI-DSS requirements
cortex-protocol compliance-report audit.jsonl --standard pci-dss
```

**What you get:**
- ✅ **CC6.1** Logical Access Controls - PASS (all tool events have agent identity)
- ⚠️ **CC6.2** Prior to Granting Access - PARTIAL (2 approval events detected)
- ✅ **CC7.1** Detection and Monitoring - PASS (847 audit events)
- ❌ **CC7.2** Anomaly Detection - FAIL (12 violations detected)

---

## 🔍 Drift Detection

Catch agents that violate their own spec in production:

```bash
# Compare actual behavior against spec
cortex-protocol drift-check agent.yaml ./logs/audit_agent.jsonl

# Block CI merges when compliance drops below threshold
cortex-protocol drift-check agent.yaml audit.jsonl --fail-on 0.9
```

**Detects:**
- 🔧 Tools used that aren't declared in the spec
- ⏱️ Runs that exceeded `max_turns`
- 🚫 Forbidden actions triggered in production
- 🔓 Approval-gated tools called without approval

---

## 🚢 Fleet Reporting

One report across your entire agent fleet:

```bash
cortex-protocol fleet-report ./logs/*.jsonl --standard soc2
cortex-protocol fleet-report ./logs/*.jsonl --specs-dir ./specs/  # with drift
```

**Supports:**
- 👥 Per-team grouping (`--team-map agent:team`)
- 📅 Time-range filtering (`--time-min` / `--time-max`)
- 🏆 Top violators ranked by severity
- 🗺️ SOC2 / GDPR / HIPAA / PCI-DSS fleet summaries
- 📤 Machine-readable JSON for SIEM ingestion

---

## 🔌 Framework Adapters

Drop governance into any existing agent - no rewrite required:

```python
# LangChain
from cortex_protocol.governance.adapters.langchain import GovernedRunnable
governed_chain = GovernedRunnable(my_chain, spec)
result = governed_chain.invoke("Process this request")

# LangGraph
from cortex_protocol.governance.adapters.langgraph import governed_agent_node, governed_tool_node

@governed_agent_node(spec)
def my_agent_node(state):
    ...

@governed_tool_node(spec, approval_handler=webhook_handler(url="..."))
def my_tool_node(state):
    ...

# OpenAI Agents SDK
from cortex_protocol.governance.adapters.openai_agents import cortex_guardrail
agent = Agent(name="x", guardrails=[cortex_guardrail(spec)])

# FastAPI / A2A endpoints
from cortex_protocol.governance.adapters.fastapi import GovernanceMiddleware
app.add_middleware(GovernanceMiddleware, spec=spec, audit_log=log)
```

---

## 📁 Audit Trail

```python
from cortex_protocol.governance.audit import RotatingAuditLog, AuditLog
from cortex_protocol.governance.audit_export import CallbackExporter, JsonlFileExporter

# Rotating log with auto-rotation at 10MB
log = RotatingAuditLog(
    path=Path("./logs/audit.jsonl"),
    max_bytes=10_000_000,
    backup_count=5,
)

# Fan-out to multiple destinations
log = AuditLog(
    path=Path("./logs/audit.jsonl"),
    exporters=[
        CallbackExporter(lambda e: send_to_datadog(e)),
        JsonlFileExporter(Path("./archive/audit_backup.jsonl")),
    ],
)
```

**Every event includes:**
- `timestamp`, `run_id`, `agent`, `turn`
- `event_type`: `tool_call` / `tool_blocked` / `tool_approved` / `tool_denied` / `forbidden_action` / `max_turns` / `escalation`
- `allowed: true/false`, `policy`, `detail`

---

## 🏗️ Registry

```bash
# Publish with semver
cortex-protocol publish agent.yaml --version 1.0.0

# Remote GitHub-backed registry
cortex-protocol publish agent.yaml -v 2.0.0 --remote github:MyOrg/agent-registry

# Search by metadata
cortex-protocol search --tag payment --compliance pci-dss
cortex-protocol search --owner platform-team --remote github:MyOrg/agent-registry
```

**Spec inheritance:**
```yaml
extends: "@myorg/base-payment-agent@^2.0.0"  # multi-level, cycle-detected

policies:
  from_template: payment-safe
  max_turns: 20  # override base
```

---

## ⚙️ Compile to Any Framework

```bash
cortex-protocol compile agent.yaml --target openai-sdk
cortex-protocol compile agent.yaml --target claude-sdk
cortex-protocol compile agent.yaml --target langgraph
cortex-protocol compile agent.yaml --target crewai
cortex-protocol compile agent.yaml --target semantic-kernel
cortex-protocol compile agent.yaml --target system-prompt
cortex-protocol compile agent.yaml --target all
```

- **openai-sdk** - Runnable agent.py with MCPServerStdio for MCP tools
- **claude-sdk** - Anthropic messages API with tool dispatch loop
- **langgraph** - StateGraph with ToolNode and MCP adapter support
- **crewai** - agents.yaml + tasks.yaml + crew.py with MCPTool
- **semantic-kernel** - Kernel + ChatCompletionAgent + plugin functions
- **system-prompt** - Model-family-optimized prompt (XML for Claude, numbered lists for GPT)

MCP tools are auto-wired in all generated code:
```yaml
tools:
  - name: jira
    mcp: "mcp-server-atlassian@2.1.0"  # resolved + wired at compile time
```

---

## 🔗 A2A Multi-Agent Networks

```bash
# Compile a multi-agent network
cortex-protocol compile-network network.yaml --target langgraph

# Generate A2A agent card + server
cortex-protocol generate-a2a agent.yaml --framework fastapi
# Serves: GET /.well-known/agent.json  POST /a2a
```

---

## 🛠️ CI/CD Integration

```bash
# Generate GitHub Actions workflow
cortex-protocol generate-ci --spec agent.yaml

# With drift detection gate (blocks merges if compliance < 90%)
cortex-protocol generate-ci --spec agent.yaml --include-drift --drift-threshold 0.9

# Generate reusable composite action (action.yml)
cortex-protocol generate-ci --composite
```

---

## 📦 All CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Create an example agent spec |
| `validate` | Validate against schema |
| `lint` | Score 0-100, grade A-F |
| `diff` | Diff two specs, flag breaking changes |
| `compile` | Compile to target runtime |
| `compile-network` | Compile multi-agent network |
| `migrate` | Migrate spec to latest schema version |
| `publish` | Publish to local or remote registry |
| `search` | Search registry by tag/owner/compliance |
| `registry-list` | List all agents in registry |
| `install` | Install a built-in agent pack |
| `list-packs` | List available packs |
| `list-targets` | List compilation targets |
| `list-templates` | List policy templates |
| `generate-ci` | Generate CI/CD workflow |
| `generate-a2a` | Generate A2A server |
| `audit` | View/summarize audit logs |
| `drift-check` | Compare behavior vs spec |
| `fleet-report` | Fleet-wide compliance report |
| `compliance-report` | SOC2 / HIPAA / PCI-DSS report |

---

## 📐 Agent Spec Reference

```yaml
version: "0.3"

agent:
  name: payment-processor
  description: Handles payment operations with full audit trail
  instructions: |
    You process payment requests. Always verify amounts.
    Never share card data. Escalate disputes over $1000.

tools:
  - name: process-payment
    description: Charge a payment method
    mcp: "mcp-server-stripe@1.0.0"   # auto-wired in compilation
    parameters:
      type: object
      properties:
        amount: { type: number }
        currency: { type: string }
      required: [amount, currency]

policies:
  from_template: payment-safe         # inherit preset
  max_turns: 10
  require_approval:
    - "process-payment"
    - "issue-refund"
    - "/^transfer-.*/"                # regex: all transfer- tools
  forbidden_actions:
    - "share card number"
    - "log credentials"
  escalation:
    trigger: "dispute over $1000"
    target: "human-agent"

model:
  preferred: claude-sonnet-4
  fallback: gpt-4o
  temperature: 0.3

metadata:
  owner: platform-team
  tags: [payment, pci-dss, sev1]
  compliance: [pci-dss, soc2]
  environment: production

extends: "@myorg/base-financial-agent@^2.0.0"
```

---

## 🏗️ Architecture

```
cortex_protocol/
├── governance/              # The moat
│   ├── enforcer.py          # PolicyEnforcer - runtime blocking
│   ├── audit.py             # AuditLog + RotatingAuditLog
│   ├── audit_export.py      # SIEM export protocol
│   ├── compliance.py        # SOC2 / HIPAA / PCI-DSS controls
│   ├── drift.py             # Spec vs behavior comparison
│   ├── fleet.py             # Cross-agent aggregation
│   ├── templates.py         # Policy presets (composable)
│   ├── approval.py          # Approval handlers (webhook, etc.)
│   └── adapters/            # LangChain, LangGraph, OpenAI, FastAPI
├── registry/                # Identity layer
│   ├── local.py             # File-based versioned storage
│   ├── remote.py            # GitHub-backed registry
│   └── resolver.py          # Semver + multi-level extends
├── targets/                 # Code generation (6 frameworks)
│   ├── openai_sdk.py
│   ├── claude_sdk.py
│   ├── langgraph.py
│   ├── crewai.py
│   ├── semantic_kernel.py
│   └── system_prompt.py
└── network/                 # Multi-agent layer
    ├── mcp.py               # MCP server registry + wiring
    ├── a2a.py               # A2A cards + handlers
    └── graph.py             # Network validation + compilation
```

---

## 📄 License

MIT - see [LICENSE](LICENSE).

Built to be the governance layer your agent fleet can't run without.
