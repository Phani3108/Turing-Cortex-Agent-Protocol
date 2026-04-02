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

Teams running multiple frameworks **maintain duplicate specifications**. Change a policy in one place, forget to update the others.

## 💡 The Solution

One spec. Five targets. Zero duplication.

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
  temperature: 0.2
```

```bash
cortex-protocol compile agent.yaml --target all --output ./build
```

That's it. Five runtime targets generated.

---

## 🚀 Quick Start

```bash
# Install
pip install -e ".[dev]"

# Create an example agent spec
cortex-protocol init agent.yaml

# Validate it
cortex-protocol validate agent.yaml

# Compile to all targets
cortex-protocol compile agent.yaml --target all --output ./build

# Or compile to a single target
cortex-protocol compile agent.yaml --target openai-sdk --output ./build
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
| 🌐 `all` | Everything above, organized by target | One folder per target |

Every target includes **test stubs** and a **requirements.txt** — ready to install and run.

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
├── cli.py              # Click CLI (init, validate, compile, list-targets)
└── targets/
    ├── base.py             # Abstract CompilationTarget
    ├── system_prompt.py    # Universal prompt generator
    ├── openai_sdk.py       # OpenAI Agent SDK
    ├── claude_sdk.py       # Anthropic Claude SDK
    ├── crewai.py           # CrewAI YAML + scaffold
    └── langgraph.py        # LangGraph StateGraph
```

---

## ✅ Tests

```bash
# Run the full suite
pytest tests/ -v

# 71 tests covering:
#   - Schema validation & round-trip (YAML → Pydantic → JSON → Pydantic)
#   - Model family detection (Claude, GPT, Gemini, o-series, Llama, DeepSeek, Mistral)
#   - Per-target compilation (all 5 targets × 2 fixture specs)
#   - Generated code syntax verification (ast.parse on all Python output)
#   - Policy propagation (forbidden_actions, require_approval, escalation)
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
| `cortex-protocol compile <file> -t <target> -o <dir>` | Compile to a target runtime |
| `cortex-protocol compile <file> -t all -o <dir>` | Compile to all 5 targets |
| `cortex-protocol list-targets` | Show available compilation targets |
| `cortex-protocol --version` | Show version |

---

## 📄 License

MIT — [Phani Marupaka](https://linkedin.com/in/phani-marupaka)
