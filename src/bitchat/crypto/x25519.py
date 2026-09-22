"""
X25519 Diffie-Hellman key exchange wrapper for BitChat.

Wraps ``cryptography.hazmat.primitives.asymmetric.x25519`` with:
  - Explicit 32-byte size enforcement
  - Low-order point validation (matching Rust ``validate_public_key`` in
    ``noise_protocol.rs`` lines 1307-1368)
  - BitChat-specific exception types

Reference: Rust ``encryption.rs`` — ``StaticSecret::random_from_rng``,
``PublicKey::from``, ``private_key.diffie_hellman``.
``noise_protocol.rs`` — ``NoiseHandshakeState::validate_public_key``.

Key sizes:
  - Private key: 32 bytes
  - Public key: 32 bytes
  - Shared secret: 32 bytes

Do NOT log or print private key bytes.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

from bitchat.exceptions import InvalidKeyError, KeyExchangeError

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

X25519_KEY_SIZE: int = 32
"""Size of an X25519 public or private key in bytes."""

X25519_SHARED_SECRET_SIZE: int = 32
"""Size of the X25519 Diffie-Hellman shared secret in bytes."""

# Low-order points on Curve25519 that enable small-subgroup attacks.
# Reproduced from Rust ``noise_protocol.rs`` ``validate_public_key``
# (lines 1319-1353).  Matching these exactly ensures consistent key rejection
# across the Python and Rust implementations.
_LOW_ORDER_POINTS: frozenset[bytes] = frozenset(
    [
        bytes(32),  # All zeros — point at infinity
        bytes(
            [
                0x01,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,
            ]
        ),  # Point of order 1
        bytes(
            [
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x01,
            ]
        ),  # Another low-order point
        bytes(
            [
                0xE0,
                0xEB,
                0x7A,
                0x7C,
                0x3B,
                0x41,
                0xB8,
                0xAE,
                0x16,
                0x56,
                0xE3,
                0xFA,
                0xF1,
                0x9F,
                0xC4,
                0x6A,
                0xDA,
                0x09,
                0x8D,
                0xEB,
                0x9C,
                0x32,
                0xB1,
                0xFD,
                0x86,
                0x62,
                0x05,
                0x16,
                0x5F,
                0x49,
                0xB8,
                0x00,
            ]
        ),  # Low-order point
        bytes(
            [
                0x5F,
                0x9C,
                0x95,
                0xBC,
                0xA3,
                0x50,
                0x8C,
                0x24,
                0xB1,
                0xD0,
                0xB1,
                0x55,
                0x9C,
                0x83,
                0xEF,
                0x5B,
                0x04,
                0x44,
                0x5C,
                0xC4,
                0x58,
                0x1C,
                0x8E,
                0x86,
                0xD8,
                0x22,
                0x4E,
                0xDD,
                0xD0,
                0x9F,
                0x11,
                0x57,
            ]
        ),  # Low-order point
        bytes([0xFF] * 32),  # All ones
        bytes(
            [
                0xDA,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
            ]
        ),  # Bad point
        bytes(
            [
                0xDB,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
                0xFF,
            ]
        ),  # Bad point
    ]
)


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_private_key() -> bytes:
    """Generate a new X25519 private key using the OS CSPRNG.

    Returns:
        32-byte raw X25519 private key.  Handle with care — do not log or
        store in plaintext.
    """
    private_key = X25519PrivateKey.generate()
    return private_key.private_bytes_raw()


def public_key_from_private(private_key_bytes: bytes) -> bytes:
    """Derive the 32-byte X25519 public key from a raw private key.

    Args:
        private_key_bytes: 32-byte raw X25519 private key.

    Returns:
        32-byte raw X25519 public key.

    Raises:
        InvalidKeyError: If ``private_key_bytes`` is not exactly 32 bytes or
            is otherwise invalid.
    """
    _validate_private_key_input(private_key_bytes)
    try:
        private_key = X25519PrivateKey.from_private_bytes(bytes(private_key_bytes))
        return private_key.public_key().public_bytes_raw()
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(f"Invalid X25519 private key: {exc}") from exc


def validate_public_key(public_key_bytes: bytes) -> bytes:
    """Validate a raw 32-byte X25519 public key.

    Checks:
    - Correct length (32 bytes)
    - Not a known low-order/weak point (matching Rust reference)
    - Parseable by the cryptography library

    Args:
        public_key_bytes: 32-byte raw X25519 public key.

    Returns:
        The validated key as immutable ``bytes``.

    Raises:
        InvalidKeyError: If the key fails any validation check.
    """
    if not isinstance(public_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"X25519 public key must be bytes, got {type(public_key_bytes).__name__}"
        )
    if len(public_key_bytes) != X25519_KEY_SIZE:
        raise InvalidKeyError(
            f"X25519 public key must be {X25519_KEY_SIZE} bytes, "
            f"got {len(public_key_bytes)}"
        )
    key_bytes = bytes(public_key_bytes)
    if key_bytes in _LOW_ORDER_POINTS:
        raise InvalidKeyError("X25519 public key is a known low-order/weak point")
    try:
        X25519PublicKey.from_public_bytes(key_bytes)
    except (ValueError, TypeError) as exc:
        raise InvalidKeyError(f"Invalid X25519 public key: {exc}") from exc
    return key_bytes


# ---------------------------------------------------------------------------
# Diffie-Hellman exchange
# ---------------------------------------------------------------------------


def diffie_hellman(local_private_bytes: bytes, remote_public_bytes: bytes) -> bytes:
    """Perform an X25519 Diffie-Hellman key exchange.

    Validates the remote public key for low-order points before performing
    the exchange (matching Rust ``validate_public_key`` call in
    ``noise_protocol.rs``).

    Args:
        local_private_bytes: 32-byte raw local X25519 private key.
        remote_public_bytes: 32-byte raw remote X25519 public key.

    Returns:
        32-byte shared secret.  Do NOT log or expose this value.

    Raises:
        InvalidKeyError: If either key is malformed, wrong size, or
            ``remote_public_bytes`` is a low-order point.
        KeyExchangeError: If the DH operation fails for any other reason.
    """
    _validate_private_key_input(local_private_bytes)
    remote_validated = validate_public_key(remote_public_bytes)
    try:
        private_key = X25519PrivateKey.from_private_bytes(bytes(local_private_bytes))
        remote_pub = X25519PublicKey.from_public_bytes(remote_validated)
        shared = private_key.exchange(remote_pub)
    except InvalidKeyError:
        raise
    except (ValueError, TypeError) as exc:
        raise KeyExchangeError(f"X25519 Diffie-Hellman exchange failed: {exc}") from exc
    if len(shared) != X25519_SHARED_SECRET_SIZE:
        raise KeyExchangeError(
            f"X25519 produced unexpected shared secret length {len(shared)}"
        )
    return shared


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_private_key_input(private_key_bytes: object) -> None:
    """Raise InvalidKeyError if the private key input is not valid bytes."""
    if not isinstance(private_key_bytes, (bytes, bytearray)):
        raise InvalidKeyError(
            f"X25519 private key must be bytes, got {type(private_key_bytes).__name__}"
        )
    if len(private_key_bytes) != X25519_KEY_SIZE:  # type: ignore[arg-type]
        raise InvalidKeyError(
            f"X25519 private key must be {X25519_KEY_SIZE} bytes, "
            f"got {len(private_key_bytes)}"  # type: ignore[arg-type]
        )
