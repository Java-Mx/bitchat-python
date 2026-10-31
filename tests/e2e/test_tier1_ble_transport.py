"""Tier 1: Feature Coverage — BLE Transport & GATT Peripheral/Central Flow."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner, MockBLEServerBackend

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.base import TransportState
from bitchat.transport.bluetooth import BluetoothTransport


@pytest.mark.asyncio
async def test_mock_ble_connection_client_server() -> None:
    """Validate MockBleakClient attaches to MockBLEServerBackend and receives notifications."""
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)
    await server.start()

    client = MockBleakClient(address="DE:AD:BE:EF:00:01")
    backend.attach_client(client)
    await client.connect()

    received_notifications: list[bytes] = []

    def notify_cb(char: Any, data: bytearray) -> None:
        received_notifications.append(bytes(data))

    await client.start_notify("char_uuid", notify_cb)

    test_payload = b"GATT notification packet"
    await backend.send_notification(test_payload)

    assert len(received_notifications) == 1
    assert received_notifications[0] == test_payload

    await client.disconnect()
    await server.stop()


@pytest.mark.asyncio
async def test_ble_server_handle_data_routes_to_coordinator() -> None:
    """Validate server-received data triggers _handle_server_data_received in coordinator."""
    id_a = LocalIdentity.generate()
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)

    client_a = MockBleakClient(address="AA:01")

    def mock_scanner(**kw: Any) -> MockBleakScanner:
        return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

    manager = BLEManager(
        sender_id=id_a.peer_id,
        client_factory=lambda *a, **kw: client_a,
        scanner_factory=mock_scanner,
    )

    received_msgs: list[tuple[str, str, bool]] = []
    coordinator = SessionCoordinator(
        local_identity=id_a,
        ble_manager=manager,
        ble_server=server,
        storage=InMemoryStorage(),
        nickname="Node-Recv",
        on_message_received=lambda s, m, enc: received_msgs.append((s, m, enc)),
    )
    await coordinator.start()

    # Craft an Announce packet from a remote peer
    sender_remote = os.urandom(SENDER_ID_SIZE)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Announce,
        ttl=3,
        timestamp=1000,
        flags=0,
        sender_id=sender_remote,
        recipient_id=None,
        payload=b"Remote-Nick",
        signature=None,
    )
    encoded = encode_packet(packet, add_padding=False)

    # Simulate write to GATT server
    backend.emit_write(encoded, client_id="AA:01")
    await asyncio.sleep(0.05)

    assert coordinator.peer_nicknames.get(sender_remote.hex()) == "Remote-Nick"

    await coordinator.stop()


@pytest.mark.asyncio
async def test_ble_manager_connect_disconnect_lifecycle() -> None:
    """Validate BLEManager connects to peer, tracks address, and disconnects cleanly."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    clients: dict[str, MockBleakClient] = {}

    def client_factory(addr: str, **kw: Any) -> MockBleakClient:
        if addr not in clients:
            clients[addr] = MockBleakClient(address=addr)
        return clients[addr]

    def mock_scanner(**kw: Any) -> MockBleakScanner:
        return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

    manager = BLEManager(
        sender_id=sender_id,
        client_factory=client_factory,
        scanner_factory=mock_scanner,
    )

    connected_events: list[str] = []
    disconnected_events: list[str] = []
    manager.on_peer_connected = lambda addr: connected_events.append(addr)
    manager.on_peer_disconnected = lambda addr: disconnected_events.append(addr)

    target_addr = "11:22:33:44:55:66"
    conn = await manager.connect_peer(target_addr)
    assert conn is not None
    assert target_addr in manager.connected_peers
    assert len(connected_events) == 1
    assert connected_events[0] == target_addr

    # Disconnect
    await manager.disconnect_peer(target_addr)
    assert target_addr not in manager.connected_peers
    from bitchat.ble.models import BLEState

    assert manager._state == BLEState.READY

    await manager.shutdown()


@pytest.mark.asyncio
async def test_bluetooth_transport_start_and_stop() -> None:
    """Validate BluetoothTransport with injected test backend starts and stops cleanly."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)

    client = MockBleakClient(address="AA:01")

    def mock_scanner(**kw: Any) -> MockBleakScanner:
        return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

    manager = BLEManager(
        sender_id=sender_id,
        client_factory=lambda *a, **kw: client,
        scanner_factory=mock_scanner,
    )

    transport = BluetoothTransport(
        ble_manager=manager,
        ble_server=server,
    )

    await transport.start()
    assert transport.is_running
    assert transport.state in (
        TransportState.READY,
        TransportState.CONNECTED,
        TransportState.SCANNING,
    )

    await transport.stop()
    assert not transport.is_running
    assert transport.state == TransportState.OFFLINE


@pytest.mark.asyncio
async def test_ble_transport_telemetry_reporting() -> None:
    """Validate BluetoothTransport telemetry report contains required diagnostic fields."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)

    def mock_scanner(**kw: Any) -> MockBleakScanner:
        return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

    manager = BLEManager(
        sender_id=sender_id,
        client_factory=lambda *a, **kw: MockBleakClient(address="AA:01"),
        scanner_factory=mock_scanner,
    )

    transport = BluetoothTransport(
        ble_manager=manager,
        ble_server=server,
    )
    await transport.start()

    telem = transport.get_telemetry()
    assert telem["transport"] == "bluetooth"
    assert "adapter_available" in telem
    assert "central_supported" in telem
    assert "peripheral_supported" in telem
    assert "advertising_active" in telem
    assert "connected_peers_count" in telem

    await transport.stop()
