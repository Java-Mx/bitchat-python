"""
Ed25519 digital signature wrapper for BitChat.

Wraps ``cryptography.hazmat.primitives.asymmetric.ed25519`` with explicit size
enforcement and BitChat-specific exception types.

Reference: Rust ``encryption.rs`` — ``SigningKey::generate``, ``signing_key.sign``,
``verifying_key.verify_strict``.

Key sizes (standard Ed25519):
  - Private (signing) key: 32 bytes
  - Public (verifying) key: 32 bytes
  - Signature: 64 bytes

Do NOT expose private key bytes through logging, repr, or exception messages.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from bitchat.exceptions import (
    InvalidKeyError,
    InvalidSignatureError,
    SignatureVerificationError,
)

# ---------------------------------------------------------------------------
# Public constants — never change these; they are part of the wire protocol
# ---------------------------------------------------------------------------

ED25519_PRIVATE_KEY_SIZE: int = 32
"""Size of a raw Ed25519 private key in bytes."""

ED25519_PUBLIC_KEY_SIZE: int = 32
"""Size of a raw Ed25519 public key (verifying key) in bytes."""

ED25519_SIGNATURE_SIZE: int = 64
"""Size of an Ed25519 signature in bytes."""


# ---------------------------------------------------------------------------
# Key generation and serialization
# ---------------------------------------------------------------------------


def generate_signing_key() -> bytes:
    """Generate a new Ed25519 signing key and return the raw 32-byte private key.

    Uses the OS CSPRNG via the ``cryptography`` library.  The returned bytes
    are the raw seed (private key material) — handle with care.

    Returns:
        32-byte raw Ed25519 private key (seed).
    """
    private_key = Ed25519PrivateKey.generate()
    # raw_private returns the 32-byte seed
    return private_key.private_bytes_raw()


def public_key_from_private(private_key_bytes: bytes) -> bytes:
    """Derive the 32-byte Ed25519 public (verifying) key from a private key.

    Args:
        private_key_bytes: 32-byte raw Ed25519 private key.

    Returns:
        32-byte raw Ed25519 public key.

    Raises:
        InvalidKeyError: If ``private_key_bytes`` is not exactly 32 bytes or
            is otherwise invalid.
    """
    if not isinstance(private_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"Ed25519 private key must be bytes, got {type(private_key_bytes).__name__}"
        )
    if len(private_key_bytes) != ED25519_PRIVATE_KEY_SIZE:
        raise InvalidKeyError(
            f"Ed25519 private key must be {ED25519_PRIVATE_KEY_SIZE} bytes, "
            f"got {len(private_key_bytes)}"
        )
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(private_key_bytes))
        return private_key.public_key().public_bytes_raw()
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(f"Invalid Ed25519 private key: {exc}") from exc


def load_public_key(public_key_bytes: bytes) -> bytes:
    """Validate and normalise a raw 32-byte Ed25519 public key.

    Args:
        public_key_bytes: 32-byte raw Ed25519 public key.

    Returns:
        The same 32-byte value as immutable ``bytes``.

    Raises:
        InvalidKeyError: If the key is not exactly 32 bytes or is otherwise
            invalid.
    """
    if not isinstance(public_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"Ed25519 public key must be bytes, got {type(public_key_bytes).__name__}"
        )
    if len(public_key_bytes) != ED25519_PUBLIC_KEY_SIZE:
        raise InvalidKeyError(
            f"Ed25519 public key must be {ED25519_PUBLIC_KEY_SIZE} bytes, "
            f"got {len(public_key_bytes)}"
        )
    try:
        # Validate by attempting to parse; raises ValueError for invalid points
        Ed25519PublicKey.from_public_bytes(bytes(public_key_bytes))
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(f"Invalid Ed25519 public key: {exc}") from exc
    return bytes(public_key_bytes)


# ---------------------------------------------------------------------------
# Signing and verification
# ---------------------------------------------------------------------------


def sign(private_key_bytes: bytes, data: bytes) -> bytes:
    """Sign ``data`` with the given Ed25519 private key.

    Args:
        private_key_bytes: 32-byte raw Ed25519 private key.
        data: Arbitrary byte string to sign.

    Returns:
        64-byte Ed25519 signature.

    Raises:
        InvalidKeyError: If ``private_key_bytes`` is invalid.
        TypeError: If ``data`` is not bytes-like.
    """
    if not isinstance(private_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"Ed25519 private key must be bytes, got {type(private_key_bytes).__name__}"
        )
    if len(private_key_bytes) != ED25519_PRIVATE_KEY_SIZE:
        raise InvalidKeyError(
            f"Ed25519 private key must be {ED25519_PRIVATE_KEY_SIZE} bytes, "
            f"got {len(private_key_bytes)}"
        )
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(private_key_bytes))
        sig = private_key.sign(bytes(data))
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(
            f"Invalid Ed25519 private key during signing: {exc}"
        ) from exc
    assert len(sig) == ED25519_SIGNATURE_SIZE, (
        f"Ed25519 produced unexpected signature length {len(sig)}"
    )
    return sig


def verify(public_key_bytes: bytes, signature: bytes, data: bytes) -> None:
    """Verify an Ed25519 signature.

    Args:
        public_key_bytes: 32-byte raw Ed25519 public key.
        signature: 64-byte Ed25519 signature.
        data: The original signed data.

    Raises:
        InvalidKeyError: If ``public_key_bytes`` is not 32 bytes or invalid.
        InvalidSignatureError: If ``signature`` is not 64 bytes.
        SignatureVerificationError: If the signature does not verify.
    """
    if not isinstance(public_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"Ed25519 public key must be bytes, got {type(public_key_bytes).__name__}"
        )
    if len(public_key_bytes) != ED25519_PUBLIC_KEY_SIZE:
        raise InvalidKeyError(
            f"Ed25519 public key must be {ED25519_PUBLIC_KEY_SIZE} bytes, "
            f"got {len(public_key_bytes)}"
        )
    if not isinstance(signature, (bytes, bytearray)):
        raise InvalidSignatureError(
            f"Signature must be bytes, got {type(signature).__name__}"
        )
    if len(signature) != ED25519_SIGNATURE_SIZE:
        raise InvalidSignatureError(
            f"Ed25519 signature must be {ED25519_SIGNATURE_SIZE} bytes, "
            f"got {len(signature)}"
        )
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes(public_key_bytes))
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(f"Invalid Ed25519 public key: {exc}") from exc
    try:
        public_key.verify(bytes(signature), bytes(data))
    except InvalidSignature as exc:
        raise SignatureVerificationError(
            "Ed25519 signature verification failed"
        ) from exc
