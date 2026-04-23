"""Ed25519 sign + verify primitives for Turing license files and audit chains.

Kept in one place so every caller (license loader, SignedAuditLog,
evidence packets) goes through the same canonical-JSON payload shape and
the same base64-encoded signature format.

Signature format: a prefixed string ``ed25519:<urlsafe-base64-nopad>`` so
future algorithms (Ed448, post-quantum) can coexist without schema churn.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)

SIG_PREFIX = "ed25519:"


# ---------------------------------------------------------------------------
# Canonical JSON — stable byte representation for signing.
# ---------------------------------------------------------------------------

def canonical_json(payload: Any) -> bytes:
    """Return a deterministic JSON byte-encoding suitable for signing.

    Sorted keys, no whitespace, UTF-8. Must match the canonicalization the
    license issuer / audit writer used, or signatures will not verify.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------

def generate_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def private_key_to_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    ).decode("utf-8")


def public_key_to_pem(key: Ed25519PublicKey) -> str:
    return key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def load_public_key(pem_or_bytes: str | bytes) -> Ed25519PublicKey:
    data = pem_or_bytes.encode("utf-8") if isinstance(pem_or_bytes, str) else pem_or_bytes
    key = load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Public key is not Ed25519.")
    return key


def load_private_key(pem_or_bytes: str | bytes) -> Ed25519PrivateKey:
    data = pem_or_bytes.encode("utf-8") if isinstance(pem_or_bytes, str) else pem_or_bytes
    key = load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Private key is not Ed25519.")
    return key


# ---------------------------------------------------------------------------
# Sign / verify
# ---------------------------------------------------------------------------

def sign_payload(private_key: Ed25519PrivateKey, payload: Any) -> str:
    """Sign `payload` (dict or list) and return a prefixed signature string."""
    sig = private_key.sign(canonical_json(payload))
    return SIG_PREFIX + base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")


def verify_signature(public_key: Ed25519PublicKey, payload: Any, signature: str) -> bool:
    """Return True if `signature` is a valid Ed25519 sig over `payload`.

    Constant-time verification via the cryptography library; we never
    compare signatures with `==` or short-circuit on a mismatch.
    """
    if not signature.startswith(SIG_PREFIX):
        return False
    b64 = signature[len(SIG_PREFIX):]
    # Re-pad to base64's multiple of 4 before decoding.
    b64 += "=" * (-len(b64) % 4)
    try:
        sig_bytes = base64.urlsafe_b64decode(b64)
    except (ValueError, TypeError):
        return False
    try:
        public_key.verify(sig_bytes, canonical_json(payload))
        return True
    except InvalidSignature:
        return False


# ---------------------------------------------------------------------------
# Hash chains (used by SignedAuditLog + evidence packets)
# ---------------------------------------------------------------------------

def sha256_hex(data: bytes | str) -> str:
    import hashlib
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Test / env overrides
# ---------------------------------------------------------------------------

def public_key_from_env() -> Ed25519PublicKey | None:
    """Return a public key overridden via env var, or None.

    Env vars (first match wins):
      CORTEX_LICENSE_PUBKEY       PEM-encoded public key string
      CORTEX_LICENSE_PUBKEY_PATH  Path to a PEM file
    """
    pem = os.environ.get("CORTEX_LICENSE_PUBKEY")
    if pem:
        return load_public_key(pem)
    path = os.environ.get("CORTEX_LICENSE_PUBKEY_PATH")
    if path:
        with open(path) as f:
            return load_public_key(f.read())
    return None
