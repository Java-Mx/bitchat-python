"""Tier 2: Boundary & Corner Cases — Encrypted Messaging & Replay Filter Boundaries."""

from __future__ import annotations

import os
import struct

import pytest

from bitchat.crypto.noise import (
    NoiseCipherState,
)
from bitchat.exceptions import (
    DecryptionError,
    InvalidNonceError,
    ReplayError,
)


def test_tampered_ciphertext_payload_raises_decryption_error() -> None:
    """Validate modifying 1 byte in ciphertext body triggers ChaChaPoly tag authentication failure."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    ct = bytearray(sender.encrypt(b"Top secret content", b""))
    # Corrupt body (byte index 6, after 4-byte nonce)
    ct[6] ^= 0x01

    with pytest.raises(DecryptionError):
        receiver.decrypt(bytes(ct), b"")


def test_tampered_poly1305_tag_raises_decryption_error() -> None:
    """Validate modifying 1 byte in ChaCha20-Poly1305 16-byte authentication tag fails."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    ct = bytearray(sender.encrypt(b"Authentic message", b""))
    # Corrupt final byte of tag
    ct[-1] ^= 0x80

    with pytest.raises(DecryptionError):
        receiver.decrypt(bytes(ct), b"")


def test_tampered_wire_nonce_prefix_raises_error() -> None:
    """Validate tampering 4-byte LE nonce prefix causes decryption authentication failure."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    # Sender generates nonce 0
    ct = bytearray(sender.encrypt(b"Payload test", b""))
    # Tamper nonce prefix to 123
    ct[:4] = struct.pack("<I", 123)

    with pytest.raises(DecryptionError):
        receiver.decrypt(bytes(ct), b"")


def test_stale_nonce_far_behind_window_rejected_as_replay() -> None:
    """Validate nonce older than highest_seen - 1024 is rejected as stale replay."""
    shared_key = os.urandom(32)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    # Manually advance receiver state to simulate having seen nonce 2000
    receiver._highest_received_nonce = 2000
    receiver._replay_window = {2000}
    receiver._key = shared_key

    # Nonce 500 is way below 2000 - 1024 (976)
    # Build fake ciphertext with nonce 500
    prefix = struct.pack("<I", 500)
    fake_ct = prefix + b"A" * 32

    with pytest.raises(ReplayError, match=r"too old|replay window"):
        receiver.decrypt(fake_ct, b"")


def test_duplicate_nonce_within_sliding_window_rejected() -> None:
    """Validate replaying an already-seen nonce within the 1024 window raises ReplayError."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    # Nonce 0
    c0 = sender.encrypt(b"msg 0", b"")
    receiver.decrypt(c0, b"")

    # Nonce 1
    c1 = sender.encrypt(b"msg 1", b"")
    receiver.decrypt(c1, b"")

    # Nonce 2
    c2 = sender.encrypt(b"msg 2", b"")
    receiver.decrypt(c2, b"")

    # Replaying c1 (nonce 1)
    with pytest.raises(ReplayError, match="Replay detected"):
        receiver.decrypt(c1, b"")


def test_ciphertext_shorter_than_nonce_prefix_raises_invalid_nonce_error() -> None:
    """Validate ciphertext shorter than 4 bytes raises InvalidNonceError."""
    shared_key = os.urandom(32)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    truncated_ct = b"\x01\x02"  # only 2 bytes, needs at least 4
    with pytest.raises(InvalidNonceError, match="too short to contain 4-byte nonce"):
        receiver.decrypt(truncated_ct, b"")
