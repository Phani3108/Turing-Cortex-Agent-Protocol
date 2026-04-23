"""Load + verify Turing license files.

A license file is a small JSON document signed with Ed25519. Shape:

    {
      "key": "cx-pro-01HXXXXX",
      "tier": "pro",
      "issued_to": "user@example.com",
      "workspace_id": "ws_abc",
      "features": ["hosted_registry", "slack_approvals"],
      "issued_at": "2026-04-23T00:00:00Z",
      "expires_at": "2027-04-23T00:00:00Z",
      "signature": "ed25519:<urlsafe-base64-nopad>"
    }

The issuer signs everything except `signature` with Ed25519 over its
canonical-JSON representation (see `crypto.canonical_json`). This module
validates that signature, enforces expiry + grace, and returns an
`Entitlements` the rest of the codebase can ask questions of.

Revocation: the Cortex Cloud service publishes a revocation list at
`/.well-known/cortex-revocations.json`. The CLI checks it at most once
per 24h (see `check_revocation`). Revocation is soft: a revoked license
degrades to Standard tier instead of crashing the agent.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ..platform import license_path
from .crypto import load_public_key, public_key_from_env, verify_signature
from .entitlements import (
    STANDARD,
    Entitlements,
    Tier,
    parse_features,
    parse_tier,
)
from .pubkey import BUNDLED_PUBKEY_PEM

GRACE_DAYS_DEFAULT = 14


class LicenseError(Exception):
    """License file exists but is unusable (bad signature, malformed, etc.)."""


@dataclass(frozen=True)
class LicenseFile:
    key: str
    tier: str
    issued_to: str
    workspace_id: str
    features: list[str]
    issued_at: str
    expires_at: str
    signature: str
    raw: dict  # full dict as loaded, for round-trip / re-export


def _default_pubkey() -> Ed25519PublicKey:
    env = public_key_from_env()
    if env is not None:
        return env
    return load_public_key(BUNDLED_PUBKEY_PEM)


def _parse_iso(value: str) -> Optional[_dt.datetime]:
    if not value:
        return None
    # Python's fromisoformat in 3.11+ accepts trailing 'Z'; normalize.
    normalized = value.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _grace_days() -> int:
    raw = os.environ.get("CORTEX_LICENSE_GRACE")
    if not raw:
        return GRACE_DAYS_DEFAULT
    try:
        return max(0, int(raw))
    except ValueError:
        return GRACE_DAYS_DEFAULT


def load_license_file(path: Optional[Path] = None) -> Optional[LicenseFile]:
    """Read a license file from disk. Returns None if no file exists."""
    p = path or license_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        raise LicenseError(f"License file at {p} is not valid JSON: {e}") from e
    try:
        return LicenseFile(
            key=data["key"],
            tier=data["tier"],
            issued_to=data.get("issued_to", ""),
            workspace_id=data.get("workspace_id", ""),
            features=list(data.get("features", [])),
            issued_at=data.get("issued_at", ""),
            expires_at=data.get("expires_at", ""),
            signature=data["signature"],
            raw=data,
        )
    except KeyError as e:
        raise LicenseError(f"License file is missing required field: {e}") from e


def verify_license(
    lic: LicenseFile,
    *,
    public_key: Optional[Ed25519PublicKey] = None,
    now: Optional[_dt.datetime] = None,
) -> Entitlements:
    """Verify the license signature + expiry; return the resulting Entitlements.

    Raises LicenseError if:
      - the signature does not match the public key
      - the license has expired AND we are past the grace window
    Issued-in-the-future (clock skew up to 24h) is tolerated; anything
    further is rejected to stop a replay with a forward-dated file.
    """
    pk = public_key or _default_pubkey()
    now = now or _dt.datetime.now(_dt.timezone.utc)

    payload = {k: v for k, v in lic.raw.items() if k != "signature"}
    if not verify_signature(pk, payload, lic.signature):
        raise LicenseError("License signature did not verify against the bundled public key.")

    issued = _parse_iso(lic.issued_at)
    if issued is not None and issued > now + _dt.timedelta(hours=24):
        raise LicenseError("License issued_at is in the future. Clock out of sync?")

    expires = _parse_iso(lic.expires_at)
    in_grace = False
    if expires is not None and expires <= now:
        grace_end = expires + _dt.timedelta(days=_grace_days())
        if grace_end <= now:
            raise LicenseError(
                f"License expired on {lic.expires_at}; grace window of "
                f"{_grace_days()} days has also lapsed."
            )
        in_grace = True

    return Entitlements(
        tier=parse_tier(lic.tier),
        extra_features=parse_features(lic.features),
        issued_to=lic.issued_to,
        workspace_id=lic.workspace_id,
        expires_at=lic.expires_at,
        in_grace=in_grace,
    )


def current_entitlements(
    path: Optional[Path] = None,
    *,
    strict: bool = False,
) -> Entitlements:
    """Load + verify the current license file, falling back to Standard.

    If `strict=True`, any license-file error is propagated. By default, a
    broken or unverifiable license silently degrades to Standard — we
    never hard-fail an agent run over a licensing issue.
    """
    try:
        lic = load_license_file(path)
    except LicenseError:
        if strict:
            raise
        return STANDARD
    if lic is None:
        return STANDARD
    try:
        return verify_license(lic)
    except LicenseError:
        if strict:
            raise
        return STANDARD


# ---------------------------------------------------------------------------
# Activation helpers (used by `cortex-protocol activate`)
# ---------------------------------------------------------------------------

def install_license(content: str | bytes, *, path: Optional[Path] = None) -> Path:
    """Write a license blob (JSON text) to disk after verifying it parses."""
    from ..platform import ensure_dir

    target = path or license_path()
    ensure_dir(target.parent)

    if isinstance(content, bytes):
        content = content.decode("utf-8")

    # Parse once up front so we fail before we've written the file.
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise LicenseError(f"License content is not valid JSON: {e}") from e

    target.write_text(content)
    # 0600 on POSIX, best-effort on Windows.
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def remove_license(*, path: Optional[Path] = None) -> bool:
    p = path or license_path()
    if not p.exists():
        return False
    p.unlink()
    return True
