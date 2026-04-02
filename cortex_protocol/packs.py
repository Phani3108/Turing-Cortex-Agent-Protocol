"""
Built-in pack registry for Cortex Protocol.

Packs are curated, ready-to-use agent specs bundled with the package.
Install a pack: cortex-protocol install incident-response
List packs:     cortex-protocol list-packs

Each pack entry points to one or more YAML spec files embedded here.
The specs follow v0.1 schema and are immediately usable with `compile`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Pack definitions (metadata)
# ---------------------------------------------------------------------------

PACK_REGISTRY = [
    {
        "name": "incident-response",
        "description": "Production incident command — triage, page, escalate SEV1",
        "agents": ["incident-commander"],
        "tags": ["ops", "on-call", "reliability"],
    },
    {
        "name": "customer-support",
        "description": "Multi-tier customer support — lookup, refund, escalate to human",
        "agents": ["support-agent"],
        "tags": ["support", "cx", "helpdesk"],
    },
    {
        "name": "code-review",
        "description": "Automated code review — lint, test coverage, policy check",
        "agents": ["code-reviewer"],
        "tags": ["dev", "ci", "quality"],
    },
]

# ---------------------------------------------------------------------------
# Pack YAML content (bundled inline so no network required)
# ---------------------------------------------------------------------------

_PACKS: dict[str, dict[str, str]] = {
    "incident-response": {
        "incident-commander.yaml": """\
version: "0.1"

agent:
  name: incident-commander
  description: Manages production incidents — triage, contact owners, escalate SEV1
  instructions: |
    You are an incident commander for production systems.
    Your job is to:
    1. Summarize the incident impact clearly and quickly
    2. Identify and contact the right service owners
    3. Escalate to VP Engineering if severity is SEV1
    4. Keep a calm, professional tone — time is critical
    Always ask for confirmation before closing an incident.
    Document every action you take in the Jira ticket.

tools:
  - name: jira
    description: Create or update Jira tickets for incident tracking
    parameters:
      type: object
      properties:
        action:
          type: string
          description: "One of: create, update, close"
        summary:
          type: string
          description: Short incident summary
        severity:
          type: string
          description: "One of: SEV1, SEV2, SEV3"
      required:
        - action
        - summary

  - name: teams
    description: Send a message to a Microsoft Teams channel
    parameters:
      type: object
      properties:
        channel:
          type: string
          description: Target Teams channel name
        message:
          type: string
          description: Message body (markdown supported)
      required:
        - channel
        - message

  - name: pager
    description: Page an on-call engineer via PagerDuty
    parameters:
      type: object
      properties:
        service:
          type: string
          description: The service to page
        urgency:
          type: string
          description: "One of: high, low"
      required:
        - service

policies:
  max_turns: 8
  require_approval:
    - pager
  forbidden_actions:
    - Resolve incidents without confirmation from service owner
    - Send external communications without approval
    - Change system configuration during an active incident
  escalation:
    trigger: severity is SEV1 or incident duration exceeds 30 minutes
    target: vp-engineering

model:
  preferred: gpt-4o
  fallback: claude-sonnet-4
  temperature: 0.2
""",
    },
    "customer-support": {
        "support-agent.yaml": """\
version: "0.1"

agent:
  name: support-agent
  description: Multi-tier customer support — lookup orders, process refunds, escalate complex cases
  instructions: |
    You are a helpful customer support agent.
    Your responsibilities:
    1. Look up order and account information accurately
    2. Process refunds within your authorized limits ($150 max)
    3. Escalate complex cases or requests above your authority to a senior agent
    4. Always verify customer identity before sharing account details
    5. Be empathetic but concise — aim to resolve in under 5 exchanges
    Never make promises about delivery dates or policy exceptions.

tools:
  - name: lookup-order
    description: Look up order details by order ID or customer email
    parameters:
      type: object
      properties:
        identifier:
          type: string
          description: Order ID or customer email address
        type:
          type: string
          description: "One of: order_id, email"
      required:
        - identifier
        - type

  - name: process-refund
    description: Process a customer refund up to the authorized limit
    parameters:
      type: object
      properties:
        order_id:
          type: string
        amount:
          type: number
          description: Refund amount in USD (max 150)
        reason:
          type: string
      required:
        - order_id
        - amount
        - reason

  - name: send-email
    description: Send a follow-up email to the customer
    parameters:
      type: object
      properties:
        to:
          type: string
          description: Customer email address
        subject:
          type: string
        body:
          type: string
      required:
        - to
        - subject
        - body

policies:
  max_turns: 15
  require_approval:
    - process-refund
    - send-email
  forbidden_actions:
    - Share another customer's information
    - Process refunds above $150 without supervisor approval
    - Make promises about future product features
    - Override account security settings
  escalation:
    trigger: customer requests human agent or issue cannot be resolved in 5 turns
    target: senior-support-manager

model:
  preferred: claude-sonnet-4
  fallback: gpt-4o
  temperature: 0.3
""",
    },
    "code-review": {
        "code-reviewer.yaml": """\
version: "0.1"

agent:
  name: code-reviewer
  description: Automated code review — identifies issues, suggests improvements, checks test coverage
  instructions: |
    You are an expert code reviewer. Your job is to:
    1. Identify bugs, security vulnerabilities, and logic errors
    2. Check that test coverage is adequate for new code paths
    3. Flag violations of the project's coding standards
    4. Suggest concrete, actionable improvements
    5. Differentiate between blocking issues and suggestions
    Be constructive and specific — link to relevant docs when helpful.
    Never approve code that has security vulnerabilities or missing tests for critical paths.

tools:
  - name: lint-code
    description: Run static analysis and linting on a file or diff
    parameters:
      type: object
      properties:
        file_path:
          type: string
          description: Path to the file to lint
        language:
          type: string
          description: Programming language (python, typescript, go, etc.)
      required:
        - file_path
        - language

  - name: check-coverage
    description: Check test coverage for changed files
    parameters:
      type: object
      properties:
        file_paths:
          type: array
          items:
            type: string
          description: List of changed file paths
        threshold:
          type: number
          description: Minimum coverage percentage required (default 80)
      required:
        - file_paths

  - name: post-review-comment
    description: Post a review comment on the pull request
    parameters:
      type: object
      properties:
        severity:
          type: string
          description: "One of: blocking, warning, suggestion"
        file_path:
          type: string
        line_number:
          type: integer
        comment:
          type: string
      required:
        - severity
        - comment

  - name: approve-pr
    description: Submit a PR approval review
    parameters:
      type: object
      properties:
        summary:
          type: string
          description: Summary of the review
      required:
        - summary

policies:
  max_turns: 20
  require_approval:
    - approve-pr
  forbidden_actions:
    - Approve PRs with known security vulnerabilities
    - Approve PRs with less than 60% test coverage on new code
    - Post dismissive or personal comments
  escalation:
    trigger: security vulnerability detected or architectural decision required
    target: senior-engineer

model:
  preferred: claude-sonnet-4
  fallback: gpt-4o
  temperature: 0.1
""",
    },
}


# ---------------------------------------------------------------------------
# Install function
# ---------------------------------------------------------------------------

def install_pack(pack_name: str, output_dir: Path) -> Optional[list[str]]:
    """
    Write pack YAML files to output_dir.

    Returns list of written filenames, or None if pack not found.
    """
    if pack_name not in _PACKS:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    written = []

    for filename, content in _PACKS[pack_name].items():
        dest = output_dir / filename
        dest.write_text(content)
        written.append(filename)

    return written


def get_pack_spec_content(pack_name: str, agent_filename: str) -> Optional[str]:
    """Return the raw YAML content for a specific agent in a pack."""
    pack = _PACKS.get(pack_name)
    if not pack:
        return None
    return pack.get(agent_filename)
