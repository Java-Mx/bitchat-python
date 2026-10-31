"""Tier 1: Feature Coverage — Encrypted Direct Messaging & Replay Filter."""

from __future__ import annotations

import os
import struct

import pytest

from bitchat.crypto.noise import (
    NoiseCipherState,
)
from bitchat.exceptions import (
    DecryptionError,
    ReplayError,
)


def test_cipher_state_transport_encryption_and_decryption() -> None:
    """Validate symmetric transport encryption and decryption roundtrip."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    secret_message = b"Confidential direct peer message"
    aad = b"associated-metadata"

    ciphertext = sender.encrypt(secret_message, aad)
    # 4 bytes nonce + len(secret_message) + 16 bytes ChaChaPoly tag
    assert len(ciphertext) == 4 + len(secret_message) + 16

    plaintext = receiver.decrypt(ciphertext, aad)
    assert plaintext == secret_message


def test_cipher_state_wire_nonce_prefix_format() -> None:
    """Validate that transport mode prepends a monotonically increasing 4-byte LE nonce."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)

    for expected_nonce in range(5):
        ct = sender.encrypt(b"msg", b"")
        (extracted_nonce,) = struct.unpack("<I", ct[:4])
        assert extracted_nonce == expected_nonce


def test_in_order_sequential_nonces_accepted() -> None:
    """Validate that sequential nonces (0..19) decrypt cleanly."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    for i in range(20):
        msg = f"Message sequence #{i}".encode()
        ct = sender.encrypt(msg, b"")
        decrypted = receiver.decrypt(ct, b"")
        assert decrypted == msg


def test_out_of_order_nonces_within_sliding_window_accepted() -> None:
    """Validate that out-of-order nonces within the 1024-entry window decrypt cleanly."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    # Pre-generate 10 ciphertexts with nonces 0..9
    ciphertexts = [sender.encrypt(f"Msg-{i}".encode(), b"") for i in range(10)]

    # Deliver in out-of-order sequence (e.g. 5, 2, 7, 1, 4, 3, 6, 9, 8)
    delivery_order = [5, 2, 7, 1, 4, 3, 6, 9, 8]
    for idx in delivery_order:
        dec = receiver.decrypt(ciphertexts[idx], b"")
        assert dec == f"Msg-{idx}".encode()


def test_associated_data_authentication_protection() -> None:
    """Validate authenticated associated data binding and tampering prevention."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    msg = b"Authenticated payload"
    aad_valid = b"packet-header-metadata"
    aad_tampered = b"packet-header-MODIFIED"

    ct = sender.encrypt(msg, aad_valid)

    # Decrypt with correct AAD succeeds
    assert receiver.decrypt(ct, aad_valid) == msg

    # Re-encrypt for second test
    ct2 = sender.encrypt(msg, aad_valid)
    # Decrypt with tampered AAD fails with DecryptionError
    with pytest.raises(DecryptionError):
        receiver.decrypt(ct2, aad_tampered)


def test_duplicate_nonces_rejected_as_replay() -> None:
    """Validate that receiving a duplicate non-zero nonce raises ReplayError."""
    shared_key = os.urandom(32)
    sender = NoiseCipherState(shared_key, use_extracted_nonce=True)
    receiver = NoiseCipherState(shared_key, use_extracted_nonce=True)

    # Nonce 0
    c0 = sender.encrypt(b"msg 0", b"")
    receiver.decrypt(c0, b"")

    # Nonce 1
    c1 = sender.encrypt(b"msg 1", b"")
    p1 = receiver.decrypt(c1, b"")
    assert p1 == b"msg 1"

    # Replaying nonce 1 must raise ReplayError
    with pytest.raises(ReplayError):
        receiver.decrypt(c1, b"")
