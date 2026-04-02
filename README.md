# 🧬 Cortex Protocol

**Define an agent once. Compile to any runtime.**

Cortex Protocol is a portable agent specification layer. Write a single YAML file describing your agent's identity, tools, and policies — then compile it into runnable code for the frameworks your team actually uses.

---

## 🎯 The Problem

Every agent framework defines agents differently:

| Framework | Agent Definition |
|-----------|-----------------|
| OpenAI SDK | `Agent()` + `FunctionTool` in Python |
| Claude SDK | `input_schema` tool format + agentic loop |
| CrewAI | `agents.yaml` + `tasks.yaml` |
| LangGraph | `StateGraph` + `ToolNode` + conditional edges |
| Semantic Kernel | `ChatCompletionAgent` + `@kernel_function` plugins |

Teams running multiple frameworks **maintain duplicate specifications**. Change a policy in one place, forget to update the others.

## 💡 The Solution

One spec. Six targets. Zero duplication.

```yaml
# agent.yaml — define once
version: "0.1"

agent:
  name: incident-commander
  description: Manages production incidents
  instructions: |
    Summarize impact, contact owners, escalate SEV1.

tools:
  - name: jira
    description: Create or update Jira tickets
    parameters:
      type: object
      properties:
        action: { type: string }
        summary: { type: string }
      required: [action, summary]

policies:
  max_turns: 8
  require_approval: [pager]
  forbidden_actions:
    - Resolve incidents without owner confirmation
  escalation:
    trigger: severity is SEV1
    target: vp-engineering

model:
  preferred: gpt-4o
  fallback: claude-sonnet-4
  temperature: 0.2
```

```bash
cortex-protocol compile agent.yaml --target all --output ./build
```

That's it. Six runtime targets generated.

---

## 🚀 Quick Start

```bash
# Install
pip install -e ".[dev]"

# Create an example agent spec
cortex-protocol init agent.yaml

# Validate it
cortex-protocol validate agent.yaml

# Lint governance quality (0-100 score + letter grade)
cortex-protocol lint agent.yaml

# Compile to all targets
cortex-protocol compile agent.yaml --target all --output ./build

# Install a curated starter pack
cortex-protocol install incident-response

# Generate a CI workflow (GitHub Actions)
cortex-protocol generate-ci
```

---

## 🎯 Compilation Targets

| Target | What It Generates | Files |
|--------|-------------------|-------|
| 📝 `system-prompt` | Model-optimized prompt (XML for Claude, numbered lists for GPT) | `system_prompt.md` |
| 🤖 `openai-sdk` | Runnable Python with `Agent()` + `@function_tool` decorators | `agent.py`, `test_agent.py`, `requirements.txt` |
| 🟣 `claude-sdk` | Anthropic SDK with tool definitions + agentic loop | `agent.py`, `test_agent.py`, `requirements.txt` |
| 🚢 `crewai` | CrewAI YAML configs + crew scaffold | `config/agents.yaml`, `config/tasks.yaml`, `crew.py`, `test_crew.py`, `requirements.txt` |
| 🔗 `langgraph` | StateGraph skeleton with ToolNode routing | `agent_graph.py`, `test_graph.py`, `requirements.txt` |
| 🔷 `semantic-kernel` | Microsoft Semantic Kernel — `ChatCompletionAgent` + plugin functions | `agent.py`, `test_agent.py`, `requirements.txt` |
| 🌐 `all` | Everything above, organized by target | One folder per target |

Every target includes **test stubs** and a **requirements.txt** — ready to install and run.

---

## 🛡️ Policy Linter

```bash
cortex-protocol lint agent.yaml
```

Scores your spec 0–100 and assigns a letter grade (A–F) based on **governance completeness**:

```
  Score: 85/100  Grade: B  (incident-commander)

  ✓ [ERROR]    Risky tools have no human approval gate
  ✓ [ERROR]    No forbidden_actions guardrails defined
  ✓ [WARNING]  No max_turns limit — agent can run indefinitely
  ✓ [WARNING]  No escalation path defined for failures or edge cases
  ⚠ [WARNING]  Instructions are too brief (< 30 words) to be reliable
               Instructions are 12 words — aim for 30+ for reliable behaviour
  ✗ [INFO]     No fallback model specified — outages will cause hard failures
               Add model.fallback to handle primary model outages

  1 warning(s)
```

**Rules checked:**

| Rule | Severity | Weight |
|------|----------|--------|
| `approval-gate-missing` — risky tools without human gate | ERROR | 25 |
| `no-forbidden-actions` — no guardrails defined | ERROR | 20 |
| `missing-max-turns` — agent can loop indefinitely | WARNING | 15 |
| `no-escalation-path` — no handoff defined | WARNING | 15 |
| `thin-instructions` — < 30 words | WARNING | 10 |
| `no-fallback-model` — no backup model | INFO | 10 |
| `tools-missing-required` — parameters with no required fields | WARNING | 5 |

**CI integration** — fail builds on policy violations:

```bash
# Block PRs with error-severity issues
cortex-protocol lint agent.yaml --fail-on error

# Stricter: block on warnings too
cortex-protocol lint agent.yaml --fail-on warning

# JSON output for programmatic use
cortex-protocol lint agent.yaml --format json
```

---

## 🔍 Spec Differ

Track what changed between two versions of your agent spec:

```bash
cortex-protocol diff agent-v1.yaml agent-v2.yaml
```

```
  Diff: agent-v1.yaml → agent-v2.yaml

  ⚠  Breaking changes detected

  - tool: jira                         (removed)
  + tool: linear                       (added)
  ~ tool: pager                        (parameters changed)
  ~ policy.max_turns: 8 → 12
  ~ policy.require_approval: ['pager'] → ['pager', 'send-email']
  ~ model.temperature: 0.2 → 0.3
```

Breaking changes (tool removals, policy relaxations) are flagged automatically — useful in code review to catch unintended governance regressions.

```bash
# JSON output for diff-in-CI tooling
cortex-protocol diff v1.yaml v2.yaml --format json
```

---

## 📦 Agent Packs

Install curated, ready-to-use agent specs from the built-in registry:

```bash
# See what's available
cortex-protocol list-packs

# Install a pack
cortex-protocol install incident-response
cortex-protocol install customer-support
cortex-protocol install code-review
```

Each pack is a fully-specified agent with:
- Complete tool definitions with parameter schemas
- Governance policies (approval gates, forbidden actions, escalation)
- Model preferences with fallbacks
- Ready to compile to any target

**Available packs:**

| Pack | Description | Agents |
|------|-------------|--------|
| `incident-response` | Production incident command — triage, page, escalate SEV1 | `incident-commander` |
| `customer-support` | Multi-tier support — lookup, refund, escalate to human | `support-agent` |
| `code-review` | Automated code review — lint, coverage, policy check | `code-reviewer` |

---

## ⚙️ GitHub Actions CI

Generate a CI workflow that validates, lints, and compiles your spec on every PR:

```bash
cortex-protocol generate-ci
```

The generated `.github/workflows/cortex-protocol.yml`:
- ✅ Validates spec schema on every PR
- 🛡️ Lints governance score (fails on errors by default)
- 🔨 Compiles to all 6 targets as a dry-run verification
- 💬 Posts a governance score comment on the PR

```
## 🟢 Cortex Protocol — Governance Score: 90/100 (Grade: A)

| Status | Rule | Severity | Message |
|--------|------|----------|---------|
| ✓ | approval-gate-missing | error | Risky tools have no human approval gate |
| ✓ | no-forbidden-actions | error | No forbidden_actions guardrails defined |
...
```

---

## 🧠 Model-Family-Aware Compilation

The system prompt target formats differently based on the model family (ported from [Cortex](https://github.com/Phani3108/Cortex)):

**Claude** → XML tags (what Claude responds best to):
```xml
<identity>
- You are incident-commander.
- Manages production incidents
</identity>

<policies>
- The following tools require human approval: pager
- You must NEVER: Resolve incidents without owner confirmation
</policies>
```

**GPT** → Numbered markdown (what GPT responds best to):
```markdown
## Identity

1. You are incident-commander.
2. Manages production incidents

## Policies

1. The following tools require human approval: pager
2. You must NEVER: Resolve incidents without owner confirmation
```

**Reasoning models (o3, o4)** → Minimal flat constraints
**Open source (Llama, DeepSeek)** → Explicit, repeated instructions

```bash
# Override model for prompt formatting
cortex-protocol compile agent.yaml --target system-prompt --model claude-sonnet-4
cortex-protocol compile agent.yaml --target system-prompt --model gpt-4o
```

---

## 📋 Spec Schema (v0.1)

```yaml
version: "0.1"

agent:
  name: string              # Agent identifier
  description: string       # What this agent does
  instructions: |           # Core behavioral prompt
    Multi-line markdown.

tools:
  - name: string            # Tool identifier
    description: string     # What the tool does
    parameters:             # JSON Schema for inputs
      type: object
      properties: { ... }
      required: [ ... ]

policies:
  max_turns: integer        # Max turns before escalation
  require_approval:         # Tools needing human approval
    - tool_name
  forbidden_actions:        # Things the agent must never do
    - string
  escalation:
    trigger: string         # When to hand off
    target: string          # Who to escalate to

model:
  preferred: string         # e.g. "claude-sonnet-4"
  fallback: string          # e.g. "gpt-4o"
  temperature: float        # 0.0 – 2.0
```

---

## 🏗️ Architecture

```
cortex_protocol/
├── models.py           # Pydantic v2 schema (AgentSpec, ToolSpec, PolicySpec)
├── validator.py        # Schema + semantic validation
├── compiler.py         # Model-family-aware prompt formatting
├── model_families.py   # Regex-based model detection (10 families)
├── linter.py           # Policy linter (7 rules, 0-100 scoring)
├── differ.py           # Spec diff engine (tools, policies, model)
├── registry.py         # Built-in pack registry (3 curated packs)
├── ci.py               # GitHub Actions workflow generator
├── cli.py              # Click CLI (init, validate, compile, lint, diff, list-targets, list-packs, install, generate-ci)
└── targets/
    ├── base.py             # Abstract CompilationTarget
    ├── system_prompt.py    # Universal prompt generator
    ├── openai_sdk.py       # OpenAI Agent SDK
    ├── claude_sdk.py       # Anthropic Claude SDK
    ├── crewai.py           # CrewAI YAML + scaffold
    ├── langgraph.py        # LangGraph StateGraph
    └── semantic_kernel.py  # Microsoft Semantic Kernel
```

---

## ✅ Tests

```bash
# Run the full suite
pytest tests/ -v

# 169 tests covering:
#   - Schema validation & round-trip (YAML → Pydantic → JSON → Pydantic)
#   - Model family detection (Claude, GPT, Gemini, o-series, Llama, DeepSeek, Mistral)
#   - Per-target compilation (all 6 targets × 2 fixture specs)
#   - Generated code syntax verification (ast.parse on all Python output)
#   - Policy linter (7 rules, scoring, grading)
#   - Spec differ (tools, policies, model, identity changes)
#   - Pack registry (3 packs, validity, install)
#   - CI workflow generator (YAML validity, step verification)
```

---

## 🔗 How It Fits

| Layer | Project | What It Does |
|-------|---------|-------------|
| 🔌 Tool connectivity | **MCP** | Standardizes how agents connect to tools |
| 📝 Coding tool config | **[Cortex](https://github.com/Phani3108/Cortex)** | Portable config for AI coding tools (9 providers) |
| 🧬 Agent specification | **Cortex Protocol** ← you are here | Portable agent definition + governance |

> *MCP standardizes how agents connect to tools.*
> *Cortex Protocol standardizes how agents are defined and governed.*

---

## 📦 CLI Reference

| Command | Description |
|---------|-------------|
| `cortex-protocol init [file]` | Create an example agent spec |
| `cortex-protocol validate <file>` | Validate spec against schema |
| `cortex-protocol lint <file>` | Score governance quality (0-100, A-F grade) |
| `cortex-protocol lint <file> --fail-on error` | Exit 1 on errors (CI integration) |
| `cortex-protocol diff <a.yaml> <b.yaml>` | Diff two spec versions |
| `cortex-protocol compile <file> -t <target> -o <dir>` | Compile to a target runtime |
| `cortex-protocol compile <file> -t all -o <dir>` | Compile to all 6 targets |
| `cortex-protocol list-targets` | Show available compilation targets |
| `cortex-protocol list-packs` | Show available agent packs |
| `cortex-protocol install <pack>` | Install a curated agent pack |
| `cortex-protocol generate-ci` | Generate GitHub Actions workflow |
| `cortex-protocol --version` | Show version |

---

## 📄 License

MIT — [Phani Marupaka](https://linkedin.com/in/phani-marupaka)
