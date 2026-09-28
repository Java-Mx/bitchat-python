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


@pytest.mark.asyncio
async def test_wait_for_gatt_status_started_succeeds() -> None:
    """GATT status 2 (Started) must resolve without error."""
    from types import SimpleNamespace

    provider = SimpleNamespace(advertisement_status=2)
    # Must complete without raising
    result = await BLEServer._wait_for_gatt_advertisement_status(provider)
    assert result is True


@pytest.mark.asyncio
async def test_wait_for_gatt_status_partial_start_is_success() -> None:
    """GATT status 4 (StartedWithoutAllAdvertisementData) is NOT a failure.

    Windows returns this when the adapter starts GATT advertising but cannot include
    all service metadata in the advertisement packet (e.g. because of payload size
    constraints). The GATT service is still active and usable.
    """
    from types import SimpleNamespace

    provider = SimpleNamespace(advertisement_status=4)
    # Must NOT raise -- status 4 is a partial success, not an error
    result = await BLEServer._wait_for_gatt_advertisement_status(provider)
    assert result is True


@pytest.mark.asyncio
async def test_wait_for_gatt_status_aborted_raises() -> None:
    """GATT status 3 (Aborted) must raise BLEError."""
    from types import SimpleNamespace

    provider = SimpleNamespace(advertisement_status=3)
    with pytest.raises(BLEError, match="status 3"):
        await BLEServer._wait_for_gatt_advertisement_status(provider)


@pytest.mark.asyncio
async def test_wait_for_gatt_status_timeout_raises() -> None:
    """Remaining in Created(0)/Stopped(1) past timeout must raise BLEError."""
    from types import SimpleNamespace

    provider = SimpleNamespace(advertisement_status=0)
    import bitchat.ble.server as server_mod

    original = server_mod._ADVERTISEMENT_START_TIMEOUT_SECONDS
    server_mod._ADVERTISEMENT_START_TIMEOUT_SECONDS = 0.1
    try:
        with pytest.raises(BLEError, match="did not start within timeout"):
            await BLEServer._wait_for_gatt_advertisement_status(provider)
    finally:
        server_mod._ADVERTISEMENT_START_TIMEOUT_SECONDS = original


@pytest.mark.asyncio
async def test_server_backend_start_failure_cleanup() -> None:
    """Backend start failure must not leave server marked as advertising."""
    backend = MockBLEServerBackend()
    backend.start_errors.append(RuntimeError("simulated GATT status 3"))
    server = BLEServer(backend=backend)

    with pytest.raises(Exception, match="simulated GATT status 3"):
        await server.start()

    assert server.is_advertising is False
    assert server._last_error is not None
    assert "simulated GATT status 3" in server._last_error
