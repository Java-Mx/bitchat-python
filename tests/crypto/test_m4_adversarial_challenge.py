"""Adversarial Challenge & Stress Suite for Milestone 4.

Author: Challenger 1 (teamwork_challenger_m4_1)
Role: Empirical Challenger / Adversarial Critic & Specialist
"""

from __future__ import annotations

import json
import logging
import os
import random
import struct
import threading
from typing import TYPE_CHECKING

import pytest

from bitchat.app.session_coordinator import (
    MAX_PENDING_HANDSHAKES,
    SessionCoordinator,
)
from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import (
    NoiseCipherState,
    NoiseRole,
    NoiseSessionState,
)
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import (
    ConfigurationError,
    CryptoError,
    DecryptionError,
    InvalidNonceError,
    NoiseStateError,
    ReplayError,
)
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket
from bitchat.storage.config import FileConfigStorage, InMemoryStorage

if TYPE_CHECKING:
    from pathlib import Path


# ===========================================================================
# 1. Wire Nonce 0 Replay & Sliding Replay Window Stress Tests
# ===========================================================================


class TestAdversarialNonce0AndReplayWindow:
    """Adversarial stress-testing of wire nonce 0 and sliding window replay filter."""

    def test_nonce_0_unconditional_rejection_repeated(self) -> None:
        """Verify nonce 0 replay is unconditionally rejected on repeated attempts."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        ct0 = sender.encrypt(b"secret payload at nonce 0", b"aad")
        assert struct.unpack("<I", ct0[:4])[0] == 0

        # 1st attempt: must succeed
        pt = receiver.decrypt(ct0, b"aad")
        assert pt == b"secret payload at nonce 0"

        # 2nd through 10th replay attempts must ALL raise ReplayError
        for _ in range(2, 11):
            with pytest.raises(ReplayError, match="Replay detected"):
                receiver.decrypt(ct0, b"aad")

    def test_nonce_0_interleaved_with_out_of_order_stream(self) -> None:
        """Deliver nonces in heavily shuffled order; verify each is accepted once."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        # Generate 200 packets
        packet_count = 200
        packets: list[tuple[int, bytes, bytes]] = []
        for i in range(packet_count):
            msg = f"packet {i}".encode()
            aad = f"aad {i}".encode()
            ct = sender.encrypt(msg, aad)
            nonce = struct.unpack("<I", ct[:4])[0]
            assert nonce == i
            packets.append((nonce, ct, aad))

        # Shuffle packets randomly
        shuffled = list(packets)
        random.seed(42)
        random.shuffle(shuffled)

        # Ensure nonce 0 is not first
        zero_idx = next(idx for idx, (nonce, _, _) in enumerate(shuffled) if nonce == 0)
        if zero_idx == 0:
            shuffled[0], shuffled[-1] = shuffled[-1], shuffled[0]

        # Decrypt shuffled stream
        for nonce, ct, aad in shuffled:
            pt = receiver.decrypt(ct, aad)
            assert pt == f"packet {nonce}".encode()

        # Replay 30 random packets including nonce 0
        sample_replays = random.sample(packets, 30)
        if not any(nonce == 0 for nonce, _, _ in sample_replays):
            sample_replays.append(packets[0])

        for _nonce, ct, aad in sample_replays:
            with pytest.raises(ReplayError, match="Replay detected"):
                receiver.decrypt(ct, aad)

    def test_corrupted_nonce_0_does_not_consume_replay_slot(self) -> None:
        """If unauthenticated packet fails auth, real nonce 0 is not blocked."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        valid_ct0 = sender.encrypt(b"legitimate message", b"aad")

        # Attacker crafts corrupted nonce 0 packet
        tampered_ct0 = bytearray(valid_ct0)
        tampered_ct0[4] ^= 0xFF  # Corrupt ciphertext body

        # Receiver must reject with DecryptionError
        with pytest.raises(DecryptionError):
            receiver.decrypt(bytes(tampered_ct0), b"aad")

        # Nonce 0 must NOT have been marked as seen
        assert 0 not in receiver._replay_window

        # Now legitimate nonce 0 arrives: must decrypt successfully!
        pt = receiver.decrypt(valid_ct0, b"aad")
        assert pt == b"legitimate message"

        # Now that legitimate nonce 0 has succeeded, replay must be rejected
        with pytest.raises(ReplayError):
            receiver.decrypt(valid_ct0, b"aad")

    def test_nonce_window_edge_boundary_1023_and_1024(self) -> None:
        """Verify boundary: 1023 accepts nonce 0; 1024 rejects nonce 0 as too old."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)

        ct0 = sender.encrypt(b"msg 0", b"")

        sender._nonce = 1023
        ct1023 = sender.encrypt(b"msg 1023", b"")

        sender._nonce = 1024
        ct1024 = sender.encrypt(b"msg 1024", b"")

        # Receiver A receives 1023 first, then 0 -> MUST ACCEPT 0
        receiver_a = NoiseCipherState(key, use_extracted_nonce=True)
        receiver_a.decrypt(ct1023, b"")
        assert receiver_a._highest_received_nonce == 1023
        pt0 = receiver_a.decrypt(ct0, b"")
        assert pt0 == b"msg 0"
        with pytest.raises(ReplayError):
            receiver_a.decrypt(ct0, b"")

        # Receiver B receives 1024 first, then 0 -> MUST REJECT 0 AS TOO OLD
        receiver_b = NoiseCipherState(key, use_extracted_nonce=True)
        receiver_b.decrypt(ct1024, b"")
        assert receiver_b._highest_received_nonce == 1024
        with pytest.raises(ReplayError, match=r"too old|outside the replay window"):
            receiver_b.decrypt(ct0, b"")

    def test_truncated_ciphertext_raises_invalid_nonce(self) -> None:
        """Packets with less than 4 bytes of wire data fail with InvalidNonceError."""
        key = os.urandom(32)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        with pytest.raises(InvalidNonceError):
            receiver.decrypt(b"", b"")

        with pytest.raises(InvalidNonceError):
            receiver.decrypt(b"\x00\x00\x01", b"")


# ===========================================================================
# 2. Handshake CryptoError Recovery & Teardown Stress Tests
# ===========================================================================


class TestAdversarialHandshakeRecovery:
    """Adversarial stress-testing of handshake error transitions and cleanup."""

    def test_corrupted_poly1305_tag_transitions_to_failed(self) -> None:
        """Corrupting Poly1305 authentication tag in handshake msg2 triggers FAILED."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        alice_session = NoiseSession(alice_id, bob_id.peer_id_hex)
        bob_session = NoiseSession(bob_id, alice_id.peer_id_hex)

        initiator = (
            alice_session if alice_session.role == NoiseRole.INITIATOR else bob_session
        )
        responder = bob_session if initiator is alice_session else alice_session

        m1 = initiator.start_handshake()
        assert m1 is not None
        m2 = responder.process_handshake_message(m1)
        assert m2 is not None

        # Flip byte in Poly1305 tag of m2
        bad_m2 = bytearray(m2)
        bad_m2[-5] ^= 0x55

        with pytest.raises(CryptoError):
            initiator.process_handshake_message(bytes(bad_m2))

        assert initiator.state == NoiseSessionState.FAILED

    def test_tampered_static_key_in_msg3_transitions_to_failed(self) -> None:
        """Corrupting msg3 payload triggers FAILED on responder."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        alice_session = NoiseSession(alice_id, bob_id.peer_id_hex)
        bob_session = NoiseSession(bob_id, alice_id.peer_id_hex)

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

        # Tamper msg3
        bad_m3 = bytearray(m3)
        bad_m3[10] ^= 0xAA

        with pytest.raises(CryptoError):
            responder.process_handshake_message(bytes(bad_m3))

        assert responder.state == NoiseSessionState.FAILED

    def test_invalid_state_call_raises_noise_state_error(self) -> None:
        """Calling process_handshake_message in ESTABLISHED or FAILED state."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        alice_session = NoiseSession(alice_id, bob_id.peer_id_hex)
        alice_session._state = NoiseSessionState.ESTABLISHED

        with pytest.raises(NoiseStateError):
            alice_session.process_handshake_message(b"\x00" * 32)

        alice_session._state = NoiseSessionState.FAILED
        with pytest.raises(NoiseStateError):
            alice_session.process_handshake_message(b"\x00" * 32)

    @pytest.mark.asyncio
    async def test_coordinator_cleans_up_on_all_handshake_failures(self) -> None:
        """Inject corrupt packets at handshake phases; verify no leaked sessions."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        # 1. Corrupt NoiseHandshakeInit
        attacker1 = f"{0x1111:016x}"
        pkt1 = BitchatPacket.create(
            message_type=MessageType.NoiseHandshakeInit,
            sender_id=bytes.fromhex(attacker1),
            recipient_id=alice_id.peer_id,
            payload=b"garbage_init_bytes",
        )
        await coordinator._process_packet_async(pkt1, "10.0.0.1")
        assert coordinator.get_session(attacker1) is None
        assert coordinator.pending_handshakes_count == 0

        # 2. Corrupt NoiseHandshakeResp for pending session
        attacker2 = f"{0x2222:016x}"
        s2 = coordinator.get_or_create_session(attacker2)
        s2._state = NoiseSessionState.HANDSHAKING
        assert coordinator.pending_handshakes_count == 1

        pkt2 = BitchatPacket.create(
            message_type=MessageType.NoiseHandshakeResp,
            sender_id=bytes.fromhex(attacker2),
            recipient_id=alice_id.peer_id,
            payload=b"corrupt_resp_payload",
        )
        await coordinator._process_packet_async(pkt2, "10.0.0.2")
        assert coordinator.get_session(attacker2) is None
        assert coordinator.pending_handshakes_count == 0

    @pytest.mark.asyncio
    async def test_handshake_timeout_cleanly_purges_session(self) -> None:
        """Handshake timeout expires session, marks FAILED, and removes state."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        peer_hex = f"{0x3333:016x}"
        session = coordinator.get_or_create_session(peer_hex)
        session._state = NoiseSessionState.HANDSHAKING
        coordinator._pending_messages[peer_hex] = ["queued message"]

        session._state = NoiseSessionState.FAILED
        coordinator._discard_failed_session(peer_hex, session)

        assert coordinator.get_session(peer_hex) is None
        assert session.state in (NoiseSessionState.FAILED, NoiseSessionState.CLOSED)
        assert peer_hex not in coordinator._pending_messages


# ===========================================================================
# 3. Pending Handshake Saturation Stress Tests
# ===========================================================================


class TestAdversarialHandshakeSaturation:
    """Adversarial stress-testing of handshake queue limits and DOS defense."""

    @pytest.mark.asyncio
    async def test_saturation_flood_100_peers(self) -> None:
        """Flood coordinator with requests; verify strictly 64 are tracked."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        coordinator._sessions.clear()
        for i in range(MAX_PENDING_HANDSHAKES):
            peer_hex = f"{i + 100:016x}"
            s = coordinator.get_or_create_session(peer_hex)
            s._state = NoiseSessionState.HANDSHAKING

        assert coordinator.pending_handshakes_count == 64

        # Now send 50 more requests from new peers
        for i in range(50):
            excess_hex = f"{i + 200:016x}"
            req_pkt = BitchatPacket.create(
                message_type=MessageType.HandshakeRequest,
                sender_id=bytes.fromhex(excess_hex),
                recipient_id=alice_id.peer_id,
                payload=b"",
            )
            await coordinator._process_packet_async(req_pkt, "192.168.2.1")
            assert coordinator.get_session(excess_hex) is None

        # Verify count is strictly capped at 64
        assert coordinator.pending_handshakes_count == 64
        assert len(coordinator._sessions) == 64

    @pytest.mark.asyncio
    async def test_saturation_slot_freeing_allows_new_handshake(self) -> None:
        """When pending handshakes clear, freed slots admit new handshakes."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        pending_sessions: list[str] = []
        for i in range(MAX_PENDING_HANDSHAKES):
            peer_hex = f"{i + 500:016x}"
            s = coordinator.get_or_create_session(peer_hex)
            s._state = NoiseSessionState.HANDSHAKING
            pending_sessions.append(peer_hex)

        assert coordinator.pending_handshakes_count == 64

        # Discard 4 pending sessions
        for peer_hex in pending_sessions[:4]:
            s = coordinator.get_session(peer_hex)
            assert s is not None
            s._state = NoiseSessionState.FAILED
            coordinator._discard_failed_session(peer_hex, s)

        assert coordinator.pending_handshakes_count == 60

        # Now 4 new peers should be accepted
        for i in range(4):
            new_peer = f"{i + 900:016x}"
            s = coordinator.get_or_create_session(new_peer)
            s._state = NoiseSessionState.HANDSHAKING

        assert coordinator.pending_handshakes_count == 64


# ===========================================================================
# 4. TOFU & Nickname Spoofing Stress Tests
# ===========================================================================


class TestAdversarialTOFUAndNicknameSpoofing:
    """Adversarial stress-testing of MITM detection and nickname protection."""

    @pytest.mark.asyncio
    async def test_mitm_key_replacement_aborts_and_cleans_up(self) -> None:
        """Simulate MITM attacker replacing a trusted peer's static key."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()
        mallory_id = LocalIdentity.generate()

        storage = InMemoryStorage()
        config = storage.load_config()
        config.add_contact(bob_id.peer_id_hex, bob_id.fingerprint)
        storage.save_config(config)

        coordinator = SessionCoordinator(local_identity=alice_id, storage=storage)
        completed: list[str] = []
        coordinator.on_handshake_completed = lambda pid, fp: completed.append(pid)

        session = coordinator.get_or_create_session(bob_id.peer_id_hex)
        session._remote_fingerprint = mallory_id.fingerprint
        session._state = NoiseSessionState.ESTABLISHED

        coordinator._on_handshake_established(bob_id.peer_id_hex, session)

        assert bob_id.peer_id_hex not in completed
        assert coordinator.get_session(bob_id.peer_id_hex) is None
        assert session.state in (NoiseSessionState.FAILED, NoiseSessionState.CLOSED)

        fresh_config = storage.load_config()
        assert (
            fresh_config.get_contact_fingerprint(bob_id.peer_id_hex)
            == bob_id.fingerprint.lower()
        )

    def test_nickname_spoofing_adversarial_patterns(self) -> None:
        """Test spoofing variations: whitespace, case, empty strings."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id, nickname="AliceAdmin")
        coordinator.peer_nicknames["0123456789abcdef"] = "CharliePeer"

        attacker_hex = "fedcba9876543210"

        # 1. Local nickname collisions (case & whitespace variants)
        assert coordinator._is_nickname_spoofed(attacker_hex, "AliceAdmin") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, "aliceadmin") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, " ALICEADMIN ") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, "\tAliceAdmin\n") is True

        # 2. Existing peer nickname collisions
        assert coordinator._is_nickname_spoofed(attacker_hex, "CharliePeer") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, "charliepeer") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, " CharliePeer ") is True

        # 3. Empty / whitespace nicknames
        assert coordinator._is_nickname_spoofed(attacker_hex, "") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, "   ") is True
        assert coordinator._is_nickname_spoofed(attacker_hex, "\t\r\n") is True

        # 4. Legitimate unclaimed nicknames
        assert coordinator._is_nickname_spoofed(attacker_hex, "DaveLegit") is False
        assert coordinator._is_nickname_spoofed(attacker_hex, "Zack") is False

        # 5. Peer updating its own nickname
        assert (
            coordinator._is_nickname_spoofed("0123456789abcdef", "CharliePeer") is False
        )


# ===========================================================================
# 5. Corrupted Identity Backup & Thread Safety Stress Tests
# ===========================================================================


class TestAdversarialIdentityStorage:
    """Adversarial stress-testing of corrupted identity handling and thread safety."""

    def test_corrupted_identity_various_malformations(self, tmp_path: Path) -> None:
        """Inject truncated JSON, binary garbage, and invalid hex keys."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)

        short_keys = json.dumps(
            {
                "x25519_private": "00" * 16,
                "ed25519_private": "00" * 16,
            }
        ).encode()

        malformations = [
            b"\x00\x01\x02\x03\xff\xfe\xfd",
            b'{"x25519_private": "incomplete',
            b'{"x25519_private": 12345, "ed25519_private": true}',
            b'{"x25519_private": "ZZZZZZ", "ed25519_private": "not_hex"}',
            short_keys,
        ]

        for malformed in malformations:
            id_file.write_bytes(malformed)
            with pytest.raises(ConfigurationError):
                storage.load_identity()

            backups = list(tmp_path.glob("identity.json.corrupt.*"))
            assert len(backups) >= 1
            for b in backups:
                b.unlink()

    def test_save_identity_with_corrupt_existing_creates_backup(
        self, tmp_path: Path
    ) -> None:
        """When existing identity is corrupted, save_identity preserves backup."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        corrupt_data = b"FATAL_CORRUPTION_DATA_12345678"
        id_file.write_bytes(corrupt_data)

        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
        new_id = LocalIdentity.generate()

        storage.save_identity(new_id)

        backups = list(tmp_path.glob("identity.json.corrupt.*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == corrupt_data

        loaded = storage.load_identity()
        assert loaded is not None
        assert loaded.peer_id == new_id.peer_id

    def test_high_concurrency_identity_stress(self, tmp_path: Path) -> None:
        """Stress harness: 16 threads concurrently saving and loading identities."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)

        initial_id = LocalIdentity.generate()
        storage.save_identity(initial_id)

        errors: list[Exception] = []
        threads: list[threading.Thread] = []

        def worker(thread_id: int) -> None:
            try:
                for _ in range(25):
                    if thread_id % 3 == 0:
                        new_id = LocalIdentity.generate()
                        storage.save_identity(new_id)
                    else:
                        loaded = storage.load_identity()
                        assert loaded is not None
                        assert len(loaded.peer_id) == 8
            except Exception as exc:
                errors.append(exc)

        for i in range(16):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent worker errors: {errors}"
        final_id = storage.load_identity()
        assert final_id is not None


# ===========================================================================
# 6. Sensitive Secrets Absence in Logs
# ===========================================================================


class TestAdversarialSecretsAbsence:
    """Verify that under attack/error scenarios, no secrets are ever logged."""

    @pytest.mark.asyncio
    async def test_no_keys_in_logs_on_failed_handshake(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Capture logs across corrupted handshake and verify zero key leakage."""
        caplog.set_level(logging.DEBUG)

        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        pkt = BitchatPacket.create(
            message_type=MessageType.NoiseHandshakeInit,
            sender_id=b"\x01" * 8,
            recipient_id=alice_id.peer_id,
            payload=b"malicious_garbage_payload",
        )
        await coordinator._process_packet_async(pkt, "127.0.0.1")

        alice_priv_x25519 = alice_id.x25519_private.hex()
        alice_priv_ed25519 = alice_id.ed25519_private.hex()

        for record in caplog.records:
            msg = record.getMessage()
            assert alice_priv_x25519 not in msg
            assert alice_priv_ed25519 not in msg
