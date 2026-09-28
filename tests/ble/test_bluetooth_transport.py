"""Tests for independent BLE central and peripheral startup."""

from __future__ import annotations

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.exceptions import BLEError
from bitchat.transport.base import TransportState
from bitchat.transport.bluetooth import BluetoothTransport


class StaticAdapterBackend:
    def __init__(self, info: AdapterInfo) -> None:
        self.info = info

    async def check_adapter(self) -> AdapterInfo:
        return self.info


def make_transport(
    info: AdapterInfo,
    backend: MockBLEServerBackend | None = None,
) -> tuple[BluetoothTransport, MockBLEServerBackend]:
    server_backend = backend or MockBLEServerBackend()
    adapter_manager = BLEAdapterManager(
        custom_backend=StaticAdapterBackend(info),
    )
    manager = BLEManager(
        sender_id=b"\x01" * 8,
        scanner_factory=lambda **kwargs: MockBleakScanner(
            kwargs["detection_callback"], kwargs["service_uuids"]
        ),
        adapter_manager=adapter_manager,
    )
    server = BLEServer(backend=server_backend)
    return BluetoothTransport(manager, server), server_backend


def adapter_info(
    *,
    radio_state: str = "on",
    central: bool = True,
    peripheral: bool = True,
    advertising: bool = False,
) -> AdapterInfo:
    return AdapterInfo(
        is_available=True,
        radio_state=radio_state,
        is_central_supported=central,
        is_peripheral_supported=peripheral,
        is_advertisement_offload_supported=advertising,
        device_id="test-adapter",
        name="Test Bluetooth",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("info", "expected_state", "message"),
    [
        (
            AdapterInfo(is_available=False, radio_state="unavailable"),
            TransportState.UNAVAILABLE,
            "Bluetooth unavailable",
        ),
        (
            adapter_info(radio_state="off"),
            TransportState.DISABLED,
            "Bluetooth disabled",
        ),
    ],
)
async def test_adapter_missing_or_radio_off_does_not_start_ble_roles(
    info: AdapterInfo,
    expected_state: TransportState,
    message: str,
) -> None:
    transport, backend = make_transport(info)

    with pytest.raises(RuntimeError, match=message):
        await transport.start()

    assert transport.state == expected_state
    assert backend.start_attempts == 0
    assert not transport.is_scanning
    assert not transport.ble_server.is_advertising

    await transport.stop()


@pytest.mark.asyncio
async def test_adapter_without_either_ble_role_is_not_reported_as_radio_off() -> None:
    transport, backend = make_transport(adapter_info(central=False, peripheral=False))
    errors: list[str] = []
    transport.on_error = errors.append

    with pytest.raises(RuntimeError, match="neither BLE central nor peripheral"):
        await transport.start()

    telemetry = transport.get_telemetry()
    assert transport.state == TransportState.ERROR
    assert telemetry["adapter_state"] == "On"
    assert telemetry["central_supported"] is False
    assert telemetry["peripheral_supported"] is False
    assert backend.start_attempts == 0
    assert not transport.is_scanning
    assert errors == [
        "Bluetooth adapter supports neither BLE central nor peripheral operation"
    ]

    await transport.stop()


@pytest.mark.asyncio
async def test_central_scanning_remains_available_without_peripheral_role() -> None:
    transport, backend = make_transport(adapter_info(peripheral=False))
    warnings: list[str] = []
    transport.on_warning = warnings.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert transport.state == TransportState.SCANNING
    assert transport.is_scanning
    assert backend.start_attempts == 0
    assert telemetry["adapter_available"] is True
    assert telemetry["radio_state"] == "on"
    assert telemetry["central_supported"] is True
    assert telemetry["peripheral_supported"] is False
    assert telemetry["advertisement_offload_supported"] is False
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Unsupported"
    assert warnings == ["BLE peripheral role is not supported by the adapter"]

    await transport.stop()


@pytest.mark.asyncio
async def test_supported_peripheral_role_advertises_and_scans() -> None:
    transport, backend = make_transport(adapter_info(advertising=False))

    await transport.start()

    telemetry = transport.get_telemetry()
    assert backend.start_attempts == 1
    assert backend.is_started
    assert transport.is_scanning
    assert telemetry["central_supported"] is True
    assert telemetry["peripheral_supported"] is True
    assert telemetry["advertisement_offload_supported"] is False
    assert telemetry["advertising_active"] is True
    assert telemetry["gatt_server_status"] == "Advertising"

    await transport.stop()


@pytest.mark.asyncio
async def test_gatt_status_three_preserves_central_mode_and_diagnostic() -> None:
    backend = MockBLEServerBackend()
    backend.start_errors.append(
        BLEError("GATT service advertising failed with status 3")
    )
    transport, _ = make_transport(adapter_info(), backend)
    warnings: list[str] = []
    errors: list[str] = []
    transport.on_warning = warnings.append
    transport.on_error = errors.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert transport.state == TransportState.SCANNING
    assert transport.is_scanning
    assert telemetry["adapter_state"] == "On"
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Failed"
    assert "status 3" in telemetry["peripheral_error"]
    assert warnings == [telemetry["peripheral_error"]]
    assert errors == []
    assert backend.is_started is False
    assert backend.stop_attempts == 1

    await transport.stop()


@pytest.mark.asyncio
async def test_retry_after_gatt_failure_releases_resources_and_recovers() -> None:
    backend = MockBLEServerBackend()
    backend.start_errors.append(
        BLEError("GATT service advertising failed with status 3")
    )
    transport, _ = make_transport(adapter_info(), backend)

    await transport.start()
    assert not transport.ble_server.is_advertising
    assert backend.stop_attempts == 1

    await transport.stop()
    await transport.start()

    assert backend.start_attempts == 2
    assert backend.is_started
    assert transport.ble_server.is_advertising
    assert transport.is_scanning

    await transport.stop()
    assert not backend.is_started


@pytest.mark.asyncio
async def test_peripheral_only_adapter_does_not_start_central_scanner() -> None:
    transport, backend = make_transport(adapter_info(central=False, peripheral=True))

    await transport.start()

    assert backend.start_attempts == 1
    assert transport.ble_server.is_advertising
    assert not transport.is_scanning
    assert transport.state == TransportState.READY

    await transport.stop()
