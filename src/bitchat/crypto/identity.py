"""
Local cryptographic identity abstraction for BitChat.

A ``LocalIdentity`` represents a complete set of cryptographic keys for a
single BitChat session:
  - X25519 static key pair (key agreement, Noise static key)
  - Ed25519 key pair (message signing / verification)

The fingerprint and peer_id are both derived from the X25519 public key,
matching the Rust reference:
  - ``get_identity_fingerprint`` in ``noise_session.rs`` line 628-631:
    ``SHA-256(X25519_public_key.to_bytes())`` → full hex string
  - Peer ID: first 8 bytes of SHA-256(X25519_public_key) → used for BLE
    identification (matching how peer IDs are derived in the protocol)

The combined public key (96 bytes) for wire exchange matches Rust
``get_combined_public_key_data`` (``encryption.rs`` lines 77-83):
  ``x25519_pub(32) || ed25519_pub(32) || ed25519_pub(32)``
  (Note: the third 32 bytes is a dedicated "identity" key; in this
   implementation we reuse the ed25519 key, matching the common case
   where the identity key equals the signing key.)

Private key material is NEVER exposed through:
  - ``__repr__``
  - ``__str__``
  - logging calls
  - exception messages
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from bitchat.crypto import ed25519 as _ed25519
from bitchat.crypto import x25519 as _x25519


@dataclass(frozen=True)
class LocalIdentity:
    """Immutable local cryptographic identity.

    All byte fields are stored as immutable ``bytes`` objects.  Private key
    bytes are excluded from the default string representation.

    Attributes:
        x25519_private: 32-byte X25519 static private key.
        x25519_public: 32-byte X25519 static public key.
        ed25519_private: 32-byte Ed25519 signing key (private seed).
        ed25519_public: 32-byte Ed25519 verifying key (public).
        peer_id: 8-byte peer identifier derived as first 8 bytes of
            SHA-256(x25519_public).
        fingerprint: 64-character hex string: SHA-256(x25519_public).hex().
    """

    # Private key material — handled carefully
    x25519_private: bytes
    ed25519_private: bytes

    # Public material — safe to share
    x25519_public: bytes
    ed25519_public: bytes

    # Derived fields
    peer_id: bytes
    fingerprint: str

    def __post_init__(self) -> None:
        # Enforce immutable bytes for all fields
        object.__setattr__(self, "x25519_private", bytes(self.x25519_private))
        object.__setattr__(self, "ed25519_private", bytes(self.ed25519_private))
        object.__setattr__(self, "x25519_public", bytes(self.x25519_public))
        object.__setattr__(self, "ed25519_public", bytes(self.ed25519_public))
        object.__setattr__(self, "peer_id", bytes(self.peer_id))

    def __repr__(self) -> str:
        """Return a safe representation that NEVER exposes private key bytes."""
        return (
            f"LocalIdentity("
            f"fingerprint={self.fingerprint!r}, "
            f"peer_id={self.peer_id.hex()!r}"
            f")"
        )

    def __str__(self) -> str:
        return self.__repr__()

    # -----------------------------------------------------------------------
    # Public wire API
    # -----------------------------------------------------------------------

    @property
    def combined_public_key(self) -> bytes:
        """96-byte combined public key for wire exchange.

        Format (matching Rust ``get_combined_public_key_data``):
          ``x25519_pub(32) || ed25519_pub(32) || ed25519_pub(32)``

        The third segment is the "identity" public key.  We reuse the ed25519
        public key for it, consistent with how the common-case Rust client
        behaves when no separate persistent identity key is maintained.

        Returns:
            96-byte bytes.
        """
        return self.x25519_public + self.ed25519_public + self.ed25519_public

    @property
    def peer_id_hex(self) -> str:
        """Hex-encoded peer ID string (16 lowercase hex characters)."""
        return self.peer_id.hex()

    # -----------------------------------------------------------------------
    # Factory methods
    # -----------------------------------------------------------------------

    @classmethod
    def generate(cls) -> LocalIdentity:
        """Generate a new random ``LocalIdentity`` using the OS CSPRNG.

        Calls the ``cryptography`` library's key generation routines for both
        X25519 and Ed25519, which use ``os.urandom`` internally.

        Returns:
            A freshly generated ``LocalIdentity``.
        """
        x25519_priv = _x25519.generate_private_key()
        ed25519_priv = _ed25519.generate_signing_key()
        return cls._from_private_keys(x25519_priv, ed25519_priv)

    @classmethod
    def from_x25519_private(
        cls, x25519_private: bytes, ed25519_private: bytes | None = None
    ) -> LocalIdentity:
        """Construct a ``LocalIdentity`` from known private key bytes.

        Intended for test vector generation and deterministic testing only.
        In production, always use ``generate()``.

        Args:
            x25519_private: 32-byte X25519 private key.
            ed25519_private: Optional 32-byte Ed25519 private key.  If
                ``None``, a new Ed25519 key is generated randomly.

        Returns:
            A ``LocalIdentity`` with the given X25519 key.
        """
        if ed25519_private is None:
            ed25519_priv = _ed25519.generate_signing_key()
        else:
            ed25519_priv = bytes(ed25519_private)
        return cls._from_private_keys(bytes(x25519_private), ed25519_priv)

    @classmethod
    def _from_private_keys(
        cls, x25519_priv: bytes, ed25519_priv: bytes
    ) -> LocalIdentity:
        """Internal factory from raw private key bytes."""
        x25519_pub = _x25519.public_key_from_private(x25519_priv)
        ed25519_pub = _ed25519.public_key_from_private(ed25519_priv)

        # Fingerprint: SHA-256(x25519_pub) → full 64-char hex
        # Matches Rust NoiseSessionManager::calculate_fingerprint
        # (noise_session.rs lines 633-641)
        fp_digest = hashlib.sha256(x25519_pub).digest()
        fingerprint = fp_digest.hex()  # 64 lowercase hex characters

        # Peer ID: first 8 bytes of SHA-256(x25519_pub)
        peer_id = fp_digest[:8]

        return cls(
            x25519_private=x25519_priv,
            ed25519_private=ed25519_priv,
            x25519_public=x25519_pub,
            ed25519_public=ed25519_pub,
            peer_id=peer_id,
            fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# Peer fingerprint utilities
# ---------------------------------------------------------------------------


def calculate_fingerprint(x25519_public_key: bytes) -> str:
    """Calculate a BitChat peer fingerprint from an X25519 public key.

    Matches Rust ``NoiseSessionManager::calculate_fingerprint``
    (``noise_session.rs`` lines 633-641):
    ``SHA-256(x25519_pub.to_bytes()).to_hex_string()`` — full 64-char hex.

    Args:
        x25519_public_key: 32-byte X25519 public key.

    Returns:
        64-character lowercase hex fingerprint string.
    """
    return hashlib.sha256(bytes(x25519_public_key)).hexdigest()
