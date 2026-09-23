"""Tests for BLEServer peripheral and advertising logic."""

from __future__ import annotations

import pytest
from tests.ble.mocks import MockBleakClient, MockBLEServerBackend

from bitchat.ble.server import BLEServer
from bitchat.exceptions import BLEError


@pytest.mark.asyncio
async def test_server_start_stop_mock() -> None:
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)

    assert server.is_advertising is False
    await server.start()
    assert server.is_advertising is True
    assert backend.is_started is True

    await server.stop()
    assert server.is_advertising is False
    assert backend.is_started is False


@pytest.mark.asyncio
async def test_server_receive_write() -> None:
    backend = MockBLEServerBackend()
    received_data: list[tuple[bytes, str]] = []

    def on_recv(data: bytes, client_id: str) -> None:
        received_data.append((data, client_id))

    server = BLEServer(on_data_received=on_recv, backend=backend)
    await server.start()

    backend.emit_write(b"incoming_payload", "client_1")
    assert len(received_data) == 1
    assert received_data[0] == (b"incoming_payload", "client_1")

    await server.stop()


@pytest.mark.asyncio
async def test_server_send_notification() -> None:
    backend = MockBLEServerBackend()
    client = MockBleakClient(address="AA:01")
    backend.attach_client(client)

    server = BLEServer(backend=backend)
    await server.start()

    # Client subscribes
    received_notifications: list[bytes] = []

    def notify_cb(_char: object, data: bytearray) -> None:
        received_notifications.append(bytes(data))

    client.subscribed_char = "dummy_char"
    client.subscribed_callback = notify_cb

    await server.send_notification(b"notification_data")
    assert len(received_notifications) == 1
    assert received_notifications[0] == b"notification_data"

    await server.stop()


@pytest.mark.asyncio
async def test_server_send_when_not_started_raises() -> None:
    backend = MockBLEServerBackend()
    server = BLEServer(backend=backend)

    with pytest.raises(BLEError, match="not active"):
        await server.send_notification(b"data")
