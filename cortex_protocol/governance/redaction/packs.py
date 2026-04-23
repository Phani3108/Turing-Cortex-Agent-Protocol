"""Prebuilt redaction packs.

Pack selection maps to the compliance standard an agent targets:
  - GDPR  : emails, phone numbers, IP addresses, names (basic heuristic)
  - HIPAA : GDPR + MRN (medical record numbers), date-of-birth, SSN
  - PCI   : card numbers (Luhn-like pattern), CVV, cardholder-name tokens
  - SECRETS: common API key / token patterns (AWS, Stripe, GitHub, etc.)

Regexes are deliberately conservative — they favor precision over
recall. Missing a redaction is better than corrupting non-PII text in
audit logs. Callers with stricter requirements add custom regexes via
`RegexRedactor` + `combine_packs`.
"""

from __future__ import annotations

import re
from typing import Iterable

from .engine import RedactionPipeline, RegexRedactor


# ---------------------------------------------------------------------------
# GDPR (basic personal data)
# ---------------------------------------------------------------------------

def gdpr_pack() -> RedactionPipeline:
    return RedactionPipeline([
        RegexRedactor(
            id="email",
            pattern=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        ),
        RegexRedactor(
            id="phone",
            # International or US-style phone numbers (7-15 digits with
            # optional country code and common separators).
            pattern=r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\w)",
        ),
        RegexRedactor(
            id="ipv4",
            pattern=r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?!\d)",
        ),
        RegexRedactor(
            id="ipv6",
            pattern=r"(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}",
        ),
    ])


# ---------------------------------------------------------------------------
# HIPAA (health-specific)
# ---------------------------------------------------------------------------

def hipaa_pack() -> RedactionPipeline:
    pipeline = gdpr_pack()
    pipeline.extend([
        RegexRedactor(
            id="ssn",
            pattern=r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)",
        ),
        RegexRedactor(
            id="mrn",
            # Loose MRN: labeled or 6-12 digit identifiers immediately
            # preceded by tokens like MRN#/Patient ID.
            pattern=r"(?:MRN|mrn|Medical[\s-]?Record[\s-]?(?:Number|No\.?|#)?|Patient[\s-]?ID)\s*[:#]?\s*(\d{6,12})",
        ),
        RegexRedactor(
            id="dob",
            # Plain date patterns — used as DOB signal when in HIPAA context.
            pattern=r"(?<!\d)(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}(?!\d)",
        ),
    ])
    return pipeline


# ---------------------------------------------------------------------------
# PCI (payment card data)
# ---------------------------------------------------------------------------

def pci_pack() -> RedactionPipeline:
    return RedactionPipeline([
        RegexRedactor(
            id="card_number",
            # 13-19 digit runs with optional grouping whitespace/dashes.
            pattern=r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)",
        ),
        RegexRedactor(
            id="cvv",
            pattern=r"(?:CVV|CVC|CV2)\s*[:#]?\s*\d{3,4}\b",
            flags=re.IGNORECASE,
        ),
    ])


# ---------------------------------------------------------------------------
# Secrets (API tokens; useful everywhere)
# ---------------------------------------------------------------------------

def secrets_pack() -> RedactionPipeline:
    return RedactionPipeline([
        RegexRedactor(
            id="aws_access_key",
            pattern=r"\bAKIA[0-9A-Z]{16}\b",
        ),
        RegexRedactor(
            id="stripe_key",
            pattern=r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{24,}\b",
        ),
        RegexRedactor(
            id="github_pat",
            pattern=r"\bghp_[A-Za-z0-9]{36}\b",
        ),
        RegexRedactor(
            id="openai_key",
            pattern=r"\bsk-[A-Za-z0-9]{20,}\b",
        ),
        RegexRedactor(
            id="anthropic_key",
            pattern=r"\bsk-ant-[A-Za-z0-9\-_]{40,}\b",
        ),
        RegexRedactor(
            id="slack_token",
            pattern=r"\bxox[aboprs]-[A-Za-z0-9-]{10,}\b",
        ),
        RegexRedactor(
            id="bearer_token",
            pattern=r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}\b",
        ),
    ])


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------

def combine_packs(*packs: RedactionPipeline) -> RedactionPipeline:
    """Flatten multiple pipelines into one, preserving order + de-duping by id."""
    seen: set[str] = set()
    merged = RedactionPipeline()
    for p in packs:
        for r in p.redactors:
            if r.id in seen:
                continue
            seen.add(r.id)
            merged.add(r)
    return merged


BUILTIN_PACKS: dict[str, "callable"] = {
    "gdpr":    gdpr_pack,
    "hipaa":   hipaa_pack,
    "pci":     pci_pack,
    "secrets": secrets_pack,
}
