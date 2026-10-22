"""TUI recovery dialog: OS-specific guidance comes from the platform layer."""

from __future__ import annotations

import sys
from typing import Any

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend
from textual.widgets import Button, Static

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.bluetooth import BluetoothTransport
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.widgets.status_bar import StatusBar


def _dialog_text(app: BitChatApp) -> str:
    return " ".join(
        str(widget.content)
        for widget in app.screen.query(".ble-error-text").results(Static)
    )


def _button_labels(app: BitChatApp) -> list[str]:
    return [str(b.label) for b in app.screen.query(Button)]


@pytest.mark.parametrize(
    ("platform_id", "expected", "forbidden"),
    [
        ("linux", "bluetoothd", "Windows"),
        ("win32", "Windows Settings", "bluetoothd"),
    ],
)
async def test_hardware_error_dialog_guidance_matches_platform(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected: str, forbidden: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(BLEErrorModal(error_message="No adapter"))
        await pilot.pause()

        text = _dialog_text(app)
        assert expected in text
        assert forbidden not in text
        # Missing hardware must never show the GATT-specific explanation.
        assert "GATT" not in text


@pytest.mark.parametrize(
    ("platform_id", "expected", "forbidden"),
    [
        ("linux", "BlueZ", "Windows"),
        ("win32", "Windows can abort GATT advertising", "BlueZ"),
    ],
)
async def test_gatt_failure_dialog_guidance_matches_platform(
    monkeypatch: pytest.MonkeyPatch, platform_id: str, expected: str, forbidden: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform_id)
    app = BitChatApp()
    async with app.run_test() as pilot:
        await app.push_screen(
            BLEErrorModal(
                error_message="GATT failed",
                bluetooth_available=True,
                peripheral_supported=True,
            )
        )
        await pilot.pause()

        text = _dialog_text(app)
        assert expected in text
        assert forbidden not in text
        assert _button_labels(app) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]


class _StaticAdapterBackend:
    def __init__(self, info: AdapterInfo) -> None:
        self.info = info

    async def check_adapter(self) -> AdapterInfo:
        return self.info


def _make_test_coordinator(
    *,
    adapter_info: AdapterInfo,
    server: BLEServer | None = None,
    fail_discovery: bool = False,
) -> SessionCoordinator:
    identity = LocalIdentity.generate()
    adapter_mgr = BLEAdapterManager(custom_backend=_StaticAdapterBackend(adapter_info))
    manager = BLEManager(
        sender_id=identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        adapter_manager=adapter_mgr,
    )
    if fail_discovery:

        async def _raise_discovery(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Scanner start failed")

        manager.start_discovery = _raise_discovery  # type: ignore[method-assign]

    ble_server = server or BLEServer(backend=MockBLEServerBackend())
    storage = InMemoryStorage()
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=ble_server,
        storage=storage,
        nickname="Alice",
    )


async def test_status_bar_supported_peripheral_capability_active() -> None:
    """When both Central and Peripheral roles are supported and active,
    the status bar accurately reports '● Bluetooth Ready • BLE Central + Peripheral'.
    """
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
    )
    coord = _make_test_coordinator(adapter_info=info)
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_bar = app.query_one(StatusBar)
        assert status_bar.mesh_status == "● Bluetooth Ready • BLE Central + Peripheral"
        assert (
            status_bar.status_message == "● Bluetooth Ready • BLE Central + Peripheral"
        )
        assert not any(isinstance(s, BLEErrorModal) for s in app._screen_stack)
    await coord.stop()


async def test_status_bar_supported_peripheral_capability_idle() -> None:
    """When peripheral role is supported but peripheral is not currently advertising,
    the status bar accurately reports '● Bluetooth Available • BLE Central Mode'.
    """
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
    )
    server_backend = MockBLEServerBackend()
    coord = _make_test_coordinator(
        adapter_info=info, server=BLEServer(backend=server_backend)
    )
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Peripheral stops advertising while central scanning remains active
        coord.ble_server._is_advertising = False
        app._refresh_peer_lists()
        status_bar = app.query_one(StatusBar)
        assert status_bar.mesh_status == "● Bluetooth Available • BLE Central Mode"
        assert status_bar.status_message == "● Bluetooth Available • BLE Central Mode"
    await coord.stop()


async def test_status_bar_unsupported_peripheral_capability_on_linux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux/Ubuntu where peripheral role is unsupported by BitChat's backend,
    Central mode is preserved and the status bar accurately reports:
    '● Bluetooth Available • BLE Central Mode • Peripheral Unsupported'.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
    )
    # Native BLEServer without custom backend: supports_peripheral is False on Linux
    real_server = BLEServer()
    assert real_server.supports_peripheral is False

    coord = _make_test_coordinator(adapter_info=info, server=real_server)
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_bar = app.query_one(StatusBar)
        assert (
            status_bar.mesh_status
            == "● Bluetooth Available • BLE Central Mode • Peripheral Unsupported"
        )
        assert (
            status_bar.status_message
            == "● Bluetooth Available • BLE Central Mode • Peripheral Unsupported"
        )

        # Truthful telemetry and preserved Central-mode functionality
        telemetry = coord.active_transport.get_telemetry()
        assert telemetry["peripheral_supported"] is False
        assert telemetry["advertising_active"] is False
        assert telemetry["gatt_server_status"] == "Unsupported"
        assert telemetry["scanner_status"] == "Active"
        assert coord.is_running is True
        assert coord.ble_status == "scanning"
        assert isinstance(coord.active_transport, BluetoothTransport)
        assert coord.active_transport.is_scanning is True

        # Expected limitation must not pop up an intrusive error recovery dialog
        assert not any(isinstance(s, BLEErrorModal) for s in app._screen_stack)
    await coord.stop()


async def test_status_bar_adapter_hardware_unsupported_peripheral() -> None:
    """When the Bluetooth adapter hardware itself does not support peripheral role,
    the status bar reports
    '● Bluetooth Available • BLE Central Mode • Peripheral Unsupported'
    and the 3-choice recovery modal is presented explaining the adapter limitation.
    """
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=False,
    )
    coord = _make_test_coordinator(adapter_info=info, server=BLEServer())
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_bar = app.query_one(StatusBar)
        assert (
            status_bar.mesh_status
            == "● Bluetooth Available • BLE Central Mode • Peripheral Unsupported"
        )
        assert (
            status_bar.status_message
            == "● Bluetooth Available • BLE Central Mode • Peripheral Unsupported"
        )
        assert isinstance(app.screen, BLEErrorModal)
        assert _button_labels(app) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
    await coord.stop()


async def test_status_bar_peripheral_startup_failure_shows_warning_and_modal() -> None:
    """When peripheral advertising fails on startup, the status bar reports
    'Peripheral Advertising Failed', central scanning remains active,
    and the 3-choice recovery modal is presented.
    """
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
    )
    server_backend = MockBLEServerBackend()
    server_backend.start_errors.append(
        RuntimeError("WinRT GATT service initialization failed (status 3)")
    )
    coord = _make_test_coordinator(
        adapter_info=info, server=BLEServer(backend=server_backend)
    )
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_bar = app.query_one(StatusBar)
        expected_status = (
            "● Bluetooth Available • BLE Central Mode • Peripheral Advertising Failed"
        )
        assert status_bar.mesh_status == expected_status
        assert status_bar.status_message == expected_status
        assert isinstance(coord.active_transport, BluetoothTransport)
        assert coord.active_transport.is_scanning is True

        # Recovery modal is presented with the existing three choices unchanged
        assert isinstance(app.screen, BLEErrorModal)
        assert _button_labels(app) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
    await coord.stop()


async def test_status_bar_ble_startup_error_with_radio_on() -> None:
    """When adapter radio is ON but BLE transport startup fails completely,
    the status bar reports '● BLE Error • Bluetooth Available' and shows the
    recovery modal.
    """
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
    )
    coord = _make_test_coordinator(adapter_info=info, fail_discovery=True)
    app = BitChatApp(coordinator=coord)
    async with app.run_test() as pilot:
        await pilot.pause()
        status_bar = app.query_one(StatusBar)
        assert status_bar.mesh_status == "● BLE Error • Bluetooth Available"
        assert status_bar.status_message == "● BLE Error • Bluetooth Available"
        assert isinstance(app.screen, BLEErrorModal)
        assert _button_labels(app) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
    await coord.stop()


async def test_status_bar_bluetooth_disabled_and_unavailable() -> None:
    """When Bluetooth is disabled (radio Off) or unavailable, the status bar
    reports '✕ BLE Offline • Bluetooth Disabled' or
    '✕ BLE Offline • Bluetooth Unavailable'.
    """
    # Radio Off
    info_off = AdapterInfo(is_available=True, radio_state="off")
    coord_off = _make_test_coordinator(adapter_info=info_off)
    app_off = BitChatApp(coordinator=coord_off)
    async with app_off.run_test() as pilot:
        await pilot.pause()
        status_bar = app_off.query_one(StatusBar)
        assert status_bar.mesh_status == "✕ BLE Offline • Bluetooth Disabled"
        assert status_bar.status_message == "✕ BLE Offline • Bluetooth Disabled"
        assert isinstance(app_off.screen, BLEErrorModal)
        assert _button_labels(app_off) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
    await coord_off.stop()

    # Radio Unavailable
    info_unavail = AdapterInfo(is_available=False, radio_state="unavailable")
    coord_unavail = _make_test_coordinator(adapter_info=info_unavail)
    app_unavail = BitChatApp(coordinator=coord_unavail)
    async with app_unavail.run_test() as pilot:
        await pilot.pause()
        status_bar = app_unavail.query_one(StatusBar)
        assert status_bar.mesh_status == "✕ BLE Offline • Bluetooth Unavailable"
        assert status_bar.status_message == "✕ BLE Offline • Bluetooth Unavailable"
        assert isinstance(app_unavail.screen, BLEErrorModal)
        assert _button_labels(app_unavail) == [
            "Retry Adapter",
            "Continue Wi-Fi/LAN",
            "Continue Offline",
        ]
    await coord_unavail.stop()
