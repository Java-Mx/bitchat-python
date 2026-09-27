"""Tests for BLEServer peripheral and advertising logic."""

from __future__ import annotations

import uuid

import pytest
from tests.ble.mocks import MockBleakClient, MockBLEServerBackend

from bitchat.ble.server import BLEServer
from bitchat.exceptions import BLEError
from bitchat.protocol.constants import BITCHAT_SERVICE_UUID


def test_manufacturer_advertisement_fits_legacy_ble_payload() -> None:
    from bitchat.ble.server import (
        _LEGACY_ADVERTISEMENT_MAX_BYTES,
        _MANUFACTURER_AD_STRUCTURE_OVERHEAD,
        _manufacturer_advertisement_payload,
    )

    payload = _manufacturer_advertisement_payload(BITCHAT_SERVICE_UUID)

    assert payload == b"BC" + uuid.UUID(BITCHAT_SERVICE_UUID).bytes
    assert len(payload) + _MANUFACTURER_AD_STRUCTURE_OVERHEAD <= (
        _LEGACY_ADVERTISEMENT_MAX_BYTES
    )


@pytest.mark.asyncio
async def test_wait_for_advertisement_status_rejects_failed_start() -> None:
    from types import SimpleNamespace

    with pytest.raises(BLEError, match="advertising failed with status 5"):
        await BLEServer._wait_for_advertisement_status(
            SimpleNamespace(status=5),
            "status",
            started_status=2,
            failed_statuses=(3, 4, 5),
            advertisement_type="BitChat discovery",
        )


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
