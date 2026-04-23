"""Tamper-evident audit log via Ed25519 signatures + SHA-256 hash chain.

Each event the agent writes carries:
  - `chain_index`  : 0-based position in the chain
  - `prev_hash`    : sha256 of the previous event's canonical bytes (or "GENESIS")
  - `signature`    : ed25519:<urlsafe-b64-nopad> over the full event body

On verification:
  1. Every `signature` must validate against the issuer's public key.
  2. Every `prev_hash` must equal sha256 of the prior event's signed payload.
  3. Event `chain_index` values must be contiguous starting at 0.

Any failure localizes to the first broken event so auditors know exactly
which row to investigate.

Motivation: the plain `AuditLog` is append-only by filesystem permissions,
but a disk-level rewrite can swap events silently. A signed + chained log
makes any tampering detectable with cryptographic certainty — provided
the issuer's public key is trusted.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, replace
from pathlib import Path
from typing import Iterable, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..licensing.crypto import (
    canonical_json,
    sha256_hex,
    sign_payload,
    verify_signature,
)
from .audit import AuditEvent, AuditLog


GENESIS = "GENESIS"


def _event_payload_for_signing(event: AuditEvent) -> dict:
    """Canonical dict of event fields used as the signing input.

    Excludes `signature` (can't sign over its own sig). Includes every
    other field, including `chain_index` and `prev_hash`, so tampering
    with the chain breaks verification.
    """
    d = asdict(event)
    d.pop("signature", None)
    # Drop None-valued fields to keep the canonical form stable across
    # schema evolution (matches AuditEvent.to_dict()).
    return {k: v for k, v in d.items() if v is not None}


def event_hash(event: AuditEvent) -> str:
    """Hash of a signed event's body + signature — used as the next prev_hash."""
    d = asdict(event)
    # Include the signature so mutation of a signed row breaks the chain.
    d = {k: v for k, v in d.items() if v is not None}
    return sha256_hex(canonical_json(d))


class SignedAuditLog(AuditLog):
    """AuditLog variant that signs and chains every event.

    Construction:
        log = SignedAuditLog(private_key, path=Path("./audit.jsonl"))

    Events written via `log.write(event)` are stamped with chain_index,
    prev_hash, and signature before persistence. Reading an existing
    signed log back in (via `from_file`) preserves those fields but does
    NOT verify — call `verify_chain()` for that, so callers control when
    the cost is paid.
    """

    def __init__(
        self,
        private_key: Ed25519PrivateKey,
        path: Optional[Path] = None,
        exporters: Optional[list] = None,
    ):
        super().__init__(path=path, exporters=exporters)
        self._private_key = private_key
        self._last_hash = self._compute_tail_hash()

    def _compute_tail_hash(self) -> str:
        """After loading an existing file, recover the chain tail."""
        if not self._events:
            return GENESIS
        tail = self._events[-1]
        if tail.signature is None:
            # Mixed log (unsigned events present). Treat as genesis — signing
            # starts fresh. Callers shouldn't mix; we refuse to silently
            # chain over unsigned history.
            return GENESIS
        return event_hash(tail)

    @property
    def chain_length(self) -> int:
        return len(self._events)

    def write(self, event: AuditEvent) -> None:
        if event.signature is not None:
            # If the caller already signed this event (e.g. re-import),
            # treat as a plain append and trust the existing chain stamp.
            super().write(event)
            self._last_hash = event_hash(event)
            return

        index = len(self._events)
        stamped = replace(
            event,
            chain_index=index,
            prev_hash=self._last_hash,
            signature=None,  # excluded from signing input; filled below
        )
        sig = sign_payload(self._private_key, _event_payload_for_signing(stamped))
        signed = replace(stamped, signature=sig)

        super().write(signed)
        self._last_hash = event_hash(signed)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

class ChainVerificationError(Exception):
    """Chain verification failed at a specific event."""

    def __init__(self, message: str, *, index: int):
        super().__init__(message)
        self.index = index


def verify_event_signature(event: AuditEvent, public_key: Ed25519PublicKey) -> bool:
    if event.signature is None:
        return False
    return verify_signature(
        public_key,
        _event_payload_for_signing(event),
        event.signature,
    )


def verify_chain(
    events: Iterable[AuditEvent],
    public_key: Ed25519PublicKey,
) -> tuple[bool, list[str]]:
    """Verify an ordered event stream. Returns (ok, findings).

    `findings` always contains one line per event explaining what was
    checked, so this function drives both the audit-verify CLI output
    and the evidence-packet builder.
    """
    findings: list[str] = []
    prev = GENESIS
    expected_index = 0
    ok = True

    for event in events:
        if event.signature is None:
            findings.append(f"  [!] index {event.chain_index}: no signature on event")
            ok = False
            continue
        if event.chain_index != expected_index:
            findings.append(
                f"  [!] expected chain_index={expected_index}, got {event.chain_index}"
            )
            ok = False
        if event.prev_hash != prev:
            findings.append(
                f"  [!] index {event.chain_index}: prev_hash mismatch "
                f"(expected {prev[:16]}..., got {(event.prev_hash or '')[:16]}...)"
            )
            ok = False
        if not verify_event_signature(event, public_key):
            findings.append(
                f"  [!] index {event.chain_index}: signature failed verification"
            )
            ok = False
            # Don't short-circuit — continue so the report lists every break.

        if ok or event.signature is not None:
            findings.append(
                f"  [ok] index {event.chain_index}: {event.event_type}  "
                f"prev={((event.prev_hash or '')[:12])}..."
            )
        prev = event_hash(event)
        expected_index += 1

    return ok, findings
