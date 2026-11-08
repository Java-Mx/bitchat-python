from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from textual.widgets import Button, Input

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.commands.parser import CommandParser
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.network.models import NetworkInfo
from bitchat.network.transport import LANTransport
from bitchat.storage.config import AppConfig, InMemoryStorage
from bitchat.transport.base import (
    TransportError,
    TransportState,
    TransportType,
    TransportWarning,
)
from bitchat.transport.bluetooth import BluetoothTransport
from bitchat.tui.app import BitChatApp, BleWarningReported
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.settings import SettingsScreen
from bitchat.tui.screens.telemetry import TelemetryScreen
from bitchat.tui.widgets.chat_view import ChatView
from bitchat.tui.widgets.status_bar import StatusBar


def _create_coordinator() -> SessionCoordinator:
    identity = LocalIdentity.generate()
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=BLEManager(sender_id=identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(identity.peer_id),
        initial_transport="bluetooth",
    )


def test_transport_errors_keep_their_origin_and_operation() -> None:
    coordinator = _create_coordinator()
    bluetooth = coordinator._transports["bluetooth"]
    lan = coordinator._transports["lan"]
    assert isinstance(lan, LANTransport)

    bluetooth_errors: list[TransportError] = []
    lan_errors: list[TransportError] = []
    coordinator.on_ble_error = bluetooth_errors.append
    coordinator.on_lan_error = lan_errors.append

    coordinator.active_transport = lan
    coordinator.active_transport_name = "lan"
    coordinator._wire_transport_callbacks(lan)

    bluetooth.report_error("peripheral_start", "BLE GATT unavailable")
    assert bluetooth_errors == []
    assert lan_errors == []

    lan.report_error(
        "tcp_server_listen",
        "Port already in use",
        stage="tcp_server_listen",
        original_error=OSError(10048, "Address already in use"),
        native_error_code=10048,
        hresult="0x80070020",
    )
    assert len(lan_errors) == 1
    assert lan_errors[0].transport == TransportType.LAN
    assert lan_errors[0].operation == "tcp_server_listen"
    assert lan_errors[0].message == "Port already in use"
    assert lan_errors[0].stage == "tcp_server_listen"
    assert lan_errors[0].occurred_at > 0
    assert lan_errors[0].native_error_code == 10048
    assert lan_errors[0].hresult == "0x80070020"
    assert "Address already in use" in (lan_errors[0].original_error or "")
    assert lan_errors[0].operation_id
    assert bluetooth_errors == []
    coordinator._starting_transport = bluetooth
    bluetooth.report_warning(
        "peripheral_start",
        "GATT advertising failed",
        stage="gatt_advertising",
        original_error=RuntimeError("native advertising status"),
    )
    coordinator._starting_transport = None
    history = coordinator.get_detailed_status()["transport_diagnostics"]
    assert history["bluetooth"][0]["kind"] == "warning"
    assert history["bluetooth"][0]["stage"] == "gatt_advertising"


@pytest.mark.asyncio
async def test_independent_ble_retry_keeps_lan_running() -> None:
    coordinator = _create_coordinator()
    lan = coordinator._transports["lan"]
    bluetooth = coordinator._transports["bluetooth"]
    assert isinstance(lan, LANTransport)
    assert isinstance(bluetooth, BluetoothTransport)
    coordinator.active_transport = lan
    coordinator.active_transport_name = "lan"
    coordinator.selected_transport_name = "lan"
    coordinator._is_running = True
    lan._is_running = True
    lan._state = TransportState.SCANNING

    async def start_ble() -> None:
        bluetooth._is_running = True
        bluetooth._state = TransportState.READY

    with (
        patch.object(bluetooth, "start", new=AsyncMock(side_effect=start_ble)) as start,
        patch.object(bluetooth, "stop", new=AsyncMock()) as stop,
        patch.object(lan, "start", new=AsyncMock()) as lan_start,
        patch.object(lan, "stop", new=AsyncMock()) as lan_stop,
    ):
        assert await coordinator.retry_ble_independent()

    start.assert_awaited_once()
    stop.assert_not_awaited()
    lan_start.assert_not_awaited()
    lan_stop.assert_not_awaited()
    assert coordinator.active_transport is lan
    assert coordinator.active_transport_name == "lan"
    assert lan.is_running


@pytest.mark.asyncio
async def test_selected_lan_does_not_start_ble_or_prestart_network_monitor() -> None:
    coordinator = _create_coordinator()
    coordinator.active_transport_name = "lan"
    lan = coordinator._transports["lan"]
    assert isinstance(lan, LANTransport)
    coordinator.active_transport = lan
    bluetooth = coordinator._transports["bluetooth"]

    async def start_lan() -> None:
        lan._is_running = True

    with (
        patch.object(lan, "start", new=AsyncMock(side_effect=start_lan)),
        patch.object(lan, "stop", new=AsyncMock()),
        patch.object(bluetooth, "stop", new=AsyncMock()),
        patch.object(coordinator, "send_announce", new=AsyncMock()),
        patch.object(coordinator, "_start_prune_task"),
        patch.object(
            lan.adapter_manager, "start_monitoring", new=AsyncMock()
        ) as start_monitoring,
    ):
        await coordinator.start()
        start_monitoring.assert_not_awaited()
        await coordinator.stop()


@pytest.mark.asyncio
async def test_coordinator_background_failures_are_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = _create_coordinator()

    async def fail() -> None:
        raise RuntimeError("background crash cause")

    task = coordinator._spawn_task(fail())
    with pytest.raises(RuntimeError, match="background crash cause"):
        await task
    await asyncio.sleep(0)

    assert "Coordinator background task failed" in caplog.text
    assert "background crash cause" in caplog.text
    assert task not in coordinator._background_tasks


@pytest.mark.parametrize("category", ["general", "network", "bluetooth", "appearance"])
def test_configure_categories_open_their_settings_category(category: str) -> None:
    app = BitChatApp(storage=InMemoryStorage(), config=AppConfig())
    chat = ChatView()
    command = CommandParser().parse(f"/configure {category}")

    with patch.object(app, "action_open_settings") as open_settings:
        app._handle_configure_command(command, chat)

    open_settings.assert_called_once_with(category=category)


def test_configure_without_category_runs_diagnostics() -> None:
    app = BitChatApp(storage=InMemoryStorage(), config=AppConfig())
    chat = ChatView()
    command = CommandParser().parse("/configure")

    with (
        patch.object(app, "_display_configure_diagnostics") as show_diagnostics,
        patch.object(app, "action_open_settings") as open_settings,
    ):
        app._handle_configure_command(command, chat)

    show_diagnostics.assert_called_once_with(chat)
    open_settings.assert_not_called()


@pytest.mark.asyncio
async def test_stale_ble_warning_is_not_shown_in_lan_mode() -> None:
    coordinator = _create_coordinator()
    coordinator.active_transport_name = "lan"
    coordinator.active_transport = coordinator._transports["lan"]
    coordinator.start = AsyncMock()  # type: ignore[method-assign]
    app = BitChatApp(
        coordinator=coordinator,
        storage=InMemoryStorage(),
        config=AppConfig(),
        initial_screen="chat",
    )
    warning = TransportWarning(
        TransportType.BLUETOOTH, "peripheral_start", "GATT advertising failed"
    )

    async with app.run_test() as pilot:
        app.post_message(BleWarningReported(warning, coordinator.transport_generation))
        await pilot.pause()
        assert not any(
            isinstance(screen, BLEErrorModal) for screen in app._screen_stack
        )


@pytest.mark.asyncio
async def test_lan_presentation_hides_ble_failure_but_telemetry_retains_it() -> None:
    coordinator = _create_coordinator()
    lan = coordinator._transports["lan"]
    bluetooth = coordinator._transports["bluetooth"]
    assert isinstance(lan, LANTransport)
    assert isinstance(bluetooth, BluetoothTransport)
    coordinator.active_transport = lan
    coordinator.active_transport_name = "lan"
    coordinator.selected_transport_name = "lan"
    coordinator._is_running = True
    coordinator.offline_mode = False
    lan._is_running = True
    lan._state = TransportState.SCANNING
    lan.adapter_manager._current_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="Test",
        local_ip="192.0.2.10",
    )
    coordinator._starting_transport = bluetooth
    bluetooth.report_warning(
        "peripheral_start",
        "GATT advertising failed",
        stage="gatt_advertising",
        original_error=RuntimeError("native advertising status"),
    )
    coordinator._starting_transport = None
    coordinator.start = AsyncMock()  # type: ignore[method-assign]
    app = BitChatApp(
        coordinator=coordinator,
        storage=InMemoryStorage(),
        config=AppConfig(transport="lan"),
        initial_screen="chat",
    )

    with patch.object(TelemetryScreen, "_refresh_system_network", new=AsyncMock()):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._refresh_peer_lists()
            status = app.query_one(StatusBar).status_message
            assert "LAN / Wi-Fi Active" in status
            assert "BLE Peripheral Failed" not in status
            assert "GATT advertising failed" not in status

            app.post_message(
                BleWarningReported(
                    TransportWarning(
                        TransportType.BLUETOOTH,
                        "peripheral_start",
                        "GATT advertising failed",
                    ),
                    coordinator.transport_generation,
                )
            )
            await pilot.pause()
            assert not any(
                isinstance(screen, BLEErrorModal) for screen in app._screen_stack
            )
            assert "GATT advertising failed" not in str(
                app.query_one(ChatView)._message_history
            )

            app.action_open_telemetry()
            await pilot.pause()
            telemetry_error = app.screen.query_one("#telem-ble-error")
            assert "GATT advertising failed" in str(telemetry_error.render())


@pytest.mark.asyncio
async def test_ble_warning_during_explicit_switch_shows_recovery_choices() -> None:
    coordinator = _create_coordinator()
    lan = coordinator._transports["lan"]
    bluetooth = coordinator._transports["bluetooth"]
    assert isinstance(lan, LANTransport)
    assert isinstance(bluetooth, BluetoothTransport)
    coordinator.active_transport = lan
    coordinator.active_transport_name = "lan"
    coordinator.selected_transport_name = "lan"
    coordinator._is_running = True
    coordinator.offline_mode = False
    lan._is_running = True
    lan._state = TransportState.SCANNING
    bluetooth_telemetry = {
        "adapter_state": "On",
        "central_supported": True,
        "scanner_status": "Active",
        "peripheral_supported": True,
        "peripheral_error": "GATT advertising failed",
    }
    bluetooth.get_telemetry = lambda: bluetooth_telemetry
    coordinator.start = AsyncMock()  # type: ignore[method-assign]
    coordinator.send_announce = AsyncMock()  # type: ignore[method-assign]
    coordinator._start_prune_task = lambda: None  # type: ignore[method-assign]

    async def fail_peripheral_start() -> None:
        bluetooth._is_running = True
        bluetooth._state = TransportState.SCANNING
        bluetooth.report_warning(
            "peripheral_start",
            "GATT advertising failed",
            stage="gatt_advertising",
        )

    app = BitChatApp(
        coordinator=coordinator,
        storage=InMemoryStorage(),
        config=AppConfig(transport="lan"),
        initial_screen="chat",
    )
    app._ble_warning_acknowledged = True

    with (
        patch.object(TelemetryScreen, "_refresh_system_network", new=AsyncMock()),
        patch.object(bluetooth, "start", new=fail_peripheral_start),
        patch.object(lan, "stop", new=AsyncMock()),
    ):
        async with app.run_test(size=(120, 45)) as pilot:
            app._handle_transport_switch("bluetooth")
            assert app._transport_switch_task is not None
            await app._transport_switch_task
            await pilot.pause()

            assert isinstance(app.screen, BLEErrorModal)
            button_ids = {button.id for button in app.screen.query(Button)}
            assert button_ids == {
                "btn-ble-retry",
                "btn-ble-lan",
                "btn-ble-close",
            }


@pytest.mark.asyncio
async def test_settings_populates_persisted_fields_before_network_diagnostics() -> None:
    config = AppConfig(nickname="Saved Nickname")
    app = BitChatApp(
        storage=InMemoryStorage(),
        config=config,
        initial_screen="chat",
    )

    async def hold_diagnostics(self: SettingsScreen) -> None:
        await asyncio.Event().wait()

    with patch.object(SettingsScreen, "_refresh_network_information", hold_diagnostics):
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            assert (
                app.screen.query_one("#settings-input-nickname", Input).value
                == "Saved Nickname"
            )
            app.pop_screen()
            await pilot.pause()
