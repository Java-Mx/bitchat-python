"""
HKDF implementations for BitChat.

This module provides **two distinct** HKDF variants:

1. **``noise_hkdf``** — the custom HMAC-SHA256 multi-output derivation function
   used *internally* by the Noise protocol handshake state machine
   (``noise_protocol.rs`` lines 564-587).  This is NOT standard HKDF expand;
   it uses a different iteration scheme.

2. **``legacy_hkdf``** — standard HKDF-SHA256 as used by the legacy X25519
   key agreement path in ``encryption.rs`` (line 140):
       ``Hkdf::<Sha256>::new(Some(b"bitchat-v1"), shared_secret.as_bytes())``
       ``hkdf.expand(&[], &mut symmetric_key)``

These two functions must NOT be conflated.  ``noise_hkdf`` is only used inside
``noise.py``.  ``legacy_hkdf`` is used in the legacy direct-message encryption
path.

Reference:
  Rust ``noise_protocol.rs`` (custom HMAC chain, lines 564-587)
  Rust ``encryption.rs`` (standard HKDF, line 140)
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# ---------------------------------------------------------------------------
# Noise-internal HKDF (custom HMAC chain matching noise_protocol.rs)
# ---------------------------------------------------------------------------


def noise_hkdf(chaining_key: bytes, ikm: bytes, num_outputs: int) -> list[bytes]:
    """Compute the Noise-protocol HKDF as implemented in the Rust reference.

    This matches ``NoiseSymmetricState::hkdf`` (``noise_protocol.rs`` lines
    564-587) exactly:

    .. code-block:: rust

        let temp_key = HMAC-SHA256(key=chaining_key, data=ikm)
        for i in 1..=num_outputs:
            current = HMAC-SHA256(key=temp_key, data=current_output || [i as u8])
            outputs.push(current)

    Used with ``num_outputs=2`` in ``mix_key`` and ``num_outputs=3`` in
    ``mix_key_and_hash``.

    Args:
        chaining_key: Current Noise chaining key (32 bytes).
        ikm: Input key material (shared secret from DH, or empty bytes for
            ``split()``).
        num_outputs: Number of 32-byte output blocks to generate (2 or 3).

    Returns:
        A list of ``num_outputs`` 32-byte values.

    Raises:
        ValueError: If ``num_outputs`` is not in [1, 255].
    """
    if num_outputs < 1 or num_outputs > 255:
        raise ValueError(f"num_outputs must be in [1, 255], got {num_outputs}")

    # Step 1: derive temp_key from chaining_key and ikm
    temp_key = hmac.new(
        bytes(chaining_key), msg=bytes(ikm), digestmod=hashlib.sha256
    ).digest()

    outputs: list[bytes] = []
    current: bytes = b""
    for i in range(1, num_outputs + 1):
        current = hmac.new(
            temp_key, msg=current + bytes([i]), digestmod=hashlib.sha256
        ).digest()
        outputs.append(current)

    return outputs


# ---------------------------------------------------------------------------
# Legacy HKDF (standard HKDF-SHA256 used in encryption.rs)
# ---------------------------------------------------------------------------


def legacy_hkdf(
    ikm: bytes,
    *,
    salt: bytes = b"bitchat-v1",
    info: bytes = b"",
    length: int = 32,
) -> bytes:
    """Derive a symmetric key using standard HKDF-SHA256.

    Matches the Rust ``encryption.rs`` usage (lines 139-143):

    .. code-block:: rust

        let hkdf = Hkdf::<Sha256>::new(Some(b"bitchat-v1"), shared_secret.as_bytes());
        hkdf.expand(&[], &mut symmetric_key)

    The default parameters reproduce the BitChat legacy key-derivation path.
    Other parameters may be supplied when building future protocol extensions.

    Args:
        ikm: Input key material (X25519 shared secret, 32 bytes).
        salt: HKDF salt.  BitChat legacy default: ``b"bitchat-v1"``.
        info: Context/info string.  BitChat legacy default: ``b""`` (empty).
        length: Output key length in bytes.  Default: 32.

    Returns:
        Derived key of ``length`` bytes.
    """
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=bytes(salt),
        info=bytes(info),
    )
    return hkdf.derive(bytes(ikm))
