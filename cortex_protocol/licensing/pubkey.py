"""Turing license public key — bundled with the wheel.

This is the Ed25519 public half of the Cortex Cloud license-issuer
keypair. The corresponding private key lives in Cortex Cloud's KMS and
is only touched by the license issuance service (Stripe webhook →
signer → emailed license).

*This placeholder key is for the 0.5.x dev line.* Before 0.5 GA, the
release process replaces this constant with the real Cortex Cloud key.
Any license minted against the dev private key will stop verifying once
the GA key ships — that is the intended cutover behavior.

To run tests or an internal deployment against your own keypair, set
`CORTEX_LICENSE_PUBKEY` or `CORTEX_LICENSE_PUBKEY_PATH` in the env.
"""

from __future__ import annotations

# Dev-line placeholder. Replace at release time. See module docstring.
BUNDLED_PUBKEY_PEM: str = """\
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAKuNxRky4/YrZnegaEueztXU5dz5eroMHnvwJ4EAEbQc=
-----END PUBLIC KEY-----
"""
