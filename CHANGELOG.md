# Changelog

All notable changes to Turing (Cortex Protocol) land here. Format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased / 0.6.0.dev] — Platform moat

### Added

- **PII redaction engine** (`cortex_protocol/governance/redaction/`).
  Regex-based `RedactionPipeline` + prebuilt packs for GDPR, HIPAA,
  PCI, and common API secrets. `RedactingExporter` plugs into
  `AuditLog(exporters=[...])` to sanitize downstream sinks; a
  `RedactingAuditLog` wrapper sanitizes the persisted JSONL too.
- **Supply-chain manifest / SBOM** (`cortex_protocol/supply_chain/`).
  `compile --manifest manifest.json [--signing-key ...]` emits a
  JSON manifest pinning Turing version, agent spec hash, every
  declared tool + MCP package, model IDs, and sha256 of each output
  file. `manifest-verify` re-hashes outputs and checks the Ed25519
  signature.
- **Deterministic replay** (`cortex_protocol/governance/replay.py`).
  Re-decides every historical `tool_call` event against the current
  spec and reports `newly_blocked` / `newly_allowed` / `unchanged`.
  New CLI: `replay <spec> <audit.jsonl> [--fail-on-regression]`.
- **Simulation / red-team harness** (`cortex_protocol/simulate/`).
  YAML scenario bank (bundled: prompt-injection, exfiltration,
  budget runaway) runs through `PolicyEnforcer` and scores each
  scenario PASS/FAIL. New CLI: `simulate <spec> [--scenarios DIR] [--fail-on-miss]`.
- **Policy marketplace** (`cortex_protocol/registry/marketplace.py`).
  `LocalPolicyMarketplace` stores installed packs under
  `<data_dir>/policy-packs/`; `CloudPolicyMarketplace` browses and
  publishes through Cortex Cloud (Pro). New CLI: `policy list|install|uninstall|search|publish`.
  Installed packs register as named `from_template` templates.
- **Policy-as-code DSL** (`cortex_protocol/governance/dsl/`). New
  optional `policies.rules:` block with `when/action/reason` — a
  small expression language (identifiers, literals, lists, `and`/
  `or`/`not`, comparisons, `in`, `matches`, `startswith`, etc.) that
  compiles once at spec-load time and evaluates against tool-call
  context at runtime. `action` is one of `deny` | `require_approval`
  | `allow`. Old YAML specs keep working unchanged. `RuleDenied`
  joins the blocking exception family.

### Changed

- `AuditEvent` event_type vocabulary grows `rule_allow`,
  `rule_denied`, `usage`, `budget_blocked` (prior) plus nothing new
  in-schema — all additions ride existing optional fields.
- `PolicySpec` gains `rules: list[dict]`. `merge_specs` concatenates
  base-then-override rule lists so inheritance lets child specs
  append to a base's rules without clobbering.
- `compile --manifest` + `--signing-key` flags on the existing
  `compile` command; no breaking change to callers that don't use
  them.

---

## [0.5.0.dev] — Cortex Cloud + signed audit

### Added

- **Licensing (Pro/Enterprise gate).** New `cortex_protocol/licensing/`
  module verifies Ed25519-signed license files, exposes tier + feature
  entitlements, and ships `@requires_tier` / `@requires_feature`
  decorators. License file lives at `~/.cortex-protocol/license.json`
  (per-OS via `cortex_protocol.platform.license_path`). 14-day offline
  grace configurable via `CORTEX_LICENSE_GRACE`.
- **Signed audit chain.** `SignedAuditLog` wraps `AuditLog` with
  sha256 `prev_hash` chaining + Ed25519 signatures per event, making
  tampering cryptographically detectable. `verify_chain()` returns
  per-event findings; the new `audit-verify` CLI drives this.
- **Evidence packets.** `build_evidence_packet()` produces a signed ZIP
  with spec, audit log, drift report, compliance report, and chain
  verification — auditor-ready. `evidence-packet` + `evidence-verify`
  CLI commands. Gated on Pro tier.
- **Cortex Cloud client (`cortex_protocol/cloud/`).**
  - `CloudClient` — urllib-based HTTP client, OAuth 2.0 device-flow.
  - `CloudAuditExporter` — pluggable into `AuditLog(exporters=[...])`.
    Buffers + batches + retries with exponential backoff; falls back to
    a local JSONL file if delivery keeps failing. Silently degrades to
    no-op on Standard tier (no exception into user code).
  - `CloudRegistry` — hosted-registry adapter sibling to
    `LocalRegistry`. Same `publish` / `get` / `get_latest` /
    `list_agents` / `search` surface.
  - CLI: `login`, `logout`, `status`, `push`, `pull`.
- **New CLI surface.** `activate`, `license`, `deactivate`,
  `audit-verify`, `evidence-packet`, `evidence-verify`, `login`,
  `logout`, `status`, `push`, `pull`.
- **Tier matrix (shipping defaults).** Standard (free, local-only) /
  Pro ($20/seat/mo, hosted + dashboard + signed audit + evidence) /
  Enterprise (custom — SAML, on-prem, notarization, K8s operator).

### Changed

- `AuditEvent` schema extended with `chain_index`, `prev_hash`,
  `signature`. All three are `Optional`; legacy JSONL loads unchanged.
- `cortex_protocol` package is now branded as **Turing**; the `turing`
  CLI alias script is installed alongside `cortex-protocol`.

### Security

- The bundled license public key in
  `cortex_protocol/licensing/pubkey.py` is a **dev-line placeholder**
  and will be replaced by the real Cortex Cloud key at 0.5 GA. Any
  license signed against the dev private key will stop verifying
  after cutover. Tests and internal deployments can override via
  `CORTEX_LICENSE_PUBKEY` or `CORTEX_LICENSE_PUBKEY_PATH`.

---

## [0.4.0.dev] — Plug in anywhere

### Added

- **First-party Turing MCP server** (`cortex_protocol/mcp_server/`).
  Any MCP client (Cursor, Claude Desktop, VS Code, Windsurf) can call
  `cortex.validate_spec`, `cortex.compile`, `cortex.check_policy`,
  `cortex.audit_query`, `cortex.drift_check`,
  `cortex.compliance_report`, `cortex.list_registry`, etc. stdio and
  streamable-http transports.
- **`mcp` CLI group.** `serve`, `install`, `list`, `add`, `connect`,
  `doctor`. Top-level `connect` alias. User-registered servers at
  `~/.cortex-protocol/mcp.json`.
- **Cost governance.** New `PolicySpec.max_cost_usd`,
  `max_tokens_per_run`, `max_tool_calls_per_run`. `CostTracker` +
  `ModelPricing` with built-in Claude/GPT/Gemini prices.
  `PolicyEnforcer.record_usage(...)` surfaces `BudgetExceeded` fail-
  closed. `cost-report` CLI aggregates by agent/run/tool/model/day.
- **Cross-platform distribution.**
  - `pyproject.toml` optional extras: `[mcp]`, `[openai]`, `[claude]`,
    `[langgraph]`, `[crewai]`, `[sk]`, `[otel]`, `[enterprise]`,
    `[all]`.
  - `Dockerfile` multi-stage: `runtime` (lean) and `full` (bundled
    Node + warmed MCP cache for airgap).
  - `packaging/npm/` launcher (`npx cortex-protocol@latest`) that
    bootstraps a Python venv on first run.
  - `packaging/homebrew/cortex-protocol.rb` formula scaffold.
  - `.github/workflows/{ci,release,docker}.yml` and a composite action
    at `.github/actions/cortex-protocol-action/` for downstream
    consumers.
- **Quickstart.** `init --interactive` walks through pack selection,
  tags, and cost cap; `compile --run` dry-runs the compiled agent
  through `PolicyEnforcer` so you see enforcement in action before
  wiring in a real model.
- **Cross-OS helper.** `cortex_protocol.platform` resolves per-OS
  config/data/cache dirs (XDG / Application Support / APPDATA) and
  known MCP client config paths.

### Changed

- `AuditEvent` gained cost fields (`model`, `input_tokens`,
  `output_tokens`, `cost_usd`, `run_cost_usd`). Backward-compatible.
- `PolicyEnforcer` records tool-call counts via
  `CostTracker.record_tool_call` at call time (previously implicit).

---

## [0.3.0] — 2026-03 baseline

- Initial public surface: spec schema, compilation to 6 targets,
  `PolicyEnforcer`, `AuditLog`, compliance reports, drift detection,
  fleet reporting, MCP client registry, A2A card + server scaffolds.
