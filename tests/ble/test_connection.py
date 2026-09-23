"""Tests for BLE connection lifecycle and state machine."""

import pytest
from tests.ble.mocks import MockBleakClient

from bitchat.ble.connection import BLEConnection
from bitchat.ble.models import BLEConnectionState
from bitchat.exceptions import BLEConnectionError


@pytest.mark.asyncio
async def test_connection_lifecycle_success():
    client_instance: MockBleakClient | None = None

    def client_factory(addr, disconnected_callback=None):
        nonlocal client_instance
        client_instance = MockBleakClient(
            addr, disconnected_callback=disconnected_callback
        )
        return client_instance

    received_notifications = []
    connection = BLEConnection(
        peer_address="AA:BB:CC:DD:EE:01",
        notification_callback=received_notifications.append,
        client_factory=client_factory,
    )

    assert connection.state == BLEConnectionState.DISCONNECTED
    assert not connection.is_ready

    await connection.connect()
    assert connection.state == BLEConnectionState.READY
    assert connection.is_ready
    assert client_instance is not None
    assert client_instance.is_connected
    assert client_instance.subscribed_callback is not None

    # Test notification dispatch
    client_instance.emit_notification(b"test packet bytes")
    assert received_notifications == [b"test packet bytes"]

    # Disconnect
    await connection.disconnect()
    assert connection.state == BLEConnectionState.DISCONNECTED
    assert not connection.is_ready
    assert not client_instance.is_connected


@pytest.mark.asyncio
async def test_connection_failure():
    def failing_factory(addr, disconnected_callback=None):
        c = MockBleakClient(addr, disconnected_callback=disconnected_callback)
        c.should_fail_connect = True
        return c

    connection = BLEConnection(
        peer_address="AA:BB:CC:DD:EE:02",
        client_factory=failing_factory,
    )

    with pytest.raises(BLEConnectionError, match="Failed to connect"):
        await connection.connect()

    assert connection.state == BLEConnectionState.DISCONNECTED
    assert not connection.is_ready


@pytest.mark.asyncio
async def test_unexpected_disconnect():
    client_instance: MockBleakClient | None = None
    disconnect_calls = []

    def client_factory(addr, disconnected_callback=None):
        nonlocal client_instance
        client_instance = MockBleakClient(
            addr, disconnected_callback=disconnected_callback
        )
        return client_instance

    connection = BLEConnection(
        peer_address="AA:BB:CC:DD:EE:03",
        disconnected_callback=disconnect_calls.append,
        client_factory=client_factory,
    )

    await connection.connect()
    assert connection.is_ready
    assert client_instance is not None

    # Simulate unexpected drop from OS/Bleak
    client_instance.trigger_unexpected_disconnect()
    assert connection.state == BLEConnectionState.DISCONNECTED
    assert not connection.is_ready
    assert disconnect_calls == ["AA:BB:CC:DD:EE:03"]


@pytest.mark.asyncio
async def test_write_data():
    client_instance: MockBleakClient | None = None

    def client_factory(addr, disconnected_callback=None):
        nonlocal client_instance
        client_instance = MockBleakClient(
            addr, disconnected_callback=disconnected_callback
        )
        return client_instance

    connection = BLEConnection(
        peer_address="AA:BB:CC:DD:EE:04",
        client_factory=client_factory,
    )

    # Cannot write before connected
    with pytest.raises(BLEConnectionError, match="not ready"):
        await connection.write(b"data")

    await connection.connect()
    assert client_instance is not None

    await connection.write(b"hello ble", response=False)
    assert len(client_instance.written_chunks) == 1
    assert client_instance.written_chunks[0][1] == b"hello ble"
    assert client_instance.written_chunks[0][2] is False

    await connection.disconnect()
