"""Tier 2: Boundary & Corner Cases — Cryptographic & Handshake Boundaries."""

from __future__ import annotations

import pytest

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import (
    NoiseError,
    NoiseStateError,
)


def _setup_sessions() -> tuple[NoiseSession, NoiseSession]:
    alice_id = LocalIdentity.generate()
    bob_id = LocalIdentity.generate()

    alice_session = NoiseSession(
        local_identity=alice_id,
        remote_peer_id=bob_id.peer_id_hex,
    )
    bob_session = NoiseSession(
        local_identity=bob_id,
        remote_peer_id=alice_id.peer_id_hex,
    )

    initiator = (
        alice_session if alice_session.role == NoiseRole.INITIATOR else bob_session
    )
    responder = bob_session if initiator is alice_session else alice_session
    return initiator, responder


def test_handshake_truncated_message_1_fails() -> None:
    """Validate responder processing truncated message 1 (<32B) transitions to FAILED."""
    _initiator, responder = _setup_sessions()

    # Truncated message 1 (only 10 bytes instead of 32-byte ephemeral key)
    truncated_msg1 = b"\x01" * 10

    with pytest.raises(NoiseError):
        responder.process_handshake_message(truncated_msg1)

    assert responder.state == NoiseSessionState.FAILED


def test_handshake_corrupted_message_2_fails() -> None:
    """Validate initiator processing tampered message 2 transitions to FAILED."""
    initiator, responder = _setup_sessions()

    msg1 = initiator.start_handshake()
    assert msg1 is not None
    msg2 = responder.process_handshake_message(msg1)
    assert msg2 is not None

    # Tamper message 2 bytes (MAC tag or ciphertext corrupted)
    tampered_msg2 = bytearray(msg2)
    tampered_msg2[-1] ^= 0xAA

    with pytest.raises(NoiseError):
        initiator.process_handshake_message(bytes(tampered_msg2))

    assert initiator.state == NoiseSessionState.FAILED


def test_handshake_corrupted_message_3_fails() -> None:
    """Validate responder processing tampered message 3 transitions to FAILED."""
    initiator, responder = _setup_sessions()

    msg1 = initiator.start_handshake()
    assert msg1 is not None
    msg2 = responder.process_handshake_message(msg1)
    assert msg2 is not None
    msg3 = initiator.process_handshake_message(msg2)
    assert msg3 is not None

    # Tamper message 3 bytes
    tampered_msg3 = bytearray(msg3)
    tampered_msg3[-1] ^= 0x55

    with pytest.raises(NoiseError):
        responder.process_handshake_message(bytes(tampered_msg3))

    assert responder.state == NoiseSessionState.FAILED


def test_handshake_calling_start_twice_raises_state_error() -> None:
    """Validate calling start_handshake twice on a session raises NoiseStateError."""
    initiator, _ = _setup_sessions()
    initiator.start_handshake()

    with pytest.raises(NoiseStateError, match="invalid state"):
        initiator.start_handshake()


def test_encrypt_before_handshake_established_raises_state_error() -> None:
    """Validate encrypt() called before handshake completion raises NoiseStateError."""
    initiator, _ = _setup_sessions()
    assert not initiator.is_established

    with pytest.raises(NoiseStateError, match="requires ESTABLISHED state"):
        initiator.encrypt(b"premature message")


def test_decrypt_before_handshake_established_raises_state_error() -> None:
    """Validate decrypt() called before handshake completion raises NoiseStateError."""
    initiator, _ = _setup_sessions()
    assert not initiator.is_established

    with pytest.raises(NoiseStateError, match="requires ESTABLISHED state"):
        initiator.decrypt(b"premature ciphertext")
