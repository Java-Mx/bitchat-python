"""Tests for BLEManager coordinating scanning, multi-peer connections, and routing."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner

from bitchat.ble.manager import BLEManager
from bitchat.exceptions import BLEConnectionError
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket

if TYPE_CHECKING:
    from bitchat.ble.models import DiscoveredPeer


def _create_packet(
    message_type: MessageType = MessageType.Message,
    sender_id: bytes = b"\x01" * 8,
    recipient_id: bytes | None = None,
    payload: bytes = b"",
) -> BitchatPacket:
    flags = FLAG_HAS_RECIPIENT if recipient_id is not None else 0
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=message_type,
        ttl=7,
        timestamp=int(time.time() * 1000),
        flags=flags,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        signature=None,
    )


@pytest.mark.asyncio
async def test_manager_discovery_lifecycle() -> None:
    mock_scanner: MockBleakScanner | None = None

    def scanner_factory(
        detection_callback: Any, service_uuids: list[str]
    ) -> MockBleakScanner:
        nonlocal mock_scanner
        mock_scanner = MockBleakScanner(detection_callback, service_uuids)
        return mock_scanner

    discovered: list[DiscoveredPeer] = []
    manager = BLEManager(
        sender_id=b"\x01" * 8,
        on_peer_discovered=lambda p: discovered.append(p),
        scanner_factory=scanner_factory,
    )

    await manager.start_discovery()
    assert mock_scanner is not None
    assert mock_scanner.is_started is True

    # Emit peer detection
    mock_scanner.emit_device(address="11:22:33:44:55:66", name="Peer-1", rssi=-60)
    assert len(discovered) == 1
    assert discovered[0].address == "11:22:33:44:55:66"
    assert "11:22:33:44:55:66" in manager.discovered_peers

    await manager.stop_discovery()
    assert mock_scanner.is_started is False


@pytest.mark.asyncio
async def test_manager_connect_and_disconnect_peer() -> None:
    clients: dict[str, MockBleakClient] = {}

    def client_factory(address: str, **kwargs: Any) -> MockBleakClient:
        client = MockBleakClient(address=address, **kwargs)
        clients[address] = client
        return client

    connected_events: list[str] = []
    disconnected_events: list[str] = []

    manager = BLEManager(
        sender_id=b"\x01" * 8,
        on_peer_connected=lambda addr: connected_events.append(addr),
        on_peer_disconnected=lambda addr: disconnected_events.append(addr),
        client_factory=client_factory,
    )

    transport = await manager.connect_peer("11:22:33:44:55:66")
    assert transport.connection.is_ready is True
    assert "11:22:33:44:55:66" in manager.connected_peers
    assert connected_events == ["11:22:33:44:55:66"]

    # Re-connecting to same ready peer returns existing transport
    existing = await manager.connect_peer("11:22:33:44:55:66")
    assert existing is transport

    # Disconnect peer
    await manager.disconnect_peer("11:22:33:44:55:66")
    assert "11:22:33:44:55:66" not in manager.connected_peers
    assert transport.connection.is_connected is False


@pytest.mark.asyncio
async def test_manager_remote_disconnect_handling() -> None:
    clients: dict[str, MockBleakClient] = {}

    def client_factory(address: str, **kwargs: Any) -> MockBleakClient:
        client = MockBleakClient(address=address, **kwargs)
        clients[address] = client
        return client

    disconnected_events: list[str] = []
    manager = BLEManager(
        sender_id=b"\x01" * 8,
        on_peer_disconnected=lambda addr: disconnected_events.append(addr),
        client_factory=client_factory,
    )

    await manager.connect_peer("11:22:33:44:55:66")
    assert "11:22:33:44:55:66" in manager.connected_peers

    # Simulate unexpected remote disconnection
    mock_client = clients["11:22:33:44:55:66"]
    mock_client.trigger_unexpected_disconnect()

    assert "11:22:33:44:55:66" not in manager.connected_peers
    assert disconnected_events == ["11:22:33:44:55:66"]


@pytest.mark.asyncio
async def test_manager_send_and_broadcast() -> None:
    clients: dict[str, MockBleakClient] = {}

    def client_factory(address: str, **kwargs: Any) -> MockBleakClient:
        client = MockBleakClient(address=address, **kwargs)
        clients[address] = client
        return client

    manager = BLEManager(
        sender_id=b"\x01" * 8,
        client_factory=client_factory,
    )

    # Sending to unconnected peer raises error
    pkt = _create_packet(payload=b"test")
    with pytest.raises(BLEConnectionError, match="not connected"):
        await manager.send_to_peer("AA:BB:CC:DD:EE:99", pkt)

    # Connect two peers
    await manager.connect_peer("AA:01")
    await manager.connect_peer("AA:02")

    assert len(manager.connected_peers) == 2

    # Send directly to peer 1
    await manager.send_to_peer("AA:01", pkt)
    assert len(clients["AA:01"].written_chunks) == 1
    assert len(clients["AA:02"].written_chunks) == 0

    # Broadcast to all
    bcast_pkt = _create_packet(payload=b"broadcast_msg")
    await manager.broadcast_packet(bcast_pkt)
    assert len(clients["AA:01"].written_chunks) == 2
    assert len(clients["AA:02"].written_chunks) == 1

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_incoming_packet_dispatch() -> None:
    clients: dict[str, MockBleakClient] = {}

    def client_factory(address: str, **kwargs: Any) -> MockBleakClient:
        client = MockBleakClient(address=address, **kwargs)
        clients[address] = client
        return client

    received: list[tuple[BitchatPacket, str]] = []
    manager = BLEManager(
        sender_id=b"\x01" * 8,
        on_packet_received=lambda pkt, addr: received.append((pkt, addr)),
        client_factory=client_factory,
    )

    await manager.connect_peer("PEER:01")
    mock_client = clients["PEER:01"]

    test_pkt = _create_packet(
        message_type=MessageType.Message,
        sender_id=b"\x02" * 8,
        payload=b"routed message",
    )
    mock_client.emit_notification(encode_packet(test_pkt, add_padding=True))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    pkt, addr = received[0]
    assert addr == "PEER:01"
    assert pkt.payload == b"routed message"

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_clean_shutdown() -> None:
    mock_scanner: MockBleakScanner | None = None

    def scanner_factory(
        detection_callback: Any, service_uuids: list[str]
    ) -> MockBleakScanner:
        nonlocal mock_scanner
        mock_scanner = MockBleakScanner(detection_callback, service_uuids)
        return mock_scanner

    clients: dict[str, MockBleakClient] = {}

    def client_factory(address: str, **kwargs: Any) -> MockBleakClient:
        client = MockBleakClient(address=address, **kwargs)
        clients[address] = client
        return client

    manager = BLEManager(
        sender_id=b"\x01" * 8,
        scanner_factory=scanner_factory,
        client_factory=client_factory,
    )

    await manager.start_discovery()
    await manager.connect_peer("AA:01")
    await manager.connect_peer("AA:02")

    assert mock_scanner is not None and mock_scanner.is_started is True
    assert len(manager.connected_peers) == 2

    await manager.shutdown()

    assert mock_scanner.is_started is False
    assert len(manager.connected_peers) == 0
    for client in clients.values():
        assert client.is_connected is False
