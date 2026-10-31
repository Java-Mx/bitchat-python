"""Tier 1: Feature Coverage — Cryptographic Identity & Noise XX Handshake."""

from __future__ import annotations

import pytest

from bitchat.crypto import ed25519
from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseRole, NoiseSessionState
from bitchat.crypto.sessions import NoiseSession
from bitchat.protocol.constants import SENDER_ID_SIZE


def test_local_identity_properties_and_redaction() -> None:
    """Validate LocalIdentity key sizes, fingerprint derivation, and secret redaction."""
    identity = LocalIdentity.generate()

    assert len(identity.x25519_private) == 32
    assert len(identity.x25519_public) == 32
    assert len(identity.ed25519_private) == 32
    assert len(identity.ed25519_public) == 32
    assert len(identity.peer_id) == SENDER_ID_SIZE
    assert len(identity.fingerprint) == 64  # SHA-256 hex string

    # Ensure private keys are never exposed in string representations
    repr_str = repr(identity)
    str_val = str(identity)

    assert identity.x25519_private.hex() not in repr_str
    assert identity.ed25519_private.hex() not in repr_str
    assert identity.x25519_private.hex() not in str_val
    assert identity.ed25519_private.hex() not in str_val


def test_identity_combined_public_key_layout() -> None:
    """Validate 96-byte combined public key structure."""
    identity = LocalIdentity.generate()
    combined = identity.combined_public_key

    assert len(combined) == 96
    # Slices: x25519(32) || ed25519(32) || ed25519(32)
    assert combined[:32] == identity.x25519_public
    assert combined[32:64] == identity.ed25519_public
    assert combined[64:96] == identity.ed25519_public


def test_ed25519_sign_and_verify_packet_data() -> None:
    """Validate Ed25519 digital signature signing and verification."""
    from bitchat.exceptions import SignatureVerificationError

    identity = LocalIdentity.generate()
    payload = b"BitChat protocol authentication and non-repudiation payload"

    sig = ed25519.sign(identity.ed25519_private, payload)
    assert len(sig) == 64

    # Verification success (verify raises SignatureVerificationError if invalid)
    ed25519.verify(identity.ed25519_public, sig, payload)

    # Verification failure on tampered message
    tampered = payload + b"!"
    with pytest.raises(SignatureVerificationError):
        ed25519.verify(identity.ed25519_public, sig, tampered)

    # Verification failure on tampered signature
    bad_sig = bytearray(sig)
    bad_sig[0] ^= 0xFF
    with pytest.raises(SignatureVerificationError):
        ed25519.verify(identity.ed25519_public, bytes(bad_sig), payload)


def test_noise_xx_three_message_handshake_exchange() -> None:
    """Validate complete 3-message Noise XX handshake state machine."""
    alice_id = LocalIdentity.generate()
    bob_id = LocalIdentity.generate()

    # Deterministic roles based on determine_handshake_role
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

    assert not initiator.is_established
    assert not responder.is_established
    assert initiator.state == NoiseSessionState.UNINITIALIZED
    assert responder.state == NoiseSessionState.UNINITIALIZED

    # Message 1: Initiator -> Responder
    msg1 = initiator.start_handshake()
    assert msg1 is not None
    assert initiator.state == NoiseSessionState.HANDSHAKING

    # Responder processes Message 1 and generates Message 2
    msg2 = responder.process_handshake_message(msg1)
    assert msg2 is not None
    assert responder.state == NoiseSessionState.HANDSHAKING

    # Initiator processes Message 2 and generates Message 3
    msg3 = initiator.process_handshake_message(msg2)
    assert msg3 is not None
    assert initiator.is_established
    assert initiator.state == NoiseSessionState.ESTABLISHED

    # Responder processes Message 3
    responder.process_handshake_message(msg3)
    assert responder.is_established
    assert responder.state == NoiseSessionState.ESTABLISHED


def test_noise_session_fingerprints_match_peers() -> None:
    """Validate remote public fingerprints computed after handshake match peer identities."""
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

    msg1 = initiator.start_handshake()
    assert msg1 is not None
    msg2 = responder.process_handshake_message(msg1)
    assert msg2 is not None
    msg3 = initiator.process_handshake_message(msg2)
    assert msg3 is not None
    responder.process_handshake_message(msg3)

    assert alice_session.remote_fingerprint == bob_id.fingerprint
    assert bob_session.remote_fingerprint == alice_id.fingerprint


def test_handshake_transport_encryption_roundtrip() -> None:
    """Validate bidirectional transport encryption between established Noise sessions."""
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

    m1 = initiator.start_handshake()
    assert m1 is not None
    m2 = responder.process_handshake_message(m1)
    assert m2 is not None
    m3 = initiator.process_handshake_message(m2)
    assert m3 is not None
    responder.process_handshake_message(m3)

    # Alice -> Bob
    alice_msg = b"Hello Bob from Alice via Noise transport"
    ciphertext_ab = alice_session.encrypt(alice_msg)
    plaintext_bob = bob_session.decrypt(ciphertext_ab)
    assert plaintext_bob == alice_msg

    # Bob -> Alice
    bob_msg = b"Hello Alice, loud and clear"
    ciphertext_ba = bob_session.encrypt(bob_msg)
    plaintext_alice = alice_session.decrypt(ciphertext_ba)
    assert plaintext_alice == bob_msg
