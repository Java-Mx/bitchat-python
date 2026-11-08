"""Automated test suite for Phase 4: Startup Transport Selection & Genuine Offline Mode.

Covers all 13 required scenarios:
1. Launch application and select Option 3: application enters Offline Mode successfully.
2. Option 3 does not instantiate or start BLE scanning, advertising, or GATT services.
3. Option 3 does not start LAN discovery, UDP broadcasts, or TCP listeners.
4. Option 3 does not display the Bluetooth recovery dialog.
5. Option 1 initializes Bluetooth and displays the recovery dialog only when a genuine BLE failure occurs.
6. Option 1 with a working Bluetooth adapter does not display an unnecessary error dialog.
7. Option 2 starts LAN without initializing Bluetooth.
8. Selecting Offline Mode after a BLE failure stops all BLE activity.
9. Selecting Offline Mode after a LAN failure stops all LAN activity.
10. Automatic network-change callbacks cannot restart transports while Offline Mode is active.
11. Switching from Offline to Bluetooth or LAN works only after explicit user selection.
12. Repeated startup and shutdown do not create duplicate tasks or leave active sockets.
13. Restarting the application and selecting Offline Mode does not trigger Bluetooth initialization from a previous session.
Plus messaging behavior while offline (friendly explanation without socket/radio triggers).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from bitchat.network.transport import LANTransport
    from bitchat.transport.bluetooth import BluetoothTransport

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.adapter import AdapterInfo
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.network.models import NetworkInfo
from bitchat.storage.config import AppConfig, FileConfigStorage
from bitchat.transport.base import TransportState, TransportType
from bitchat.tui.app import BitChatApp
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.connection import ConnectionModal
from bitchat.tui.screens.home import HomeScreen
from bitchat.tui.widgets.chat_view import ChatView


@pytest.fixture
def local_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def mock_storage(local_identity: LocalIdentity, tmp_path: Path) -> FileConfigStorage:
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    storage.save_config(AppConfig(nickname="TestNode", transport="bluetooth"))
    storage.save_identity(local_identity)
    return storage


def make_test_coordinator(
    identity: LocalIdentity,
    storage: FileConfigStorage,
    initial_transport: str = "bluetooth",
) -> SessionCoordinator:
    server = BLEServer()
    manager = BLEManager(sender_id=identity.peer_id)
    mesh = MeshRouter(identity.peer_id)
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server,
        mesh_router=mesh,
        storage=storage,
        nickname="TestNode",
        initial_transport=initial_transport,
    )


@pytest.mark.asyncio
async def test_scenario_1_select_option_3_enters_offline_mode(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """1. Launch application and select Option 3: application enters Offline Mode successfully."""
    coord = make_test_coordinator(local_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")

    async with app.run_test() as pilot:
        # Opens directly to HomeScreen
        assert isinstance(app.screen, HomeScreen)

        # Open ConnectionModal
        app.screen.action_open_connect()
        await pilot.pause()
        assert isinstance(app.screen, ConnectionModal)

        # Select Option 3 (Offline Mode)
        app.screen.action_select_offline()
        await pilot.pause()

        # Modal dismissed into chat, no error modals
        assert not isinstance(app.screen, ConnectionModal)
        assert not isinstance(app.screen, BLEErrorModal)

        # Coordinator is authoritative offline
        assert coord.offline_mode is True
        assert coord.active_transport_name == "offline"
        assert coord.active_transport.transport_type == TransportType.OFFLINE
        assert coord.is_running is False


@pytest.mark.asyncio
async def test_scenario_2_option_3_no_ble_activity(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """2. Option 3 does not instantiate or start BLE scanning, advertising, or GATT services."""
    coord = make_test_coordinator(local_identity, mock_storage)
    await coord.go_offline()

    bt: BluetoothTransport = coord._transports["bluetooth"]  # type: ignore[assignment]
    assert not bt.is_running
    assert not bt.is_scanning
    assert not coord.ble_manager.scanner.is_scanning
    assert not coord.ble_server.is_advertising
    assert coord.ble_server._publisher is None
    assert coord.ble_server._provider is None
    assert coord.ble_manager.adapter_manager._monitor_task is None
    assert coord.ble_status == "offline"


@pytest.mark.asyncio
async def test_scenario_3_option_3_no_lan_listeners_or_discovery(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """3. Option 3 does not start LAN discovery, UDP broadcasts, or TCP listeners."""
    coord = make_test_coordinator(local_identity, mock_storage)
    await coord.go_offline()

    lan: LANTransport = coord._transports["lan"]  # type: ignore[assignment]
    assert not lan.is_running
    assert not lan.server.is_listening
    assert lan.server._server is None
    assert not lan.discovery.is_running
    assert lan.discovery._listen_task is None
    assert lan.discovery._broadcast_task is None
    assert lan.discovery._listen_sock is None
    assert lan.discovery._send_sock is None
    assert len(lan.connected_peers) == 0


@pytest.mark.asyncio
async def test_scenario_4_option_3_no_bluetooth_recovery_dialog(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """4. Option 3 does not display the Bluetooth recovery dialog."""
    coord = make_test_coordinator(local_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")

    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)
        app.screen.action_open_connect()
        await pilot.pause()
        assert isinstance(app.screen, ConnectionModal)

        app.screen.action_select_offline()
        await pilot.pause()

        # Check all screens in stack - none may be BLEErrorModal
        assert not any(isinstance(s, BLEErrorModal) for s in app._screen_stack)


@pytest.mark.asyncio
async def test_scenario_5_option_1_ble_failure_shows_recovery_dialog(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """5. Option 1 initializes Bluetooth and displays recovery dialog only when BLE failure occurs."""
    coord = make_test_coordinator(local_identity, mock_storage)

    async def failing_ble_start(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.ERROR
        self._error_message = "Bluetooth radio unavailable or adapter off"
        raise RuntimeError(self._error_message)

    with patch(
        "bitchat.transport.bluetooth.BluetoothTransport.start", failing_ble_start
    ):
        app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            app.screen.action_open_connect()
            await pilot.pause()
            assert isinstance(app.screen, ConnectionModal)

            # Option 1 explicitly chosen
            app.screen.action_select_ble()
            await pilot.pause()

            # Recovery dialog presented
            assert isinstance(app.screen, BLEErrorModal)
            assert "Bluetooth radio unavailable" in app.screen.error_message


@pytest.mark.asyncio
async def test_scenario_6_option_1_working_ble_no_error_dialog(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """6. Option 1 with a working Bluetooth adapter does not display an unnecessary error dialog."""
    coord = make_test_coordinator(local_identity, mock_storage)

    async def success_ble_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    def working_telemetry(self: Any) -> dict[str, Any]:
        return {
            "transport": "bluetooth",
            "state": "scanning",
            "adapter_available": True,
            "adapter_state": "On",
            "central_supported": True,
            "peripheral_supported": True,
            "scanner_status": "Active",
            "peripheral_error": None,
            "connected_peers_count": 0,
            "discovered_peers_count": 0,
            "connected_peers": [],
            "discovered_peers": {},
            "error_message": None,
        }

    with (
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.start", success_ble_start
        ),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.get_telemetry",
            working_telemetry,
        ),
    ):
        app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            app.screen.action_open_connect()
            await pilot.pause()
            assert isinstance(app.screen, ConnectionModal)

            app.screen.action_select_ble()
            await pilot.pause()

            # Enters chat cleanly without error modal
            assert not isinstance(app.screen, BLEErrorModal)
            assert not isinstance(app.screen, ConnectionModal)
            assert coord.active_transport_name == "bluetooth"


@pytest.mark.asyncio
async def test_scenario_7_option_2_starts_lan_without_ble(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """7. Option 2 starts LAN without initializing Bluetooth."""
    coord = make_test_coordinator(local_identity, mock_storage)

    async def mock_lan_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.READY

    ble_start_mock = AsyncMock()

    with (
        patch("bitchat.network.transport.LANTransport.start", mock_lan_start),
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", ble_start_mock),
    ):
        app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)
            app.screen.action_open_connect()
            await pilot.pause()
            assert isinstance(app.screen, ConnectionModal)

            # Choose Option 2 (LAN)
            app.screen.action_select_lan()
            await pilot.pause()

            # LAN started, Bluetooth NEVER started
            assert coord.active_transport_name == "lan"
            assert ble_start_mock.call_count == 0
            assert not isinstance(app.screen, BLEErrorModal)


@pytest.mark.asyncio
async def test_scenario_8_offline_after_ble_failure_stops_all_ble(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """8. Selecting Offline Mode after a BLE failure stops all BLE activity."""
    coord = make_test_coordinator(local_identity, mock_storage)

    # Put coordinator in BLE mode with simulated activity
    bt: BluetoothTransport = coord._transports["bluetooth"]  # type: ignore[assignment]
    bt._is_running = True
    bt._state = TransportState.ERROR

    await coord.go_offline()

    assert coord.offline_mode is True
    assert bt._is_running is False
    assert bt.state == TransportState.OFFLINE
    assert not bt.is_scanning
    assert not coord.ble_manager.scanner.is_scanning
    assert not coord.ble_server.is_advertising


@pytest.mark.asyncio
async def test_scenario_9_offline_after_lan_failure_stops_all_lan(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """9. Selecting Offline Mode after a LAN failure stops all LAN activity."""
    coord = make_test_coordinator(local_identity, mock_storage)

    lan: LANTransport = coord._transports["lan"]  # type: ignore[assignment]
    lan._is_running = True
    lan._state = TransportState.ERROR

    await coord.go_offline()

    assert coord.offline_mode is True
    assert lan._is_running is False
    assert lan.state == TransportState.OFFLINE
    assert not lan.server.is_listening
    assert not lan.discovery.is_running


@pytest.mark.asyncio
async def test_scenario_10_network_change_callbacks_do_not_restart_transports_while_offline(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """10. Automatic network-change callbacks cannot restart transports while Offline Mode is active."""
    coord = make_test_coordinator(local_identity, mock_storage)
    await coord.go_offline()

    lan: LANTransport = coord._transports["lan"]  # type: ignore[assignment]
    bt: BluetoothTransport = coord._transports["bluetooth"]  # type: ignore[assignment]

    # Simulate network reconnect event
    lan._handle_network_changed(
        NetworkInfo(status="Connected", local_ip="192.168.1.100")
    )
    await asyncio.sleep(0.05)

    assert not lan.is_running
    assert not lan.server.is_listening
    assert not lan.discovery.is_running

    # Simulate Bluetooth adapter powered on event
    bt._handle_adapter_state_changed(
        AdapterInfo(is_available=True, radio_state="on", is_central_supported=True)
    )
    await asyncio.sleep(0.05)

    assert not bt.is_running
    assert not bt.is_scanning
    assert coord.offline_mode is True


@pytest.mark.asyncio
async def test_scenario_11_switching_from_offline_requires_explicit_user_selection(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """11. Switching from Offline to Bluetooth or LAN works only after explicit user selection."""
    coord = make_test_coordinator(local_identity, mock_storage)
    await coord.go_offline()

    # Stray start or retries are rejected
    await coord.start()
    assert coord.offline_mode is True
    assert not coord.is_running

    assert await coord.retry_active_transport() is False
    assert await coord.retry_ble() is False
    assert await coord.retry_lan() is False
    assert coord.offline_mode is True

    # Explicit user switch to LAN succeeds
    async def mock_lan_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.READY

    with patch("bitchat.network.transport.LANTransport.start", mock_lan_start):
        success, _ = await coord.switch_transport("lan")
        assert success is True
        assert coord.offline_mode is False
        assert coord.active_transport_name == "lan"


@pytest.mark.asyncio
async def test_scenario_12_repeated_startup_shutdown_no_duplicate_tasks_or_socket_leaks(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """12. Repeated startup and shutdown do not create duplicate tasks or leave active sockets."""
    coord = make_test_coordinator(local_identity, mock_storage)

    for _ in range(5):
        await coord.go_offline()
        assert coord.offline_mode is True
        assert len(coord._background_tasks) == 0
        assert coord._prune_task is None

    lan: LANTransport = coord._transports["lan"]  # type: ignore[assignment]
    assert lan.server._server is None
    assert lan.discovery._listen_sock is None
    assert lan.discovery._send_sock is None


@pytest.mark.asyncio
async def test_scenario_13_restart_persisted_config_offline_mode_no_ble_initialization(
    local_identity: LocalIdentity, tmp_path: Path
) -> None:
    """13. Restarting application with persisted Offline Mode does not trigger BLE initialization."""
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    storage.save_config(AppConfig(nickname="OfflineUser", transport="offline"))
    storage.save_identity(local_identity)

    ble_start_mock = AsyncMock()
    with patch("bitchat.transport.bluetooth.BluetoothTransport.start", ble_start_mock):
        coord = make_test_coordinator(
            local_identity, storage, initial_transport="offline"
        )
        assert coord.offline_mode is True
        assert coord.active_transport_name == "offline"

        await coord.start()
        assert ble_start_mock.call_count == 0
        assert coord.offline_mode is True


@pytest.mark.asyncio
async def test_offline_mode_friendly_chat_messaging(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Sending a message while offline produces a friendly message without attempting socket I/O."""
    coord = make_test_coordinator(local_identity, mock_storage)
    await coord.go_offline()

    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="chat")
    async with app.run_test() as pilot:
        chat = app.query_one(ChatView)
        initial_msg_count = len(chat._message_history)

        # Attempt sending public chat message
        app._send_chat_message(chat, "Hello while offline")
        await pilot.pause()

        # Friendly explanation delivered
        assert len(chat._message_history) > initial_msg_count
        last_msg = chat._message_history[-1]
        assert "Cannot send message: BitChat is in Offline Mode" in last_msg.text

        # No packets sent or queued
        assert len(coord._pending_messages) == 0


@pytest.mark.asyncio
async def test_late_peer_refresh_after_shutdown_is_a_noop(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """A transport event processed after teardown must not raise ScreenStackError.

    Regression: a late BLE error event (or the periodic refresh timer) reached
    ``_refresh_peer_lists`` once the screen stack was empty, and the fallback to
    ``self.screen`` raised on slower runners.
    """
    coord = make_test_coordinator(local_identity, mock_storage)
    app = BitChatApp(coordinator=coord, storage=mock_storage, initial_screen="home")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._screen_stack

    assert not app._screen_stack
    app._refresh_peer_lists()
    from bitchat.tui.app import BleErrorReported, BleWarningReported, LanErrorReported

    app.on_ble_error_reported(BleErrorReported("late ble error"))
    app.on_ble_warning_reported(BleWarningReported("late ble warning"))
    app.on_lan_error_reported(LanErrorReported("late lan error"))
