# 🧠 Turing (Cortex Protocol)

> **The governance layer for enterprise AI agents.**
> Define once. Enforce everywhere. Audit everything. Prove it to auditors.

Stop guessing what your agents are doing in production. Turing wraps any
agent — in any framework — with fail-closed policy enforcement, a signed
and chained audit trail, spend caps, red-team-tested rules, and one-command
SOC2 / HIPAA / PCI-DSS evidence bundles your compliance team can hand to
an auditor.

[![Tests](https://img.shields.io/badge/tests-800%20passing-brightgreen)](https://github.com/Phani3108/Turing-Cortex-Agent-Protocol)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
[![Version](https://img.shields.io/badge/version-0.6.0--dev-orange)](https://github.com/Phani3108/Turing-Cortex-Agent-Protocol)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## ❓ The Problem

Your auditor asks: *"Which agents can access payment systems, who approved
them, what did they spend last month, and what changed in the policy last
week?"*

Today that answer is scattered across 6 repos, 4 frameworks, and 12 team
Slack threads. Turing makes it a 10-second CLI command — and the answer
is cryptographically signed.

---

## ⚡ Quickstart (3 steps, ~2 minutes)

```bash
# 1. Install (pip, pipx, npx, brew, or docker)
pipx install cortex-protocol[all]
#   or:  npx cortex-protocol@latest ...
#   or:  brew tap Phani3108/cortex && brew install cortex-protocol
#   or:  docker run -it cortex-protocol/cortex:latest

# 2. Walk through an interactive wizard, then wire Turing into your editor
cortex-protocol init --interactive
cortex-protocol connect            # merges Turing into Cursor / Claude Desktop / VS Code / Windsurf

# 3. Compile for your framework and see enforcement work end-to-end
cortex-protocol compile agent.yaml --target claude-sdk --run
```

```python
from cortex_protocol.models import AgentSpec
from cortex_protocol.governance import PolicyEnforcer, SignedAuditLog
from cortex_protocol.licensing import generate_keypair

spec = AgentSpec.from_yaml("agent.yaml")

# Signed, tamper-evident audit trail
priv, _pub = generate_keypair()             # in prod: loaded from your KMS
log = SignedAuditLog(priv, path="audit.jsonl")

enforcer = PolicyEnforcer(spec, audit_log=log)
enforcer.increment_turn()
enforcer.check_tool_call("process-refund", {"amount": 500})
enforcer.record_usage(model="claude-sonnet-4",
                      input_tokens=1_200, output_tokens=180)
```

---

## 🏛️ Three Pillars

### 🪪 Identity - *What is this agent?*
- Versioned YAML spec with name, tools, policies, model config
- Publish to local, GitHub-backed, or **Cortex Cloud** hosted registry
- `extends:` inheritance — child specs override base specs (multi-level, cycle-detected)
- `from_template:` policy presets + **policy marketplace** for shared packs

### 🛡️ Governance - *What can it do, did it comply, and can you prove it?*
- Runtime enforcement with fail-closed semantics
- Approval gates, forbidden action checks, turn limits, **per-run cost caps**
- **Policy-as-code DSL** — rules with `when`/`action`/`reason`
- **Tamper-evident audit trail** — SHA-256 chain + Ed25519 per event
- **SOC2 / HIPAA / PCI-DSS / GDPR reports** with real control IDs
- **Signed evidence packets** — one ZIP, auditor-ready
- **PII / secrets redaction** before persistence (GDPR / HIPAA / PCI packs)
- **Red-team simulation** — offline scenario runner for prompt-injection, exfil, runaway budget
- **Deterministic replay** — re-decide yesterday's events against today's policy

### 🌐 Network - *How does it connect?*
- **First-party Turing MCP server** — exposes governance tools to Cursor, Claude Desktop, VS Code, Windsurf
- MCP client wiring across all 6 compilation targets
- A2A (Agent-to-Agent) agent cards and server handlers
- Multi-agent network specs with route validation
- **Cortex Cloud** hosted registry, audit sink, Slack/PagerDuty approvals (Pro+)

### 📦 Supply chain - *What actually ran?*
- Signed **tool manifest / SBOM** per compile — tool versions, MCP server hashes, model IDs, output-file checksums
- `manifest-verify` re-hashes every file and checks the Ed25519 signature

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

## 📜 Policy-as-code DSL (0.6+)

Beyond `require_approval` lists and `forbidden_actions` substrings,
specs can declare context-aware rules in a small expression language:

```yaml
policies:
  rules:
    - when: 'tool_name matches "^delete_" and env != "staging"'
      action: require_approval
      reason: "Destructive tools need human approval outside staging"

    - when: 'run_cost_usd > 4.00'
      action: deny
      reason: "Approaching budget cap"

    - when: 'tool_input.amount > 1000 and not ("gold" in tags)'
      action: require_approval
```

Grammar: literals (numbers, strings, booleans, lists), attribute
access (`tool_input.amount`), comparisons, `and` / `or` / `not`, `in`
/ `not in`, `matches` (regex), `startswith` / `endswith` / `contains`,
`len()`, `lower()`, `upper()`, `int()`. First matching rule wins.
Rules compile once at spec-load time; parse errors fail the spec.

## 🛡️ Red-Team Simulation (0.6+)

Offline adversarial harness. Every spec should survive the bundled
scenario bank before hitting production:

```bash
cortex-protocol simulate agent.yaml --fail-on-miss
#   Simulation: 4 scenario(s)
#   passed: 4   failed: 0   (100%)
#     [PASS] (high    ) pi-001  Ignore-previous-instructions refund
#     [PASS] (medium  ) pi-002  Role-swap override
#     [PASS] (critical) ex-001  Credential exfiltration via response
#     [PASS] (high    ) ex-002  Budget runaway via recursive tool calls
```

Bring your own scenarios: `--scenarios ./adversarial/` walks a
directory of YAML files alongside the bundled pack.

## 🔁 Deterministic Replay (0.6+)

Re-decide every historical tool call against the current policy to
catch regressions before you ship a policy change:

```bash
cortex-protocol replay agent.yaml audit.jsonl --fail-on-regression
#   Replay: 847 tool events
#   Regressions: 2 (newly_blocked=2, newly_allowed=0)
#     [!] turn 12 tool=send-email  was allowed → now blocked by require_approval
```

## 🧼 PII Redaction (0.6+)

Rule-based, deterministic redactor with prebuilt GDPR/HIPAA/PCI/secrets
packs. Plug into any audit log:

```python
from cortex_protocol.governance import AuditLog, RedactingExporter, combine_packs, gdpr_pack, secrets_pack
from cortex_protocol.cloud import CloudAuditExporter

pipeline = combine_packs(gdpr_pack(), secrets_pack())
log = AuditLog(path="audit.jsonl", exporters=[
    RedactingExporter(CloudAuditExporter(client), pipeline)
])
```

## 📦 Tool Manifest / SBOM (0.6+)

Every compile can emit a signed supply-chain manifest — pinning
Turing version, agent spec hash, tool packages, model IDs, and a
sha256 of every generated file:

```bash
cortex-protocol compile agent.yaml -t claude-sdk \
  --output ./out --manifest ./manifest.json --signing-key ./signer.pem

cortex-protocol manifest-verify ./manifest.json --artifacts-dir ./out
#   Manifest: VERIFIED
#   [ok] agent.py
#   [ok] README.md
#   [ok] manifest signature verified
```

## 🏪 Policy Marketplace (0.6+)

Install community or private policy packs and reference them the same
way as built-in templates:

```bash
cortex-protocol policy search --tag payment
cortex-protocol policy install my-org-pci-strict       # from the Cloud marketplace (Pro)
cortex-protocol policy install ./packs/gdpr-retail.yaml # from a local file
cortex-protocol policy list
```

Installed packs auto-register as `policies.from_template: my-org-pci-strict`
in any downstream spec.

---

## 💰 Cost Governance (0.4+)

Enforce spend caps at runtime — the #1-asked enterprise feature ships in
the free tier.

```yaml
policies:
  max_cost_usd: 5.00            # fail-closed at $5 per run
  max_tokens_per_run: 200000    # fail-closed at 200k combined tokens
  max_tool_calls_per_run: 50    # fail-closed after 50 tool invocations
```

```python
enforcer = PolicyEnforcer(spec)
enforcer.increment_turn()
enforcer.record_usage(
    model="claude-sonnet-4",
    input_tokens=5000,
    output_tokens=500,
)
# Raises BudgetExceeded the moment a cap is breached.
```

```bash
cortex-protocol cost-report audit.jsonl --by model --format json
```

Pricing for Claude, GPT, and Gemini ships built-in; negotiated rates
override via `ModelPricing(overrides={...})`.

---

## 🧩 MCP Server — Turing inside your editor (0.4+)

Turing itself runs as an MCP server, so Cursor, Claude Desktop, VS Code,
and Windsurf can call governance tools natively.

```bash
pipx install cortex-protocol
cortex-protocol init --interactive
cortex-protocol connect && cortex-protocol compile agent.yaml --target claude-sdk --run
```

`connect` auto-detects installed MCP clients and merges the Turing
entry into each client's `mcpServers` config (preserving anything else
already there). `mcp doctor` verifies Node, the SDK, the cache, and
every detected client.

**Tools exposed to the client:**
`cortex.validate_spec`, `cortex.lint`, `cortex.compile`,
`cortex.check_policy`, `cortex.audit_query`, `cortex.drift_check`,
`cortex.compliance_report`, `cortex.fleet_report`,
`cortex.list_registry`, `cortex.install_pack`,
`cortex.list_mcp_servers`, `cortex.suggest_mcp_for_tool`.

---

## 🔏 Signed Audit Chain (0.5+ · Pro)

Tamper-evident audit logs. Each event carries a sha256 `prev_hash` and
an Ed25519 signature; `verify_chain()` localizes any break to a single
row.

```python
from cortex_protocol.governance import SignedAuditLog
from cortex_protocol.licensing import generate_keypair

priv, pub = generate_keypair()                   # in prod: loaded from KMS
log = SignedAuditLog(priv, path=Path("audit.jsonl"))
enforcer = PolicyEnforcer(spec, audit_log=log)
# ...run the agent...
```

```bash
cortex-protocol audit-verify audit.jsonl
#   Chain: VERIFIED
#   events: 847
#   [ok] index 0: turn_start  prev=GENESIS...
#   [ok] index 1: tool_call   prev=ab12cd34...
#   ...
```

## 📦 Evidence Packets (0.5+ · Pro)

One-command auditor-ready ZIP with spec, signed audit, drift, compliance
report, and a signed manifest.

```bash
cortex-protocol evidence-packet audit.jsonl agent.yaml \
  -o packet.zip --standard soc2 \
  --signing-key keys/signer.pem --public-key keys/audit.pub.pem

cortex-protocol evidence-verify packet.zip
#   Packet: VERIFIED  id: ep-7f3a91c4c6b1
```

## ☁️ Cortex Cloud (0.5+ · Pro)

Hosted registry, central audit sink, approval workflow engine (planned),
and dashboards. OSS-side integration ships now; the backend lands with
Cortex Cloud GA.

```bash
cortex-protocol login                    # OAuth device flow
cortex-protocol push agent.yaml -v 1.0.0 # to hosted registry
cortex-protocol pull payment-agent       # fetch latest version
cortex-protocol status                   # tier, workspace, connection
```

```python
from cortex_protocol.cloud import CloudClient, CloudAuditExporter
from cortex_protocol.governance import AuditLog

client = CloudClient.from_environment()
log = AuditLog(path="audit.jsonl", exporters=[CloudAuditExporter(client)])
```

The exporter batches, retries, falls back to disk on hard failure, and
silently degrades to a no-op on Standard tier so the same agent code
runs in every environment.

## 🪪 Licensing & Tiers (0.5+)

| Tier | Price | Included |
|---|---|---|
| **Standard** | Free | Local CLI, Turing MCP server, file audit logs, cost governance, community registry |
| **Pro** | $20/seat/mo | All Standard + hosted registry, Cloud audit sink (30-day), Slack approvals, Google SSO, OTel, signed audit, evidence packets, cost dashboards |
| **Enterprise** | Custom | All Pro + SAML/OIDC, on-prem deploy, RFC-3161 notarized evidence, custom compliance, private policy marketplace, K8s operator, SLA |

```bash
cortex-protocol activate ~/Downloads/my-license.json
cortex-protocol license           # show tier + features + expiry
cortex-protocol deactivate         # revert to Standard
```

License files are Ed25519-signed by Cortex Cloud, cached offline,
respect a 14-day grace window past expiry (configurable via
`CORTEX_LICENSE_GRACE`), and never hard-fail agent code — missing or
invalid licenses silently degrade to Standard.

---

## 📦 All CLI Commands

| Command | Description |
|---------|-------------|
| `init` | Create an example agent spec (`--interactive` for a wizard) |
| `validate` | Validate against schema |
| `lint` | Score 0-100, grade A-F |
| `diff` | Diff two specs, flag breaking changes |
| `compile` | Compile to target runtime (`--run` for enforcement dry-run) |
| `compile-network` | Compile multi-agent network |
| `migrate` | Migrate spec to latest schema version |
| `publish` | Publish to local or remote registry |
| `push` / `pull` | Publish / fetch to/from Cortex Cloud hosted registry (Pro) |
| `search` | Search registry by tag/owner/compliance |
| `registry-list` | List all agents in registry |
| `install` | Install a built-in agent pack |
| `list-packs` | List available packs |
| `list-targets` | List compilation targets |
| `list-templates` | List policy templates |
| `generate-ci` | Generate CI/CD workflow |
| `generate-a2a` | Generate A2A server |
| `audit` | View/summarize audit logs |
| `audit-verify` | Verify a signed audit chain |
| `drift-check` | Compare behavior vs spec |
| `fleet-report` | Fleet-wide compliance report |
| `compliance-report` | SOC2 / HIPAA / PCI-DSS report |
| `cost-report` | Aggregate token + USD spend from an audit log |
| `evidence-packet` / `evidence-verify` | Build / verify auditor-ready bundles (Pro) |
| `manifest-verify` | Verify a supply-chain manifest against compiled artifacts |
| `replay` | Re-decide historical tool calls against the current spec |
| `simulate` | Run adversarial scenarios offline against a spec |
| `policy list` / `install` / `uninstall` / `search` / `publish` | Policy pack marketplace (Pro to publish) |
| `activate` / `license` / `deactivate` | Licensing operations |
| `login` / `logout` / `status` | Cortex Cloud session management |
| `mcp serve` / `mcp install` / `mcp list` / `mcp add` / `mcp connect` / `mcp doctor` | MCP server group |
| `connect` | Alias for `mcp connect` |

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
├── governance/              # The moat — runtime enforcement + compliance
│   ├── enforcer.py          # PolicyEnforcer — runtime blocking, DSL eval
│   ├── audit.py             # AuditLog + RotatingAuditLog
│   ├── signed_audit.py      # (0.5) SignedAuditLog — prev_hash + Ed25519 chain
│   ├── evidence.py          # (0.5) Evidence packets — auditor-ready ZIPs
│   ├── audit_export.py      # SIEM export protocol
│   ├── compliance.py        # SOC2 / HIPAA / PCI-DSS controls
│   ├── cost.py              # (0.4) Cost tracker + model pricing
│   ├── drift.py             # Spec vs behavior comparison
│   ├── replay.py            # (0.6) Deterministic re-decision
│   ├── fleet.py             # Cross-agent aggregation
│   ├── templates.py         # Policy presets (composable)
│   ├── approval.py          # Approval handlers (webhook, allowlist, ...)
│   ├── dsl/                 # (0.6) Policy-as-code DSL: lexer → parser → compiler
│   ├── redaction/           # (0.6) PII + secrets redaction (GDPR/HIPAA/PCI packs)
│   └── adapters/            # LangChain, LangGraph, OpenAI, FastAPI
├── mcp_server/              # (0.4) First-party Turing MCP server
├── cloud/                   # (0.5) Cortex Cloud client — OAuth, audit sink, registry
├── licensing/               # (0.5) Ed25519 licenses + tier entitlements
├── supply_chain/            # (0.6) Signed tool manifest / SBOM
├── simulate/                # (0.6) Red-team scenario harness + bundled packs
├── registry/                # Identity layer
│   ├── local.py             # File-based versioned storage
│   ├── remote.py            # GitHub-backed registry
│   ├── resolver.py          # Semver + multi-level extends
│   └── marketplace.py       # (0.6) Policy pack marketplace (local + Cloud)
├── targets/                 # Code generation (6 frameworks)
│   ├── openai_sdk.py
│   ├── claude_sdk.py
│   ├── langgraph.py
│   ├── crewai.py
│   ├── semantic_kernel.py
│   └── system_prompt.py
├── network/                 # Multi-agent layer
│   ├── mcp.py               # External MCP server registry + wiring
│   ├── a2a.py               # A2A cards + handlers
│   └── graph.py             # Network validation + compilation
└── platform.py              # Per-OS paths + MCP client config resolution
```

## 🪪 Licensing & tiers

| Tier | Price | Included |
|---|---|---|
| **Standard** | Free | Local CLI, Turing MCP server, file audit logs, cost governance, DSL rules, red-team harness, PII redaction, policy marketplace (browse), SBOM, community registry |
| **Pro** | $20/seat/mo | All Standard + hosted registry, Cloud audit sink (30-day), Slack approvals, Google SSO, OTel export, signed audit chain, evidence packets, cost dashboards, marketplace publish |
| **Enterprise** | Custom | All Pro + SAML/OIDC, on-prem deploy, RFC-3161 notarized evidence, custom compliance, private policy marketplace, K8s operator, SLA |

```bash
cortex-protocol activate ~/Downloads/my-license.json
cortex-protocol license        # tier, features, expiry
cortex-protocol status         # tier + Cloud connection + workspace
```

---

## 📄 License

MIT — see [LICENSE](LICENSE).

The Turing engine is MIT. The Cortex Cloud service and Enterprise features
(SSO, on-prem, SLA, RFC-3161 notarization, private marketplace) are
proprietary add-ons.

Built to be the governance layer your agent fleet can't run without.
