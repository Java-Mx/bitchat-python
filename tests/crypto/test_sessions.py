"""Tests for bitchat.crypto.sessions — NoiseSession high-level abstraction."""

from __future__ import annotations

import pytest

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import (
    DecryptionError,
    NoiseStateError,
    ReplayError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_pair() -> tuple[NoiseSession, NoiseSession]:
    """Create Alice (initiator) and Bob (responder) sessions."""
    alice = LocalIdentity.generate()
    bob = LocalIdentity.generate()
    # Force Alice to be initiator by using peer IDs that satisfy the tie-break
    alice_id = "0000000000000000"  # Always lower
    bob_id = "ffffffffffffffff"  # Always higher
    # Override peer IDs by using custom identities with known hex IDs
    # We'll just set remote peer IDs such that the role is deterministic
    session_a = NoiseSession(alice, bob_id)  # alice_id < bob_id → initiator
    session_b = NoiseSession(bob, alice_id)  # bob_id > alice_id → responder

    # Verify roles
    assert session_a.role == NoiseRole.INITIATOR
    assert session_b.role == NoiseRole.RESPONDER
    return session_a, session_b


def _complete_handshake(session_a: NoiseSession, session_b: NoiseSession) -> None:
    """Run a complete XX handshake between two NoiseSession instances."""
    msg1 = session_a.start_handshake()
    assert msg1 is not None

    response1 = session_b.process_handshake_message(msg1)
    assert response1 is not None

    response2 = session_a.process_handshake_message(response1)
    assert response2 is not None

    final = session_b.process_handshake_message(response2)
    assert final is None  # No more messages needed

    assert session_a.state == NoiseSessionState.ESTABLISHED
    assert session_b.state == NoiseSessionState.ESTABLISHED


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


class TestNoiseSessionStateMachine:
    def test_initial_state_is_uninitialized(self) -> None:
        alice = LocalIdentity.generate()
        session = NoiseSession(alice, "ffffffffffffffff")
        assert session.state == NoiseSessionState.UNINITIALIZED

    def test_start_handshake_transitions_to_handshaking(self) -> None:
        alice = LocalIdentity.generate()
        session = NoiseSession(alice, "ffffffffffffffff")
        session.start_handshake()
        assert session.state == NoiseSessionState.HANDSHAKING

    def test_start_handshake_twice_raises(self) -> None:
        alice = LocalIdentity.generate()
        session = NoiseSession(alice, "ffffffffffffffff")
        session.start_handshake()
        with pytest.raises(NoiseStateError):
            session.start_handshake()

    def test_encrypt_before_established_raises(self) -> None:
        alice = LocalIdentity.generate()
        session = NoiseSession(alice, "ffffffffffffffff")
        with pytest.raises(NoiseStateError):
            session.encrypt(b"data")

    def test_decrypt_before_established_raises(self) -> None:
        alice = LocalIdentity.generate()
        session = NoiseSession(alice, "ffffffffffffffff")
        with pytest.raises(NoiseStateError):
            session.decrypt(b"\x00" * 20)

    def test_close_transitions_to_closed(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        session_a.close()
        assert session_a.state == NoiseSessionState.CLOSED

    def test_encrypt_after_close_raises(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        session_a.close()
        with pytest.raises(NoiseStateError):
            session_a.encrypt(b"data")

    def test_decrypt_after_close_raises(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        ct = session_b.encrypt(b"data")
        session_a.close()
        with pytest.raises(NoiseStateError):
            session_a.decrypt(ct)


# ---------------------------------------------------------------------------
# Full handshake and transport
# ---------------------------------------------------------------------------


class TestNoiseSessionHandshake:
    def test_complete_handshake_both_established(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        assert session_a.is_established
        assert session_b.is_established

    def test_a_encrypts_b_decrypts(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        pt = b"hello from alice"
        ct = session_a.encrypt(pt)
        recovered = session_b.decrypt(ct)
        assert recovered == pt

    def test_b_encrypts_a_decrypts(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        pt = b"hello from bob"
        ct = session_b.encrypt(pt)
        recovered = session_a.decrypt(ct)
        assert recovered == pt

    def test_bidirectional_many_messages(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        for i in range(20):
            pt = f"message {i}".encode()
            assert session_b.decrypt(session_a.encrypt(pt)) == pt
            assert session_a.decrypt(session_b.encrypt(pt)) == pt

    def test_empty_message(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        ct = session_a.encrypt(b"")
        assert session_b.decrypt(ct) == b""

    def test_remote_fingerprint_available_after_handshake(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        assert session_a.remote_fingerprint is not None
        assert len(session_a.remote_fingerprint) == 64
        assert session_b.remote_fingerprint is not None
        assert len(session_b.remote_fingerprint) == 64

    def test_handshake_hash_available_after_handshake(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        assert session_a.handshake_hash is not None
        assert len(session_a.handshake_hash) == 32
        # Both sides should agree on the handshake hash
        assert session_a.handshake_hash == session_b.handshake_hash


# ---------------------------------------------------------------------------
# Responder auto-init
# ---------------------------------------------------------------------------


class TestResponderAutoInit:
    def test_responder_starts_from_uninitialized_on_first_message(self) -> None:
        """Responder can process the first message without calling start_handshake."""
        alice = LocalIdentity.generate()
        bob = LocalIdentity.generate()
        # Alice is initiator
        session_a = NoiseSession(alice, "ffffffffffffffff")
        session_b = NoiseSession(bob, "0000000000000000")

        msg1 = session_a.start_handshake()
        assert msg1 is not None

        # Bob hasn't called start_handshake but process_handshake_message works
        response1 = session_b.process_handshake_message(msg1)
        assert response1 is not None
        assert session_b.state == NoiseSessionState.HANDSHAKING


# ---------------------------------------------------------------------------
# Security — tampered messages
# ---------------------------------------------------------------------------


class TestNoiseSessionSecurity:
    def test_tampered_ciphertext_raises(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        ct = bytearray(session_a.encrypt(b"secret data"))
        ct[4] ^= 0xFF
        with pytest.raises(DecryptionError):
            session_b.decrypt(bytes(ct))

    def test_replay_attack_raises(self) -> None:
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        # Generate two messages to advance past nonce=0
        ct0 = session_a.encrypt(b"msg0")
        ct1 = session_a.encrypt(b"msg1")
        session_b.decrypt(ct0)
        session_b.decrypt(ct1)
        with pytest.raises(ReplayError):
            session_b.decrypt(ct1)  # Replay

    def test_no_plaintext_fallback_on_auth_failure(self) -> None:
        """Authentication failure must never silently return data."""
        session_a, session_b = _make_session_pair()
        _complete_handshake(session_a, session_b)
        ct = bytearray(session_a.encrypt(b"sensitive"))
        ct[-1] ^= 0x01  # Corrupt tag
        with pytest.raises(DecryptionError):
            result = session_b.decrypt(bytes(ct))
            # If we get here, the result must not be the original plaintext
            assert result != b"sensitive"

    def test_cross_session_ciphertext_rejected(self) -> None:
        """Ciphertext from session 1 must be rejected by session 2."""
        session_a1, session_b1 = _make_session_pair()
        session_a2, session_b2 = _make_session_pair()
        _complete_handshake(session_a1, session_b1)
        _complete_handshake(session_a2, session_b2)

        ct_from_1 = session_a1.encrypt(b"session1 message")
        with pytest.raises(DecryptionError):
            session_b2.decrypt(ct_from_1)
