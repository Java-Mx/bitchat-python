"""Tests for bitchat.crypto.noise — Noise protocol state machine."""

from __future__ import annotations

import pytest

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import (
    NOISE_PROTOCOL_NAME,
    NoiseCipherState,
    NoiseHandshakeState,
    NoiseRole,
    NoiseSymmetricState,
    determine_handshake_role,
)
from bitchat.exceptions import (
    AuthenticationError,
    DecryptionError,
    NoiseError,
    NoiseStateError,
    ReplayError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_pair() -> tuple[NoiseHandshakeState, NoiseHandshakeState]:
    """Create a linked initiator/responder handshake pair for testing."""
    alice = LocalIdentity.generate()
    bob = LocalIdentity.generate()
    initiator = NoiseHandshakeState(NoiseRole.INITIATOR, alice.x25519_private)
    responder = NoiseHandshakeState(NoiseRole.RESPONDER, bob.x25519_private)
    return initiator, responder


def _complete_handshake(
    initiator: NoiseHandshakeState, responder: NoiseHandshakeState
) -> tuple[NoiseCipherState, NoiseCipherState, NoiseCipherState, NoiseCipherState]:
    """Run a complete XX handshake between two states.

    Returns (initiator_send, initiator_recv, responder_send, responder_recv).
    """
    # Message 1: Initiator → Responder
    msg1 = initiator.write_message(b"")
    responder.read_message(msg1)

    # Message 2: Responder → Initiator
    msg2 = responder.write_message(b"")
    initiator.read_message(msg2)

    # Message 3: Initiator → Responder
    msg3 = initiator.write_message(b"")
    responder.read_message(msg3)

    assert initiator.is_handshake_complete()
    assert responder.is_handshake_complete()

    i_send, i_recv = initiator.get_transport_ciphers()
    r_send, r_recv = responder.get_transport_ciphers()
    return i_send, i_recv, r_send, r_recv


# ---------------------------------------------------------------------------
# determine_handshake_role
# ---------------------------------------------------------------------------


class TestDetermineHandshakeRole:
    def test_lower_id_becomes_initiator(self) -> None:
        assert (
            determine_handshake_role("aabbccdd00000000", "ff00000000000000")
            == NoiseRole.INITIATOR
        )

    def test_higher_id_becomes_responder(self) -> None:
        assert (
            determine_handshake_role("ff00000000000000", "aabbccdd00000000")
            == NoiseRole.RESPONDER
        )

    def test_same_id_responder(self) -> None:
        # Same ID → not strictly less → Responder
        assert (
            determine_handshake_role("aabbccddee001122", "aabbccddee001122")
            == NoiseRole.RESPONDER
        )

    def test_empty_my_id_raises(self) -> None:
        with pytest.raises(ValueError):
            determine_handshake_role("", "aabbccdd")

    def test_empty_remote_id_raises(self) -> None:
        with pytest.raises(ValueError):
            determine_handshake_role("aabbccdd", "")


# ---------------------------------------------------------------------------
# NoiseCipherState
# ---------------------------------------------------------------------------


class TestNoiseCipherState:
    def test_no_key_encrypt_raises(self) -> None:
        cs = NoiseCipherState()
        with pytest.raises(NoiseStateError):
            cs.encrypt(b"data", b"")

    def test_no_key_decrypt_raises(self) -> None:
        cs = NoiseCipherState()
        with pytest.raises(NoiseStateError):
            cs.decrypt(b"\x00" * 20, b"")

    def test_has_key_false_initially(self) -> None:
        cs = NoiseCipherState()
        assert not cs.has_key()

    def test_has_key_true_after_initialize(self) -> None:
        cs = NoiseCipherState()
        cs.initialize_key(bytes(32))
        assert cs.has_key()

    def test_handshake_mode_encrypt_decrypt_round_trip(self) -> None:
        key = bytes(range(32))
        enc = NoiseCipherState(key, use_extracted_nonce=False)
        dec = NoiseCipherState(key, use_extracted_nonce=False)
        pt = b"handshake payload"
        ct = enc.encrypt(pt, b"aad")
        recovered = dec.decrypt(ct, b"aad")
        assert recovered == pt

    def test_transport_mode_encrypt_decrypt_round_trip(self) -> None:
        key = bytes(range(32))
        enc = NoiseCipherState(key, use_extracted_nonce=True)
        dec = NoiseCipherState(key, use_extracted_nonce=True)
        pt = b"transport message"
        ct = enc.encrypt(pt, b"")
        recovered = dec.decrypt(ct, b"")
        assert recovered == pt

    def test_transport_mode_nonce_prepended(self) -> None:
        key = bytes(32)
        cs = NoiseCipherState(key, use_extracted_nonce=True)
        ct = cs.encrypt(b"test", b"")
        # First 4 bytes must be nonce (counter=0 → [0,0,0,0])
        assert ct[:4] == b"\x00\x00\x00\x00"

    def test_nonce_increments_each_encrypt(self) -> None:
        key = bytes(32)
        enc = NoiseCipherState(key, use_extracted_nonce=True)
        ct0 = enc.encrypt(b"msg0", b"")
        ct1 = enc.encrypt(b"msg1", b"")
        # Nonce counter in first 4 bytes should differ
        assert ct0[:4] != ct1[:4]
        assert int.from_bytes(ct0[:4], "little") == 0
        assert int.from_bytes(ct1[:4], "little") == 1

    def test_wrong_aad_fails_authentication(self) -> None:
        key = bytes(32)
        enc = NoiseCipherState(key, use_extracted_nonce=False)
        dec = NoiseCipherState(key, use_extracted_nonce=False)
        ct = enc.encrypt(b"data", b"correct-aad")
        with pytest.raises(DecryptionError):
            dec.decrypt(ct, b"wrong-aad")

    def test_tampered_ciphertext_fails(self) -> None:
        key = bytes(32)
        enc = NoiseCipherState(key, use_extracted_nonce=True)
        dec = NoiseCipherState(key, use_extracted_nonce=True)
        ct = bytearray(enc.encrypt(b"data", b""))
        ct[4] ^= 0xFF  # flip byte in ciphertext after nonce prefix
        with pytest.raises(DecryptionError):
            dec.decrypt(bytes(ct), b"")


class TestReplayProtection:
    def _make_transport_pair(self) -> tuple[NoiseCipherState, NoiseCipherState]:
        key = bytes(range(32))
        enc = NoiseCipherState(key, use_extracted_nonce=True)
        dec = NoiseCipherState(key, use_extracted_nonce=True)
        return enc, dec

    def test_replay_same_ciphertext_rejected(self) -> None:
        enc, dec = self._make_transport_pair()
        ct = enc.encrypt(b"message", b"")
        # First decrypt succeeds (nonce=0, skipped per Rust behavior)
        dec.decrypt(ct, b"")
        # Second decrypt of same ct — counter should now be in window
        enc2, dec2 = self._make_transport_pair()
        ct2 = enc2.encrypt(b"msg1", b"")
        ct3 = enc2.encrypt(b"msg2", b"")
        dec2.decrypt(ct2, b"")
        dec2.decrypt(ct3, b"")
        # Replay ct3 — must be rejected
        with pytest.raises(ReplayError):
            dec2.decrypt(ct3, b"")

    def test_out_of_order_within_window_accepted(self) -> None:
        """Messages arriving slightly out of order should be accepted."""
        enc, dec = self._make_transport_pair()
        # Generate 5 messages
        messages = [enc.encrypt(f"msg{i}".encode(), b"") for i in range(5)]
        # Deliver out of order: 0, 2, 1, 4, 3
        order = [0, 2, 1, 4, 3]
        for i in order:
            dec.decrypt(messages[i], b"")  # Must not raise

    def test_very_old_message_outside_window_rejected(self) -> None:
        """Messages with nonce far behind the window must be rejected."""
        from bitchat.crypto.noise import NOISE_REPLAY_WINDOW_SIZE

        key = bytes(32)
        enc = NoiseCipherState(key, use_extracted_nonce=True)
        dec = NoiseCipherState(key, use_extracted_nonce=True)

        # Generate enough messages to advance the window
        messages = []
        for _ in range(NOISE_REPLAY_WINDOW_SIZE + 10):
            messages.append(enc.encrypt(b"x", b""))

        # Deliver the most recent messages to advance the receiver window
        for msg in messages[10:]:
            dec.decrypt(msg, b"")

        # Now try to deliver the first message (nonce=0 — skip check, Rust behavior)
        # Message at index 1 has nonce=1 which is outside window
        with pytest.raises(ReplayError):
            dec.decrypt(messages[1], b"")


# ---------------------------------------------------------------------------
# NoiseSymmetricState
# ---------------------------------------------------------------------------


class TestNoiseSymmetricState:
    def test_initial_hash_uses_protocol_name(self) -> None:
        """For names ≤32 bytes, hash is zero-padded name bytes."""
        name = "Noise_XX_25519_ChaChaPoly_SHA256"
        assert len(name) == 32
        ss = NoiseSymmetricState(name)
        expected_hash = name.encode("utf-8")  # exactly 32 bytes, no padding needed
        assert ss.get_handshake_hash() == expected_hash

    def test_mix_hash_changes_hash(self) -> None:
        ss = NoiseSymmetricState("test")
        h_before = ss.get_handshake_hash()
        ss.mix_hash(b"data")
        assert ss.get_handshake_hash() != h_before

    def test_mix_key_enables_cipher(self) -> None:
        ss = NoiseSymmetricState("test")
        assert not ss.has_cipher_key()
        ss.mix_key(bytes(32))
        assert ss.has_cipher_key()

    def test_encrypt_and_hash_without_key_returns_plaintext(self) -> None:
        ss = NoiseSymmetricState("test")
        pt = b"unencrypted"
        result = ss.encrypt_and_hash(pt)
        assert result == pt

    def test_encrypt_and_hash_with_key_returns_different_bytes(self) -> None:
        ss = NoiseSymmetricState("test")
        ss.mix_key(bytes(32))
        pt = b"encrypted"
        ct = ss.encrypt_and_hash(pt)
        assert ct != pt

    def test_decrypt_and_hash_without_key_returns_ciphertext(self) -> None:
        ss = NoiseSymmetricState("test")
        ct = b"passthrough"
        result = ss.decrypt_and_hash(ct)
        assert result == ct

    def test_split_returns_two_cipher_states(self) -> None:
        ss = NoiseSymmetricState(NOISE_PROTOCOL_NAME)
        c1, c2 = ss.split()
        assert c1.has_key()
        assert c2.has_key()


# ---------------------------------------------------------------------------
# Full Handshake
# ---------------------------------------------------------------------------


class TestNoiseXXHandshake:
    def test_complete_handshake_reaches_established(self) -> None:
        initiator, responder = _make_session_pair()
        msg1 = initiator.write_message(b"")
        responder.read_message(msg1)
        msg2 = responder.write_message(b"")
        initiator.read_message(msg2)
        msg3 = initiator.write_message(b"")
        responder.read_message(msg3)
        assert initiator.is_handshake_complete()
        assert responder.is_handshake_complete()

    def test_initiator_encrypt_responder_decrypt(self) -> None:
        initiator, responder = _make_session_pair()
        i_send, _i_recv, _r_send, r_recv = _complete_handshake(initiator, responder)
        pt = b"hello from initiator"
        ct = i_send.encrypt(pt, b"")
        recovered = r_recv.decrypt(ct, b"")
        assert recovered == pt

    def test_responder_encrypt_initiator_decrypt(self) -> None:
        initiator, responder = _make_session_pair()
        _i_send, i_recv, r_send, _r_recv = _complete_handshake(initiator, responder)
        pt = b"hello from responder"
        ct = r_send.encrypt(pt, b"")
        recovered = i_recv.decrypt(ct, b"")
        assert recovered == pt

    def test_bidirectional_multiple_messages(self) -> None:
        initiator, responder = _make_session_pair()
        i_send, i_recv, r_send, r_recv = _complete_handshake(initiator, responder)
        for i in range(10):
            pt = f"message {i}".encode()
            ct = i_send.encrypt(pt, b"")
            assert r_recv.decrypt(ct, b"") == pt
            ct2 = r_send.encrypt(pt, b"")
            assert i_recv.decrypt(ct2, b"") == pt

    def test_remote_static_key_authenticated(self) -> None:
        alice = LocalIdentity.generate()
        bob = LocalIdentity.generate()
        initiator = NoiseHandshakeState(NoiseRole.INITIATOR, alice.x25519_private)
        responder = NoiseHandshakeState(NoiseRole.RESPONDER, bob.x25519_private)

        msg1 = initiator.write_message(b"")
        responder.read_message(msg1)
        msg2 = responder.write_message(b"")
        initiator.read_message(msg2)
        msg3 = initiator.write_message(b"")
        responder.read_message(msg3)

        # Initiator should have Bob's static key
        assert initiator.get_remote_static_public_key() == bob.x25519_public
        # Responder should have Alice's static key
        assert responder.get_remote_static_public_key() == alice.x25519_public

    def test_handshake_hash_matches_both_sides(self) -> None:
        initiator, responder = _make_session_pair()
        msg1 = initiator.write_message(b"")
        responder.read_message(msg1)
        msg2 = responder.write_message(b"")
        initiator.read_message(msg2)
        msg3 = initiator.write_message(b"")
        responder.read_message(msg3)
        assert initiator.get_handshake_hash() == responder.get_handshake_hash()

    def test_tampered_handshake_message_fails(self) -> None:
        """Tampering a handshake message that contains encrypted content must fail.

        Message 1 (E-only) has no encrypted content — tampering the ephemeral
        key byte doesn't cause an auth failure.  Message 2 (E, EE, S, ES)
        contains the encrypted static key (S), tampering which causes
        AuthenticationError from decrypt_and_hash.
        """
        initiator, responder = _make_session_pair()

        # Complete message 1 exchange (E-only, no cipher)
        msg1 = initiator.write_message(b"")
        responder.read_message(msg1)

        # Message 2 from responder contains encrypted S key
        msg2 = responder.write_message(b"")
        # Tamper the encrypted static key portion (after 32-byte E key)
        # Message 2 layout: E(32) | S_encrypted(48) | ES_result | payload
        # The encrypted S key starts at offset 32
        tampered = bytearray(msg2)
        tampered[32] ^= 0xFF  # Flip a byte in the encrypted static key
        with pytest.raises((AuthenticationError, NoiseError)):
            initiator.read_message(bytes(tampered))

    def test_write_after_complete_raises(self) -> None:
        initiator, responder = _make_session_pair()
        _complete_handshake(initiator, responder)
        with pytest.raises(NoiseStateError):
            initiator.write_message(b"")

    def test_read_after_complete_raises(self) -> None:
        initiator, responder = _make_session_pair()
        _complete_handshake(initiator, responder)
        with pytest.raises(NoiseStateError):
            initiator.read_message(b"\x00" * 32)
