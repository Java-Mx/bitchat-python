"""
PBKDF2-HMAC-SHA256 key derivation for password-protected BitChat channels.

Matches the Rust ``EncryptionService::derive_channel_key``
(``encryption.rs`` lines 285-294):

.. code-block:: rust

    pbkdf2_hmac::<Sha256>(
        password.as_bytes(),
        channel_name.as_bytes(),  // salt = channel name UTF-8
        100_000,                  // iterations
        &mut key,                 // 32-byte output
    );

This function is ONLY for channel-password key derivation.  Do NOT use it
for identity, session, or Noise key material.

Reference: Rust ``encryption.rs`` lines 284-294.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# Constants — verified against Rust source
# ---------------------------------------------------------------------------

PBKDF2_ITERATIONS: int = 100_000
"""Iteration count matching Rust ``derive_channel_key`` (encryption.rs line 290)."""

PBKDF2_OUTPUT_LENGTH: int = 32
"""Output key length in bytes (AES-256 key)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_channel_key(password: str, channel_name: str) -> bytes:
    """Derive a 32-byte AES-256 channel key from a password and channel name.

    The derivation exactly matches the Rust implementation:
      - Algorithm: PBKDF2-HMAC-SHA256
      - Salt: ``channel_name`` encoded as UTF-8 bytes
      - Iterations: 100,000
      - Output: 32 bytes

    The same ``password`` and ``channel_name`` always produce the same key.
    This is intentional — channels require a shared, reproducible key
    derived from a shared secret (the password).

    Args:
        password: Plain-text channel password (UTF-8).
        channel_name: The channel name used as the PBKDF2 salt (UTF-8).
            Matching Rust: ``channel_name.as_bytes()`` is used directly as salt.

    Returns:
        32-byte derived symmetric channel key.

    Raises:
        TypeError: If ``password`` or ``channel_name`` are not strings.
    """
    if not isinstance(password, str):
        raise TypeError(f"password must be str, got {type(password).__name__}")
    if not isinstance(channel_name, str):
        raise TypeError(f"channel_name must be str, got {type(channel_name).__name__}")

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_OUTPUT_LENGTH,
        salt=channel_name.encode("utf-8"),
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))
