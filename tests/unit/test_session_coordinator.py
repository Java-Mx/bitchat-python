"""Tests for SessionCoordinator verifying handshake, encryption, and messaging."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from tests.ble.mocks import (
    MockBleakClient,
    MockBleakScanner,
    MockBLEServerBackend,
)

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto import ed25519
from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseSessionState
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket
from bitchat.tui.app import BitChatApp
from bitchat.tui.widgets.chat_view import ChatView


def _create_linked_pair() -> tuple[
    SessionCoordinator,
    SessionCoordinator,
    list[tuple[str, str, bool]],
    list[tuple[str, str, bool]],
]:
    id_a = LocalIdentity.generate()
    id_b = LocalIdentity.generate()

    backend_a = MockBLEServerBackend()
    server_a = BLEServer(backend=backend_a)

    backend_b = MockBLEServerBackend()
    server_b = BLEServer(backend=backend_b)

    client_a = MockBleakClient(address="BB:01")
    backend_b.attach_client(client_a)

    orig_write_a = client_a.write_gatt_char

    async def hooked_write_a(char: Any, data: bytes, response: bool = False) -> None:
        await orig_write_a(char, data, response)
        backend_b.emit_write(data, client_id="client_a")

    client_a.write_gatt_char = hooked_write_a  # type: ignore[assignment]

    mock_scanner_factory = lambda **kwargs: MockBleakScanner(  # noqa: E731
        detection_callback=kwargs["detection_callback"],
        service_uuids=kwargs["service_uuids"],
    )

    manager_a = BLEManager(
        sender_id=id_a.peer_id,
        client_factory=lambda *args, **kwargs: client_a,
        scanner_factory=mock_scanner_factory,
    )
    manager_b = BLEManager(
        sender_id=id_b.peer_id,
        scanner_factory=mock_scanner_factory,
    )

    messages_a: list[tuple[str, str, bool]] = []
    messages_b: list[tuple[str, str, bool]] = []

    coord_a = SessionCoordinator(
        local_identity=id_a,
        ble_manager=manager_a,
        ble_server=server_a,
        nickname="Alice",
        on_message_received=lambda s, m, enc: messages_a.append((s, m, enc)),
        inter_fragment_delay=0.001,
    )
    coord_b = SessionCoordinator(
        local_identity=id_b,
        ble_manager=manager_b,
        ble_server=server_b,
        nickname="Bob",
        on_message_received=lambda s, m, enc: messages_b.append((s, m, enc)),
        inter_fragment_delay=0.001,
    )

    return coord_a, coord_b, messages_a, messages_b


class TestSessionCoordinator:
    @pytest.mark.parametrize(
        "signature_kind",
        [
            "unsigned",
            "valid",
            "modified_payload",
            "wrong_signing_key",
            "sender_key_mismatch",
            "invalid_signature_bytes",
        ],
    )
    @pytest.mark.asyncio
    async def test_public_message_does_not_authenticate_sender_from_signature(
        self, signature_kind: str
    ) -> None:
        sender = LocalIdentity.generate()
        signing_identity = (
            LocalIdentity.generate()
            if signature_kind in ("wrong_signing_key", "sender_key_mismatch")
            else sender
        )
        payload = b"original public message"
        signed_payload = payload
        signature: bytes | None
        if signature_kind == "unsigned":
            signature = None
        elif signature_kind == "invalid_signature_bytes":
            signature = b"\x00" * 64
        else:
            if signature_kind == "modified_payload":
                signed_payload = b"original public message before alteration"
            signature = ed25519.sign(signing_identity.ed25519_private, signed_payload)
        if signature_kind == "modified_payload":
            payload = b"modified public message"

        received: list[tuple[str, str, bool]] = []
        coordinator = SessionCoordinator(
            local_identity=LocalIdentity.generate(),
            on_message_received=lambda peer_id, text, encrypted: received.append(
                (peer_id, text, encrypted)
            ),
        )
        packet = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=sender.peer_id,
            payload=payload,
            signature=signature,
        )

        await coordinator._process_packet_async(packet)

        assert received == [(sender.peer_id_hex, payload.decode(), False)]

    @pytest.mark.asyncio
    async def test_incomplete_noise_handshake_times_out_and_is_removed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "bitchat.app.session_coordinator.NOISE_HANDSHAKE_TIMEOUT_SECONDS",
            0.01,
        )
        coord_a, coord_b, _, _ = _create_linked_pair()
        remote_peer_id = coord_b.local_identity.peer_id_hex
        session = coord_a.get_or_create_session(remote_peer_id)
        session.start_handshake()

        coord_a._schedule_handshake_timeout(remote_peer_id, session)
        await asyncio.sleep(0.05)

        assert coord_a.get_session(remote_peer_id) is None
        assert session.state == NoiseSessionState.CLOSED
        assert not coord_a._handshake_timeout_tasks
        await coord_a.stop()
        await coord_b.stop()

    @pytest.mark.asyncio
    async def test_coordinator_initialization(self) -> None:
        id_a = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())
        manager = BLEManager(sender_id=id_a.peer_id)
        coord = SessionCoordinator(id_a, manager, server, nickname="Tester")

        assert coord.nickname == "Tester"
        assert not coord.is_running
        assert len(coord.peer_nicknames) == 0

    @pytest.mark.asyncio
    async def test_get_or_create_session(self) -> None:
        id_a = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())
        manager = BLEManager(sender_id=id_a.peer_id)
        coord = SessionCoordinator(id_a, manager, server)

        remote_id = "ff" * 8
        session1 = coord.get_or_create_session(remote_id)
        session2 = coord.get_or_create_session(remote_id)
        assert session1 is session2
        assert session1.state == NoiseSessionState.UNINITIALIZED

    @pytest.mark.asyncio
    async def test_announce_exchange(self) -> None:
        coord_a, coord_b, _, _ = _create_linked_pair()

        await coord_b.start()
        await coord_a.start()

        # Connect Node A to Node B
        await coord_a.ble_manager.connect_peer("BB:01")
        await asyncio.sleep(0.05)

        # Node A sends announce
        await coord_a.send_announce("Alice")
        await asyncio.sleep(0.05)

        # Node B should have recorded Alice's nickname
        assert coord_b.peer_nicknames.get(coord_a.local_identity.peer_id_hex) == "Alice"

        await coord_a.stop()
        await coord_b.stop()

    @pytest.mark.asyncio
    async def test_broadcast_message(self) -> None:
        coord_a, coord_b, _, messages_b = _create_linked_pair()

        await coord_b.start()
        await coord_a.start()

        await coord_a.ble_manager.connect_peer("BB:01")
        await asyncio.sleep(0.05)

        await coord_a.send_broadcast_message("Hello BitChat World!")
        await asyncio.sleep(0.05)

        assert len(messages_b) == 1
        sender, text, is_enc = messages_b[0]
        assert sender == coord_a.local_identity.peer_id_hex
        assert text == "Hello BitChat World!"
        assert is_enc is False

        await coord_a.stop()
        await coord_b.stop()

    @pytest.mark.asyncio
    async def test_encrypted_direct_message_bidirectional(self) -> None:
        coord_a, coord_b, messages_a, messages_b = _create_linked_pair()

        await coord_b.start()
        await coord_a.start()

        await coord_a.ble_manager.connect_peer("BB:01")
        await asyncio.sleep(0.05)

        # Alice sends DM to Bob. This triggers Noise XX handshake,
        # followed by encrypted message delivery.
        await coord_a.send_direct_message(
            coord_b.local_identity.peer_id_hex, "Secret message for Bob"
        )
        await asyncio.sleep(0.1)

        # Handshake should complete and Bob should receive decrypted DM
        session_a = coord_a.get_or_create_session(coord_b.local_identity.peer_id_hex)
        session_b = coord_b.get_or_create_session(coord_a.local_identity.peer_id_hex)

        assert session_a.is_established
        assert session_b.is_established

        assert len(messages_b) == 1
        sender, text, is_enc = messages_b[0]
        assert sender == coord_a.local_identity.peer_id_hex
        assert text == "Secret message for Bob"
        assert is_enc is True

        # Bob replies back to Alice
        await coord_b.send_direct_message(
            coord_a.local_identity.peer_id_hex, "Secret reply from Bob"
        )
        await asyncio.sleep(0.05)

        assert len(messages_a) == 1
        sender, text, is_enc = messages_a[0]
        assert sender == coord_b.local_identity.peer_id_hex
        assert text == "Secret reply from Bob"
        assert is_enc is True

        await coord_a.stop()
        await coord_b.stop()

    @pytest.mark.asyncio
    async def test_authenticated_ble_transition_is_reported_once_in_tui(self) -> None:
        coord_a, coord_b, messages_a, messages_b = _create_linked_pair()
        app_a = BitChatApp(coordinator=coord_a)
        app_b = BitChatApp(coordinator=coord_b)
        on_message_b = coord_b.on_message_received

        def capture_message_b(sender: str, text: str, is_encrypted: bool) -> None:
            messages_b.append((sender, text, is_encrypted))
            if on_message_b is not None:
                on_message_b(sender, text, is_encrypted)

        coord_b.on_message_received = capture_message_b

        try:
            async with (
                app_a.run_test() as pilot_a,
                app_b.run_test() as pilot_b,
            ):
                await asyncio.sleep(0.05)
                for app in (app_a, app_b):
                    assert not any(
                        record.kind == "system"
                        and record.text == "Connected via Bluetooth"
                        for record in app.query_one(ChatView)._message_history
                    )

                await coord_a.ble_manager.connect_peer("BB:01")
                await asyncio.sleep(0.05)

                for app in (app_a, app_b):
                    assert not any(
                        record.kind == "system"
                        and record.text == "Connected via Bluetooth"
                        for record in app.query_one(ChatView)._message_history
                    )

                await coord_a.send_direct_message(
                    coord_b.local_identity.peer_id_hex,
                    "Authenticated BLE message",
                )
                for _ in range(50):
                    session_a = coord_a.get_session(coord_b.local_identity.peer_id_hex)
                    session_b = coord_b.get_session(coord_a.local_identity.peer_id_hex)
                    if (
                        session_a is not None
                        and session_a.is_established
                        and session_b is not None
                        and session_b.is_established
                    ):
                        break
                    await asyncio.sleep(0.01)
                await pilot_a.pause()
                await pilot_b.pause()
                for _ in range(50):
                    if messages_b:
                        break
                    await asyncio.sleep(0.01)

                for app in (app_a, app_b):
                    connected_messages = [
                        record
                        for record in app.query_one(ChatView)._message_history
                        if record.kind == "system"
                        and record.text == "Connected via Bluetooth"
                    ]
                    assert len(connected_messages) == 1

                assert messages_b == [
                    (
                        coord_a.local_identity.peer_id_hex,
                        "Authenticated BLE message",
                        True,
                    )
                ]
                assert not any(
                    "Connected via Bluetooth" in message
                    for _, message, _ in messages_a + messages_b
                )

                assert coord_a.on_handshake_completed is not None
                coord_a.on_handshake_completed(
                    coord_b.local_identity.peer_id_hex,
                    coord_b.local_identity.fingerprint,
                )
                await pilot_a.pause()
                assert (
                    sum(
                        record.kind == "system"
                        and record.text == "Connected via Bluetooth"
                        for record in app_a.query_one(ChatView)._message_history
                    )
                    == 1
                )
        finally:
            await coord_a.stop()
            await coord_b.stop()

    @pytest.mark.asyncio
    async def test_large_fragmented_direct_message(self) -> None:
        coord_a, coord_b, _, messages_b = _create_linked_pair()

        await coord_b.start()
        await coord_a.start()

        await coord_a.ble_manager.connect_peer("BB:01")
        await asyncio.sleep(0.05)

        large_payload = "LARGE-MESSAGE-TEST-" + ("Z" * 1200)

        # Send large DM
        await coord_a.send_direct_message(
            coord_b.local_identity.peer_id_hex, large_payload
        )
        for _ in range(50):
            if len(messages_b) > 0:
                break
            await asyncio.sleep(0.02)

        assert len(messages_b) == 1
        sender, text, is_enc = messages_b[0]
        assert sender == coord_a.local_identity.peer_id_hex
        assert text == large_payload
        assert is_enc is True

        await coord_a.stop()
        await coord_b.stop()

    @pytest.mark.asyncio
    async def test_coordinator_ble_error_and_retry(self) -> None:
        """BLE failure triggers on_ble_error and updates truthful ble_status."""
        id_a = LocalIdentity.generate()
        server = BLEServer(backend=MockBLEServerBackend())

        # Create manager with scanner that raises on start
        def failing_scanner_factory(**kwargs: Any) -> Any:
            mock = MockBleakScanner(
                detection_callback=kwargs["detection_callback"],
                service_uuids=kwargs["service_uuids"],
            )

            async def fail_start() -> None:
                raise RuntimeError("Hardware adapter missing")

            mock.start = fail_start  # type: ignore[assignment]
            return mock

        manager = BLEManager(
            sender_id=id_a.peer_id,
            scanner_factory=failing_scanner_factory,
        )

        reported_errors: list[str] = []
        coord = SessionCoordinator(
            local_identity=id_a,
            ble_manager=manager,
            ble_server=server,
            nickname="Alice",
        )
        coord.on_ble_error = lambda err: reported_errors.append(err)

        await coord.start()

        assert coord.ble_status == "error"
        assert coord.ble_error_message is not None
        assert "Hardware adapter missing" in coord.ble_error_message
        assert len(reported_errors) >= 1

        # Test retry failure
        success = await coord.retry_ble()
        assert success is False
        assert coord.ble_status == "error"

        await coord.stop()
        assert coord.ble_status == "offline"
