# Cortex Protocol

> Define your AI agent once. Enforce its policies everywhere. Compile to any framework.

![Tests](https://img.shields.io/badge/tests-passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## The Problem

The auditor asks: "Which agents can access payment systems, who approved them, and what changed last week?" Today, that answer lives in six different frameworks, scattered across repos, with no shared policy layer. Cortex Protocol is the missing spec layer: one YAML file defines the agent, its tools, its governance rules, and its identity - and compiles to whatever framework your team uses.

## Quickstart (3 minutes)

```bash
pip install cortex-protocol

# 1. Create a spec
cortex-protocol init agent.yaml

# 2. Validate it
cortex-protocol validate agent.yaml

# 3. Lint for governance quality
cortex-protocol lint agent.yaml

# 4. Compile to your framework
cortex-protocol compile agent.yaml --target openai-sdk --output ./out
cortex-protocol compile agent.yaml --target all --output ./out

# 5. Enforce at runtime
```

```python
from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.enforcer import PolicyEnforcer

spec = AgentSpec.from_yaml("agent.yaml")
enforcer = PolicyEnforcer(spec)

# Wraps any callable - blocks forbidden actions, logs everything
result = enforcer.check_tool_call("delete-user", {"user_id": "123"})
```

## The Three Pillars

**Identity** - The `agent:` block defines name, description, and instructions. The spec is the single source of truth for what the agent is and what it can do. Compile once, run anywhere.

**Governance** - The `policies:` block travels with the agent. `PolicyEnforcer` wraps any tool call and enforces `forbidden_actions`, `require_approval`, `max_turns`, and escalation rules at runtime, writing every decision to an audit log.

**Network** - The `tools:` block supports MCP references (`mcp: "mcp-server-github@1.0.0"`), which compile to native MCP client code for each target. The `extends:` field enables spec inheritance from a versioned registry.

## CLI Reference

| Command | Description |
|---------|-------------|
| `init [file]` | Create an example agent spec |
| `validate <file>` | Validate spec against schema |
| `lint <file>` | Score spec 0-100, assign grade A-F |
| `diff <file-a> <file-b>` | Diff two specs, flag breaking changes |
| `compile <file> -t <target>` | Compile to target runtime (`all` for all) |
| `list-targets` | List available compilation targets |
| `list-packs` | List built-in agent packs |
| `install <pack>` | Install an agent pack |
| `publish <file> -v <ver>` | Publish spec to local registry |
| `search` | Search registry by tags/owner/compliance |
| `registry-list` | List all agents in registry |
| `audit <log>` | View runtime audit log |
| `compliance-report <log>` | Generate compliance report (SOC2/GDPR) |
| `migrate <file>` | Migrate spec to latest schema version |
| `generate-ci` | Generate GitHub Actions CI workflow |
| `compile-network <file>` | Compile multi-agent network spec |
| `generate-a2a <file>` | Generate A2A protocol server |

## Integration Examples

### Wrap a LangGraph agent with PolicyEnforcer

```python
from cortex_protocol.models import AgentSpec
from cortex_protocol.governance.enforcer import PolicyEnforcer
from cortex_protocol.governance.audit import AuditLog
from pathlib import Path

spec = AgentSpec.from_yaml("agent.yaml")
log = AuditLog(path=Path("audit.jsonl"))
enforcer = PolicyEnforcer(spec, audit_log=log)

def safe_tool_call(tool_name: str, tool_input: dict):
    result = enforcer.check_tool_call(tool_name, tool_input)
    if not result.allowed:
        raise PermissionError(result.detail)
    return your_actual_tool(tool_name, tool_input)
```

### Compile a spec to OpenAI SDK with MCP tools

```yaml
# agent.yaml
version: "0.3"
agent:
  name: github-assistant
  description: Manages GitHub issues and PRs
  instructions: You help engineers manage their GitHub workflow.

tools:
  - name: github-search
    description: Search GitHub issues and PRs
    mcp: "mcp-server-github@1.0.0"

policies:
  max_turns: 10
  require_approval:
    - github-create-pr
```

```bash
cortex-protocol compile agent.yaml --target openai-sdk --output ./out
# Generates out/agent.py with MCPServerStdio setup, mcp_servers=[] on Agent
# Generates out/requirements.txt with openai-agents[mcp]>=0.1
```

## Schema Reference

```yaml
version: "0.3"              # Schema version

agent:
  name: my-agent            # Agent identifier (used in registry, logs)
  description: "..."        # One-line description
  instructions: |           # Full system prompt source
    You are...

tools:
  - name: search            # Tool name (snake or kebab case)
    description: "..."      # What the tool does
    mcp: "mcp-server-github@1.0.0"  # Optional: MCP server reference
    parameters:
      type: object
      properties:
        query: { type: string }
      required: [query]

policies:
  max_turns: 10             # Hard turn limit
  require_approval:         # These tools need human sign-off
    - delete-record
  forbidden_actions:        # Enforcer blocks these at runtime
    - Share PII externally
  escalation:
    trigger: user requests human
    target: human-support

model:
  preferred: claude-sonnet-4
  fallback: gpt-4o
  temperature: 0.7

metadata:                   # For registry discovery
  owner: platform-team
  tags: [payment, customer-support]
  compliance: [pci-dss, soc2]
  environment: production

extends: "@org/base-agent@^2.0"  # Inherit from registry
```

## Architecture

```
                    ┌─────────────────────┐
                    │   agent.yaml (spec) │
                    │   version: "0.3"    │
                    └──────────┬──────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐    ┌───────▼──────┐   ┌───────▼──────┐
    │  IDENTITY   │    │  GOVERNANCE  │   │   NETWORK    │
    │             │    │              │   │              │
    │ - name      │    │ - policies   │   │ - MCP tools  │
    │ - desc      │    │ - enforcer   │   │ - extends    │
    │ - instruct. │    │ - audit log  │   │ - registry   │
    └──────┬──────┘    └───────┬──────┘   └───────┬──────┘
           │                   │                   │
           └───────────────────┼───────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │     compiler.py     │
                    └──────────┬──────────┘
                               │
      ┌────────┬──────────┬────┴─────┬──────────┬──────────┐
      │        │          │          │          │          │
  openai   claude    langgraph   crewai   semantic   system
   -sdk     -sdk               (yaml)    -kernel   -prompt
```

## Targets

- **openai-sdk** - Runnable agent.py with MCPServerStdio for MCP tools
- **claude-sdk** - Anthropic messages API with tool dispatch loop
- **langgraph** - StateGraph with ToolNode and MCP adapter support
- **crewai** - agents.yaml + tasks.yaml + crew.py scaffold with MCPTool
- **semantic-kernel** - Kernel + ChatCompletionAgent + plugin functions
- **system-prompt** - Model-family-optimized prompt (XML for Claude, numbered lists for GPT)

## License

MIT
