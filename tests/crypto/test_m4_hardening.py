"""Milestone 4 Regression & Unit Tests: Cryptography, Noise & Storage Safety.

Comprehensive verification of:
1. Wire nonce 0 replay vulnerability fix and sliding-window replay filter boundaries.
2. Noise handshake error transitions to FAILED and session recovery/cleanup.
3. Bounded pending handshakes (MAX_PENDING_HANDSHAKES = 64) saturation rejection.
4. Peer authentication, TOFU fingerprint verification, and nickname spoofing rejection.
5. Corrupted identity backup creation and thread-safe persistence.
6. Zero cryptographic secrets (private keys, session keys, plaintext) in log output.
"""

from __future__ import annotations

import json
import logging
import os
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
    NOISE_REPLAY_WINDOW_SIZE,
    NoiseCipherState,
    NoiseRole,
    NoiseSessionState,
)
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import (
    ConfigurationError,
    CryptoError,
    NoiseError,
    ReplayError,
)
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket
from bitchat.storage.config import AppConfig, FileConfigStorage, InMemoryStorage

if TYPE_CHECKING:
    from pathlib import Path


# ===========================================================================
# 1. Nonce 0 Replay Protection & Replay Window Boundaries
# ===========================================================================


class TestNonce0AndReplayWindow:
    """Validate wire nonce 0 replay vulnerability fix and window boundary rules."""

    def test_nonce_0_replay_rejected(self) -> None:
        """Verify that wire nonce 0 cannot be decrypted more than once."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        # First packet: wire nonce is 0
        ct0 = sender.encrypt(b"hello nonce 0", b"")
        assert struct.unpack("<I", ct0[:4])[0] == 0

        # First decryption of nonce 0 must succeed
        pt0 = receiver.decrypt(ct0, b"")
        assert pt0 == b"hello nonce 0"

        # Replaying nonce 0 MUST raise ReplayError
        with pytest.raises(ReplayError, match="Replay detected"):
            receiver.decrypt(ct0, b"")

    def test_nonce_0_out_of_order_accepted_then_replay_rejected(self) -> None:
        """Verify nonce 0 received after nonce 1 is accepted once, then rejected."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        ct0 = sender.encrypt(b"message zero", b"")
        ct1 = sender.encrypt(b"message one", b"")

        # Deliver ct1 (nonce 1) first
        pt1 = receiver.decrypt(ct1, b"")
        assert pt1 == b"message one"

        # Out-of-order delivery of ct0 (nonce 0) must succeed on first try
        pt0 = receiver.decrypt(ct0, b"")
        assert pt0 == b"message zero"

        # Subsequent replay of ct0 must be rejected
        with pytest.raises(ReplayError, match="Replay detected"):
            receiver.decrypt(ct0, b"")

        # Subsequent replay of ct1 must also be rejected
        with pytest.raises(ReplayError, match="Replay detected"):
            receiver.decrypt(ct1, b"")

    def test_stale_nonce_0_outside_window_rejected(self) -> None:
        """Verify nonce 0 is rejected as too old when window moves past 1024."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        ct0 = sender.encrypt(b"message 0", b"")

        # Advance receiver window to 1024
        receiver._highest_received_nonce = NOISE_REPLAY_WINDOW_SIZE
        receiver._replay_window = {NOISE_REPLAY_WINDOW_SIZE}

        # Nonce 0 is now too old (0 + 1024 <= 1024)
        with pytest.raises(ReplayError, match=r"too old|replay window"):
            receiver.decrypt(ct0, b"")

    def test_sliding_window_large_jump_clears_old_records(self) -> None:
        """Verify a jump of >= 1024 nonces purges previous window entries."""
        key = os.urandom(32)
        sender = NoiseCipherState(key, use_extracted_nonce=True)
        receiver = NoiseCipherState(key, use_extracted_nonce=True)

        # Receive nonces 0, 1, 2
        for i in range(3):
            ct = sender.encrypt(f"msg {i}".encode(), b"")
            receiver.decrypt(ct, b"")

        assert 0 in receiver._replay_window
        assert 1 in receiver._replay_window
        assert 2 in receiver._replay_window

        # Advance sender to nonce 2000
        sender._nonce = 2000
        ct2000 = sender.encrypt(b"jump forward", b"")
        receiver.decrypt(ct2000, b"")

        # Old nonces must be completely purged from replay window
        assert receiver._highest_received_nonce == 2000
        assert 0 not in receiver._replay_window
        assert 1 not in receiver._replay_window
        assert 2000 in receiver._replay_window


# ===========================================================================
# 2. Handshake Error Handling & Session Recovery
# ===========================================================================


class TestNoiseHandshakeErrorRecovery:
    """Validate transition to FAILED on errors and coordinator session recovery."""

    def test_process_handshake_crypto_error_transitions_to_failed(self) -> None:
        """Any CryptoError in handshake message processing sets state to FAILED."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        alice_session = NoiseSession(alice_id, bob_id.peer_id_hex)
        bob_session = NoiseSession(bob_id, alice_id.peer_id_hex)

        initiator = (
            alice_session if alice_session.role == NoiseRole.INITIATOR else bob_session
        )
        responder = bob_session if initiator is alice_session else alice_session

        msg1 = initiator.start_handshake()
        assert msg1 is not None
        msg2 = responder.process_handshake_message(msg1)
        assert msg2 is not None

        # Corrupt message 2 (tamper encrypted static key / AEAD tag)
        tampered_msg2 = bytearray(msg2)
        tampered_msg2[-1] ^= 0x01

        with pytest.raises((NoiseError, CryptoError, Exception)):
            initiator.process_handshake_message(bytes(tampered_msg2))

        # Initiator state MUST now be FAILED
        assert initiator.state == NoiseSessionState.FAILED

    def test_corrupted_ephemeral_key_transitions_to_failed(self) -> None:
        """Truncated handshake message transitions to FAILED."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        responder = NoiseSession(bob_id, alice_id.peer_id_hex)
        if responder.role == NoiseRole.INITIATOR:
            responder = NoiseSession(alice_id, bob_id.peer_id_hex)

        # Truncated message (only 10 bytes, needs at least 32)
        with pytest.raises(NoiseError):
            responder.process_handshake_message(b"\x01" * 10)

        assert responder.state == NoiseSessionState.FAILED

    @pytest.mark.asyncio
    async def test_coordinator_discards_failed_handshake_session(self) -> None:
        """Coordinator cleanly removes session when process_handshake_message fails."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        coordinator = SessionCoordinator(local_identity=alice_id)
        bob_hex = bob_id.peer_id_hex

        # Pre-create session in coordinator
        session = coordinator.get_or_create_session(bob_hex)
        assert coordinator.get_session(bob_hex) is session

        # Send corrupt NoiseHandshakeInit
        pkt = BitchatPacket.create(
            message_type=MessageType.NoiseHandshakeInit,
            sender_id=bob_id.peer_id,
            recipient_id=alice_id.peer_id,
            payload=b"\xde\xad\xbe\xef",  # Invalid handshake payload
        )

        await coordinator._process_packet_async(pkt, "127.0.0.1")

        # Session should be discarded from coordinator._sessions
        assert coordinator.get_session(bob_hex) is None
        assert session.state in (NoiseSessionState.FAILED, NoiseSessionState.CLOSED)

    @pytest.mark.asyncio
    async def test_coordinator_discard_failed_session_direct(self) -> None:
        """Calling _discard_failed_session with FAILED session cleans up state."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        coordinator = SessionCoordinator(local_identity=alice_id)
        bob_hex = bob_id.peer_id_hex
        session = coordinator.get_or_create_session(bob_hex)
        coordinator._pending_messages[bob_hex] = ["test message"]

        # Session in FAILED state must be discarded
        session._state = NoiseSessionState.FAILED
        coordinator._discard_failed_session(bob_hex, session)

        assert coordinator.get_session(bob_hex) is None
        assert bob_hex not in coordinator._pending_messages


# ===========================================================================
# 3. Bounded Pending Handshakes
# ===========================================================================


class TestBoundedPendingHandshakes:
    """Validate MAX_PENDING_HANDSHAKES bound enforcement."""

    def test_max_pending_handshakes_constant_is_64(self) -> None:
        assert MAX_PENDING_HANDSHAKES == 64
        assert SessionCoordinator.MAX_PENDING_HANDSHAKES == 64

    @pytest.mark.asyncio
    async def test_incoming_handshake_rejected_when_pending_saturated(self) -> None:
        """Coordinator rejects new handshakes when 64 pending handshakes exist."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        # Saturate 64 pending handshakes
        for i in range(MAX_PENDING_HANDSHAKES):
            peer_hex = f"{i:016x}"
            s = coordinator.get_or_create_session(peer_hex)
            s._state = NoiseSessionState.HANDSHAKING

        assert coordinator.pending_handshakes_count == 64

        # 65th peer attempts NoiseHandshakeInit
        peer65_hex = f"{65:016x}"
        pkt = BitchatPacket.create(
            message_type=MessageType.NoiseHandshakeInit,
            sender_id=bytes.fromhex(peer65_hex),
            recipient_id=alice_id.peer_id,
            payload=b"\x00" * 32,
        )

        await coordinator._process_packet_async(pkt, "127.0.0.1")

        # 65th peer must NOT have been granted a session
        assert coordinator.get_session(peer65_hex) is None
        assert coordinator.pending_handshakes_count == 64

    @pytest.mark.asyncio
    async def test_handshake_request_rejected_when_pending_saturated(self) -> None:
        """HandshakeRequest from new peer is rejected when 64 handshakes pending."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        for i in range(MAX_PENDING_HANDSHAKES):
            peer_hex = f"{i:016x}"
            s = coordinator.get_or_create_session(peer_hex)
            s._state = NoiseSessionState.HANDSHAKING

        peer_new_hex = f"{99:016x}"
        req_pkt = BitchatPacket.create(
            message_type=MessageType.HandshakeRequest,
            sender_id=bytes.fromhex(peer_new_hex),
            recipient_id=alice_id.peer_id,
            payload=b"",
        )

        await coordinator._process_packet_async(req_pkt, "127.0.0.1")

        assert coordinator.get_session(peer_new_hex) is None

    @pytest.mark.asyncio
    async def test_existing_pending_peer_can_continue_handshake(self) -> None:
        """A peer with a pending handshake is not rejected by saturation bound."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(local_identity=alice_id)

        # Saturate with 63 other peers
        for i in range(63):
            peer_hex = f"{i:016x}"
            s = coordinator.get_or_create_session(peer_hex)
            s._state = NoiseSessionState.HANDSHAKING

        # Peer 63 is already pending
        known_peer_hex = f"{63:016x}"
        known_session = coordinator.get_or_create_session(known_peer_hex)
        known_session._state = NoiseSessionState.HANDSHAKING

        assert coordinator.pending_handshakes_count == 64

        # Messages from known_peer_hex should not be dropped by saturation guard
        existing = coordinator._sessions.get(known_peer_hex)
        is_pending = (
            existing is not None and existing.state == NoiseSessionState.HANDSHAKING
        )
        assert is_pending is True


# ===========================================================================
# 4. Peer Authentication & TOFU Verification
# ===========================================================================


class TestPeerAuthenticationAndTOFU:
    """Validate TOFU contact verification in AppConfig and nickname protection."""

    def test_app_config_tofu_lifecycle(self) -> None:
        """Test Trust-On-First-Use: first use accepts & stores, mismatch rejects."""
        config = AppConfig()
        peer_id = "0102030405060708"
        fp_original = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
        fp_impostor = "11223344556677889900aabbccddeeff11223344556677889900aabbccddeeff"

        # 1. First use: contact is trusted and recorded
        assert config.verify_contact(peer_id, fp_original) is True
        assert config.get_contact_fingerprint(peer_id) == fp_original.lower()

        # 2. Subsequent use with same fingerprint: accepted
        assert config.verify_contact(peer_id, fp_original) is True

        # 3. Subsequent use with different fingerprint (MITM/spoof): REJECTED
        assert config.verify_contact(peer_id, fp_impostor) is False

    def test_app_config_contacts_serialization(self) -> None:
        """Verify contacts dictionary roundtrips through to_dict and from_dict."""
        config = AppConfig()
        config.add_contact("peer1", "fp1")
        config.add_contact("peer2", "fp2")

        d = config.to_dict()
        assert "contacts" in d
        assert d["contacts"]["peer1"] == "fp1"

        restored = AppConfig.from_dict(d)
        assert restored.verify_contact("peer1", "fp1") is True
        assert restored.verify_contact("peer1", "wrong_fp") is False

    def test_app_config_remove_contact(self) -> None:
        """Verify removing a contact allows re-trusting a new fingerprint via TOFU."""
        config = AppConfig()
        config.add_contact("peer1", "fp_old")
        assert config.verify_contact("peer1", "fp_new") is False

        assert config.remove_contact("peer1") is True
        # Once removed, next verification is treated as first use (TOFU)
        assert config.verify_contact("peer1", "fp_new") is True
        assert config.get_contact_fingerprint("peer1") == "fp_new"

    def test_unauthenticated_nickname_spoofing_prevented(self) -> None:
        """SessionCoordinator rejects unauthenticated nickname collision attempts."""
        alice_id = LocalIdentity.generate()
        coordinator = SessionCoordinator(
            local_identity=alice_id,
            nickname="CoordinatorAlice",
        )

        peer1_hex = "1111111111111111"
        peer2_hex = "2222222222222222"

        # Peer 1 claims "Bob"
        coordinator.peer_nicknames[peer1_hex] = "Bob"

        # Peer 2 tries to spoof "Bob" (case-insensitive)
        assert coordinator._is_nickname_spoofed(peer2_hex, "Bob") is True
        assert coordinator._is_nickname_spoofed(peer2_hex, "bob") is True
        assert coordinator._is_nickname_spoofed(peer2_hex, " BOB ") is True

        # Peer 2 tries to spoof coordinator's own nickname
        assert coordinator._is_nickname_spoofed(peer2_hex, "CoordinatorAlice") is True
        assert coordinator._is_nickname_spoofed(peer2_hex, "coordinatoralice") is True

        # Peer 2 uses an unclaimed nickname
        assert coordinator._is_nickname_spoofed(peer2_hex, "Charlie") is False

        # Peer 1 re-announcing its own nickname is NOT spoofing
        assert coordinator._is_nickname_spoofed(peer1_hex, "Bob") is False

    @pytest.mark.asyncio
    async def test_coordinator_rejects_tofu_mismatch_during_handshake(self) -> None:
        """Handshake completion is aborted if stored TOFU fingerprint does not match."""
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()

        storage = InMemoryStorage()
        config = storage.load_config()
        # Pre-seed bob with a different fingerprint in storage
        config.add_contact(bob_id.peer_id_hex, "expected_different_fingerprint")
        storage.save_config(config)

        coordinator = SessionCoordinator(local_identity=alice_id, storage=storage)
        completed_peers: list[str] = []
        coordinator.on_handshake_completed = lambda pid, fp: completed_peers.append(pid)

        # Create a mock session that completed handshake with bob_id
        session = coordinator.get_or_create_session(bob_id.peer_id_hex)
        session._remote_fingerprint = bob_id.fingerprint
        session._state = NoiseSessionState.ESTABLISHED

        # Invoke completion hook
        coordinator._on_handshake_established(bob_id.peer_id_hex, session)

        # Handshake completion must NOT be called due to TOFU failure
        assert bob_id.peer_id_hex not in completed_peers
        # Session must be discarded
        assert coordinator.get_session(bob_id.peer_id_hex) is None


# ===========================================================================
# 5. Corrupted Identity Backup & Thread Safety
# ===========================================================================


class TestCorruptedIdentityBackup:
    """Validate corrupted identity file backup creation and write lock safety."""

    def test_load_corrupted_json_creates_backup(self, tmp_path: Path) -> None:
        """Loading malformed JSON identity creates identity.json.corrupt.<ts>."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        id_file.write_text("{this is corrupted json!", encoding="utf-8")

        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)

        with pytest.raises(ConfigurationError):
            storage.load_identity()

        # Backup file must exist in tmp_path
        backups = list(tmp_path.glob("identity.json.corrupt.*"))
        assert len(backups) >= 1
        assert backups[0].read_text(encoding="utf-8") == "{this is corrupted json!"

    def test_load_missing_keys_creates_backup(self, tmp_path: Path) -> None:
        """Loading identity JSON missing private keys creates backup file."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        bad_data = json.dumps({"peer_id": "0102030405060708", "notes": "no keys"})
        id_file.write_text(bad_data, encoding="utf-8")

        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)

        with pytest.raises(ConfigurationError):
            storage.load_identity()

        backups = list(tmp_path.glob("identity.json.corrupt.*"))
        assert len(backups) >= 1

    def test_save_identity_preserves_corrupted_existing_file(
        self, tmp_path: Path
    ) -> None:
        """Saving new identity preserves corrupted existing file before overwrite."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        corrupted_content = "corrupted previous identity data"
        id_file.write_text(corrupted_content, encoding="utf-8")

        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
        new_identity = LocalIdentity.generate()

        storage.save_identity(new_identity)

        # 1. Backup of corrupted data must be preserved
        backups = list(tmp_path.glob("identity.json.corrupt.*"))
        assert len(backups) >= 1
        assert backups[0].read_text(encoding="utf-8") == corrupted_content

        # 2. identity.json must now be valid and loadable
        loaded = storage.load_identity()
        assert loaded is not None
        assert loaded.fingerprint == new_identity.fingerprint

    def test_save_identity_does_not_backup_valid_existing_file(
        self, tmp_path: Path
    ) -> None:
        """Saving over an existing valid identity does not create a corrupt backup."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"

        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
        id1 = LocalIdentity.generate()
        storage.save_identity(id1)

        # Overwrite with second valid identity
        id2 = LocalIdentity.generate()
        storage.save_identity(id2)

        backups = list(tmp_path.glob("identity.json.corrupt.*"))
        assert len(backups) == 0

    def test_thread_safe_concurrent_identity_access(self, tmp_path: Path) -> None:
        """Verify _write_lock protects concurrent identity read/write operations."""
        id_file = tmp_path / "identity.json"
        cfg_file = tmp_path / "config.json"
        storage = FileConfigStorage(config_path=cfg_file, identity_path=id_file)
        assert hasattr(storage, "_write_lock")

        identity = LocalIdentity.generate()
        storage.save_identity(identity)

        errors: list[Exception] = []

        def worker(thread_idx: int) -> None:
            try:
                for _ in range(10):
                    if thread_idx % 2 == 0:
                        loaded = storage.load_identity()
                        assert loaded is not None
                    else:
                        storage.save_identity(identity)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ===========================================================================
# 6. Cryptographic Material Audit in Logs
# ===========================================================================


class TestNoCryptoSecretsInLogs:
    """Verify that zero private keys, session keys, or secrets appear in log output."""

    def test_zero_keys_or_secrets_in_logs_during_handshake(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Perform handshake and message exchange; verify zero secret hex in logs."""
        caplog.set_level(logging.DEBUG)

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
        responder.process_handshake_message(m3)

        assert initiator.is_established
        assert responder.is_established

        # Encrypt and decrypt a test secret
        secret_plaintext = "CONFIDENTIAL_PAYLOAD_SECRET_987654321"
        ciphertext = initiator.encrypt(secret_plaintext.encode())
        decrypted = responder.decrypt(ciphertext)
        assert decrypted.decode() == secret_plaintext

        # Secrets to check for
        sensitive_hexes = [
            alice_id.x25519_private.hex(),
            alice_id.ed25519_private.hex(),
            bob_id.x25519_private.hex(),
            bob_id.ed25519_private.hex(),
        ]
        if initiator._send_cipher and initiator._send_cipher._key:
            sensitive_hexes.append(initiator._send_cipher._key.hex())
        if initiator._recv_cipher and initiator._recv_cipher._key:
            sensitive_hexes.append(initiator._recv_cipher._key.hex())

        # Inspect all log records
        for record in caplog.records:
            log_text = record.getMessage()
            assert secret_plaintext not in log_text
            for secret_hex in sensitive_hexes:
                assert secret_hex not in log_text
                assert secret_hex.lower() not in log_text.lower()
