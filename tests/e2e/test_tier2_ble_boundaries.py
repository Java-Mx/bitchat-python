"""Tier 2: Boundary & Corner Cases — BLE Transport Boundaries."""

from __future__ import annotations

import os

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner, MockBLEServerBackend

from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.exceptions import BLEConnectionError
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


@pytest.mark.asyncio
async def test_ble_client_write_when_disconnected_raises_runtime_error() -> None:
    """Validate writing to an unconnected BLE client raises RuntimeError."""
    client = MockBleakClient(address="AA:BB:CC:00:00:01")
    assert not client.is_connected

    with pytest.raises(RuntimeError, match="Client not connected"):
        await client.write_gatt_char("char_handle", b"test_bytes")


@pytest.mark.asyncio
async def test_ble_client_simulated_write_failure() -> None:
    """Validate client handles hardware GATT write failure safely."""
    client = MockBleakClient(address="AA:BB:CC:00:00:02")
    await client.connect()
    assert client.is_connected

    client.should_fail_write = True
    with pytest.raises(RuntimeError, match="Write failed"):
        await client.write_gatt_char("char_handle", b"test_bytes")

    await client.disconnect()


@pytest.mark.asyncio
async def test_ble_client_connect_failure() -> None:
    """Validate client connection failure returns False without hanging."""
    client = MockBleakClient(address="AA:BB:CC:00:00:03")
    client.should_fail_connect = True

    success = await client.connect()
    assert success is False
    assert not client.is_connected


@pytest.mark.asyncio
async def test_ble_manager_send_to_unconnected_peer_raises_error() -> None:
    """Validate sending a packet to an unestablished peer address raises BLEConnectionError."""
    manager = BLEManager(
        sender_id=os.urandom(SENDER_ID_SIZE),
        client_factory=lambda *a, **kw: MockBleakClient(address="AA:01"),
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )

    pkt = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=1,
        timestamp=100,
        flags=0,
        sender_id=os.urandom(SENDER_ID_SIZE),
        recipient_id=None,
        payload=b"test",
        signature=None,
    )

    with pytest.raises(BLEConnectionError, match="not connected"):
        await manager.send_to_peer("UNKNOWN:ADDR", pkt)


@pytest.mark.asyncio
async def test_ble_scanner_adapter_offline_error() -> None:
    """Validate scanner failure when Bluetooth adapter is offline raises RuntimeError."""
    scanner = MockBleakScanner(
        detection_callback=lambda dev, adv: None,
        service_uuids=["F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"],
    )
    scanner.should_fail_start = True

    with pytest.raises(RuntimeError, match="adapter offline"):
        await scanner.start()


@pytest.mark.asyncio
async def test_ble_server_abort_handling_client_disconnect() -> None:
    """Validate server backend handles sudden client disconnect without crashing."""
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)
    await server.start()

    client = MockBleakClient(address="XX:YY:ZZ:00:01")
    backend.attach_client(client)
    await client.connect()

    # Trigger sudden unexpected disconnect
    client.trigger_unexpected_disconnect()
    assert not client.is_connected

    # Server should still be healthy and running
    assert server.is_advertising
    await server.stop()
