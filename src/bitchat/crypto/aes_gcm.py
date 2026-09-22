"""
AES-256-GCM encryption wrapper for BitChat legacy direct-message encryption.

Implements the encryption/decryption used in the legacy X25519 key-agreement
path (``encryption.rs`` ``encrypt_legacy`` / ``decrypt_legacy`` and
``encrypt_with_key`` / ``decrypt_with_key``).

Wire format (matching Rust):
    ``nonce(12 bytes) || ciphertext+tag(N+16 bytes)``

Security rules enforced here:
  - Every encryption call generates a fresh 12-byte random nonce via ``os.urandom``.
  - The nonce is NEVER reused within a single encrypt call.
  - Callers must rotate keys before nonce space exhaustion (not tracked here;
    upper layers are responsible for key freshness).
  - Authentication tag is included in the ``cryptography`` library's output
    automatically (AES-GCM mode appends the 16-byte tag to ciphertext).

Reference: Rust ``encryption.rs`` lines 204-262, 296-329.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bitchat.exceptions import DecryptionError, EncryptionError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AES_KEY_SIZE: int = 32
"""Required AES-256 key size in bytes."""

AES_NONCE_SIZE: int = 12
"""Required AES-GCM nonce size in bytes (96-bit random nonce)."""

AES_TAG_SIZE: int = 16
"""AES-GCM authentication tag size appended to ciphertext."""

_MIN_CIPHERTEXT_SIZE: int = AES_NONCE_SIZE + AES_TAG_SIZE
"""Minimum valid AES-GCM payload size: nonce(12) + tag(16)."""


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt ``plaintext`` with AES-256-GCM using a fresh random nonce.

    Returns the combined ``nonce || ciphertext+tag`` blob matching the Rust
    wire format (``encryption.rs`` lines 217-221).

    Args:
        key: 32-byte AES-256 key.
        plaintext: Data to encrypt.

    Returns:
        ``nonce(12) || ciphertext+tag`` — total length is
        ``len(plaintext) + 28`` bytes.

    Raises:
        EncryptionError: If the key is invalid or the AEAD operation fails.
    """
    _validate_key(key)
    nonce = os.urandom(AES_NONCE_SIZE)
    try:
        aesgcm = AESGCM(bytes(key))
        ciphertext_and_tag = aesgcm.encrypt(nonce, bytes(plaintext), None)
    except (ValueError, TypeError) as exc:
        raise EncryptionError(f"AES-256-GCM encryption failed: {exc}") from exc
    return nonce + ciphertext_and_tag


def encrypt_with_key(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt with an explicit channel key.  Alias for ``encrypt``.

    Used for password-protected channel message encryption
    (``encryption.rs`` ``encrypt_with_key``).

    Args:
        key: 32-byte AES-256 channel key.
        plaintext: Data to encrypt.

    Returns:
        ``nonce(12) || ciphertext+tag``.

    Raises:
        EncryptionError: If key is invalid or encryption fails.
    """
    return encrypt(key, plaintext)


# ---------------------------------------------------------------------------
# Decryption
# ---------------------------------------------------------------------------


def decrypt(key: bytes, data: bytes) -> bytes:
    """Decrypt an AES-256-GCM payload in ``nonce || ciphertext+tag`` format.

    Matches the Rust ``decrypt_legacy`` (``encryption.rs`` lines 241-262).
    The ``cryptography`` library verifies the GCM tag internally; if it fails,
    it raises ``InvalidTag``, which we map to ``DecryptionError``.

    Args:
        key: 32-byte AES-256 key (must be the same key used for encryption).
        data: ``nonce(12) || ciphertext+tag`` blob.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        DecryptionError: If ``data`` is too short, the key is invalid, the
            authentication tag fails, or any other decryption error occurs.
    """
    _validate_key(key)
    if not isinstance(data, (bytes, bytearray)):
        raise DecryptionError(f"AES-GCM input must be bytes, got {type(data).__name__}")
    if len(data) < _MIN_CIPHERTEXT_SIZE:
        raise DecryptionError(
            f"AES-GCM data too short: need at least {_MIN_CIPHERTEXT_SIZE} bytes "
            f"(nonce + tag), got {len(data)}"
        )
    nonce = bytes(data[:AES_NONCE_SIZE])
    ciphertext_and_tag = bytes(data[AES_NONCE_SIZE:])
    try:
        aesgcm = AESGCM(bytes(key))
        return aesgcm.decrypt(nonce, ciphertext_and_tag, None)
    except Exception as exc:  # cryptography raises InvalidTag or ValueError
        raise DecryptionError(
            "AES-256-GCM decryption or authentication failed"
        ) from exc


def decrypt_with_key(key: bytes, data: bytes) -> bytes:
    """Decrypt a channel-key-encrypted payload.  Alias for ``decrypt``.

    Used for password-protected channel message decryption
    (``encryption.rs`` ``decrypt_with_key``).

    Args:
        key: 32-byte AES-256 channel key.
        data: ``nonce(12) || ciphertext+tag`` blob.

    Returns:
        Decrypted plaintext bytes.

    Raises:
        DecryptionError: If decryption or authentication fails.
    """
    return decrypt(key, data)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_key(key: object) -> None:
    """Raise EncryptionError if the AES key is not valid."""
    if not isinstance(key, (bytes, bytearray)):
        raise EncryptionError(f"AES key must be bytes, got {type(key).__name__}")
    if len(key) != AES_KEY_SIZE:  # type: ignore[arg-type]
        raise EncryptionError(
            f"AES-256 key must be {AES_KEY_SIZE} bytes, got {len(key)}"  # type: ignore[arg-type]
        )
