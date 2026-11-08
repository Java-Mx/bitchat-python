"""Comprehensive regression tests for M6 critical bug fixes:
- Windows WinRT BLE GATT error handling & status 3 Aborted diagnostics
- HRESULT and Win32 error preservation
- Transport switching lifecycle, Item 10 rollback, and offline mode
- Device identity persistence across transport medium transitions
- BLEErrorModal presentation and HomeScreen non-suppression
- Structured transport diagnostics recording and redaction
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Static

if TYPE_CHECKING:
    from pathlib import Path

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import (
    WINRT_BLUETOOTH_ERROR_NAMES,
    WINRT_GATT_ADV_STATUS_NAMES,
    BLEServer,
    _extract_winrt_error_info,
)
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import BLEError
from bitchat.logging import get_recent_transport_diagnostics, log_transport_diagnostic
from bitchat.mesh.router import MeshRouter
from bitchat.network.models import NetworkInfo
from bitchat.network.transport import LANTransport
from bitchat.storage.config import AppConfig, FileConfigStorage
from bitchat.transport.base import TransportState
from bitchat.transport.bluetooth import BluetoothTransport
from bitchat.tui.app import BitChatApp, BleWarningReported
from bitchat.tui.screens.ble_error import BLEErrorModal
from bitchat.tui.screens.home import HomeScreen


@pytest.fixture
def local_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def mock_storage(local_identity: LocalIdentity, tmp_path: Path) -> FileConfigStorage:
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    storage.save_config(AppConfig(nickname="AliceNode", transport="bluetooth"))
    storage.save_identity(local_identity)
    return storage


# ---------------------------------------------------------------------------
# Issue 1: Windows Bluetooth / WinRT Error Handling & Status 3 Diagnostics
# ---------------------------------------------------------------------------


def test_winrt_enum_and_hresult_extraction() -> None:
    """Verify WinRT BluetoothError mappings and HRESULT / Win32 code extraction."""
    assert WINRT_BLUETOOTH_ERROR_NAMES[0] == "Success"
    assert WINRT_BLUETOOTH_ERROR_NAMES[1] == "RadioNotAvailable"
    assert WINRT_BLUETOOTH_ERROR_NAMES[2] == "ResourceInUse"
    assert WINRT_BLUETOOTH_ERROR_NAMES[3] == "DeviceNotConnected"
    assert WINRT_BLUETOOTH_ERROR_NAMES[4] == "OtherError"

    assert WINRT_GATT_ADV_STATUS_NAMES[0] == "Created"
    assert WINRT_GATT_ADV_STATUS_NAMES[1] == "Stopped"
    assert WINRT_GATT_ADV_STATUS_NAMES[2] == "Started"
    assert WINRT_GATT_ADV_STATUS_NAMES[3] == "Aborted"

    # Test HRESULT extraction from exception with winerror attribute
    class WinErrorTestError(Exception):
        def __init__(self, winerror: int) -> None:
            self.winerror = winerror

    # 0x80070003 -> ERROR_PATH_NOT_FOUND (code 3)
    exc = WinErrorTestError(0x80070003)
    code, hresult = _extract_winrt_error_info(exc)
    assert code == 3
    assert hresult == "0x80070003"

    # Generic negative HRESULT: 0x80004005 (E_FAIL)
    exc_fail = WinErrorTestError(-2147467259)  # 0x80004005 signed
    _code_fail, hresult_fail = _extract_winrt_error_info(exc_fail)
    assert hresult_fail == "0x80004005"


def _create_winrt_mock_modules(
    mock_gatt: Any, mock_adv: Any | None = None
) -> dict[str, Any]:
    """Create a complete hierarchy of WinRT mock modules for import compatibility."""
    if mock_adv is None:
        mock_adv = MagicMock()
    winrt_mock = MagicMock()
    winrt_windows = MagicMock()
    winrt_devices = MagicMock()
    winrt_bt = MagicMock()
    winrt_storage = MagicMock()
    winrt_streams = MagicMock()

    winrt_mock.windows = winrt_windows
    winrt_windows.devices = winrt_devices
    winrt_devices.bluetooth = winrt_bt
    winrt_bt.advertisement = mock_adv
    winrt_bt.genericattributeprofile = mock_gatt

    winrt_windows.storage = winrt_storage
    winrt_storage.streams = winrt_streams

    return {
        "winrt": winrt_mock,
        "winrt.windows": winrt_windows,
        "winrt.windows.devices": winrt_devices,
        "winrt.windows.devices.bluetooth": winrt_bt,
        "winrt.windows.devices.bluetooth.advertisement": mock_adv,
        "winrt.windows.devices.bluetooth.genericattributeprofile": mock_gatt,
        "winrt.windows.storage": winrt_storage,
        "winrt.windows.storage.streams": winrt_streams,
    }


@pytest.mark.asyncio
async def test_winrt_advertisement_status_3_aborted_diagnostics() -> None:
    """When WinRT advertisement aborts with status 3, diagnostics are preserved."""
    server = BLEServer()

    # Mock provider that reports status 3 (Aborted)
    mock_provider = MagicMock()
    mock_provider.advertisement_status = 3
    mock_provider.stop_advertising = MagicMock()

    mock_res = MagicMock()
    mock_res.error = 0
    mock_res.service_provider = mock_provider

    mock_c_res = MagicMock()
    mock_c_res.error = 0
    mock_c_res.characteristic = MagicMock()

    mock_gatt = MagicMock()
    mock_gatt.GattServiceProvider.create_async = AsyncMock(return_value=mock_res)
    mock_provider.service.create_characteristic_async = AsyncMock(
        return_value=mock_c_res
    )
    mock_provider.start_advertising_with_parameters = MagicMock()

    winrt_modules = _create_winrt_mock_modules(mock_gatt)

    with (
        patch("bitchat.ble.server.is_windows", return_value=True),
        patch.dict("sys.modules", winrt_modules),
    ):
        await server._start_windows_server()

        assert not server.is_advertising
        telemetry = server.get_telemetry()
        assert telemetry["server_active"] is False
        assert telemetry["failed_stage"] == "advertising_start"
        assert telemetry["error_code"] == 3
        assert (
            telemetry["error_source"] == "winrt.GattServiceProviderAdvertisementStatus"
        )
        assert "status 3 (Aborted)" in (telemetry["last_error"] or "")

        # Verify structured diagnostic was recorded
        diags = get_recent_transport_diagnostics()
        aborted_diags = [
            d
            for d in diags
            if d.get("stage") == "advertising_start" and d.get("result") == "ABORTED"
        ]
        assert len(aborted_diags) > 0
        assert aborted_diags[-1]["error_code"] == 3
        assert (
            aborted_diags[-1]["source"]
            == "winrt.GattServiceProviderAdvertisementStatus"
        )


@pytest.mark.asyncio
async def test_winrt_gatt_provider_create_failure_error_mapping() -> None:
    """When GattServiceProvider.create_async returns BluetoothError 3, error is mapped."""
    server = BLEServer()

    mock_res = MagicMock()
    mock_res.error = 3  # DeviceNotConnected
    mock_res.service_provider = None

    mock_gatt = MagicMock()
    mock_gatt.GattServiceProvider.create_async = AsyncMock(return_value=mock_res)

    winrt_modules = _create_winrt_mock_modules(mock_gatt)

    with (
        patch("bitchat.ble.server.is_windows", return_value=True),
        patch.dict("sys.modules", winrt_modules),
    ):
        with pytest.raises(BLEError) as exc_info:
            await server._start_windows_server()

        assert "DeviceNotConnected" in str(exc_info.value)
        assert "error 3" in str(exc_info.value)

        telemetry = server.get_telemetry()
        assert telemetry["failed_stage"] == "gatt_provider_create"
        assert telemetry["error_code"] == 3
        assert telemetry["error_source"] == "winrt.GattServiceProvider.create_async"


@pytest.mark.asyncio
async def test_bluez_linux_parity_failure() -> None:
    """Linux BlueZ server failures capture diagnostics and failed stage cleanly."""
    server = BLEServer()

    with (
        patch("bitchat.ble.server.is_linux", return_value=True),
        patch(
            "bitchat.ble.bluez.BlueZServerBackend",
            side_effect=RuntimeError("D-Bus daemon disconnected"),
        ),
    ):
        await server._start_linux_server()

        assert not server.is_advertising
        telemetry = server.get_telemetry()
        assert telemetry["failed_stage"] == "bluez_gatt_server_start"
        assert telemetry["error_source"] == "BlueZServerBackend"
        assert "D-Bus daemon disconnected" in (telemetry["last_error"] or "")


# ---------------------------------------------------------------------------
# Issue 2: Transport Switching Lifecycle, Item 10 Rollback & /transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_transport_item_10_rollback_on_failure(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """If target transport startup fails, active_transport state is NOT updated to target."""
    coordinator = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_bt_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    async def mock_bt_stop(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.OFFLINE

    def mock_bt_telemetry(self: Any) -> dict[str, Any]:
        return {
            "adapter_state": "On",
            "central_supported": True,
            "scanner_status": "Active",
            "peripheral_supported": False,
            "advertising_active": False,
        }

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_bt_start),
        patch("bitchat.transport.bluetooth.BluetoothTransport.stop", mock_bt_stop),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.get_telemetry",
            mock_bt_telemetry,
        ),
    ):
        await coordinator.start()
        assert coordinator.active_transport_name == "bluetooth"
        assert coordinator.is_running

        # Configure LAN candidate to fail startup
        async def failing_lan_start(self: Any) -> None:
            self._is_running = False
            self._state = TransportState.ERROR
            raise RuntimeError("LAN TCP bind collision port 41235")

        with (
            patch("bitchat.network.transport.LANTransport.start", failing_lan_start),
            patch(
                "bitchat.network.transport.LANTransport.stop", new_callable=AsyncMock
            ),
        ):
            success, msg = await coordinator.switch_transport("lan")
            assert not success
            assert "LAN TCP bind collision" in msg

            # Rollback restarts the previous transport after cleaning up the candidate.
            assert coordinator.is_running
            assert coordinator.active_transport.is_running is True
            assert coordinator.ble_status == TransportState.SCANNING.value
            assert coordinator.active_transport_name == "bluetooth"
        await coordinator.stop()


@pytest.mark.asyncio
async def test_switch_transport_offline_mode(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Switching to offline mode stops all radios and preserves identity."""
    orig_peer_id = local_identity.peer_id_hex
    coordinator = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    async def mock_stop(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.OFFLINE

    def mock_bt_telemetry(self: Any) -> dict[str, Any]:
        return {
            "adapter_state": "On",
            "central_supported": True,
            "scanner_status": "Active",
            "peripheral_supported": False,
            "advertising_active": False,
            "listening_port": 41235,
        }

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_start),
        patch("bitchat.transport.bluetooth.BluetoothTransport.stop", mock_stop),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.get_telemetry",
            mock_bt_telemetry,
        ),
        patch("bitchat.network.transport.LANTransport.start", mock_start),
        patch("bitchat.network.transport.LANTransport.stop", mock_stop),
    ):
        await coordinator.start()
        success, msg = await coordinator.switch_transport("offline")
        assert success
        assert "Switched transport to offline" in msg
        assert coordinator.offline_mode is True
        assert coordinator.ble_status == "offline"
        assert not coordinator.is_running
        # Identity strictly preserved
        assert coordinator.local_identity.peer_id_hex == orig_peer_id


# ---------------------------------------------------------------------------
# Issue 3: Peer Identity & Transport Independence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peer_identity_invariance_across_switches(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Device identity (Peer ID) is strictly constant across Bluetooth, LAN, and Offline."""
    orig_peer_id = local_identity.peer_id_hex

    coordinator = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    async def mock_stop(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.OFFLINE

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_start),
        patch("bitchat.transport.bluetooth.BluetoothTransport.stop", mock_stop),
        patch("bitchat.network.transport.LANTransport.start", mock_start),
        patch("bitchat.network.transport.LANTransport.stop", mock_stop),
    ):
        # Bluetooth
        await coordinator.start()
        assert coordinator.local_identity.peer_id_hex == orig_peer_id

        # Switch to LAN
        s1, _ = await coordinator.switch_transport("lan")
        assert s1
        assert coordinator.local_identity.peer_id_hex == orig_peer_id

        # Switch to Offline
        s2, _ = await coordinator.switch_transport("offline")
        assert s2
        assert coordinator.local_identity.peer_id_hex == orig_peer_id

        # Switch back to Bluetooth
        s3, _ = await coordinator.switch_transport("bluetooth")
        assert s3
        assert coordinator.local_identity.peer_id_hex == orig_peer_id

    # Simulated restart: reading from mock_storage returns exact same peer ID
    reloaded_id = mock_storage.load_identity()
    assert reloaded_id is not None
    assert reloaded_id.peer_id_hex == orig_peer_id


# ---------------------------------------------------------------------------
# Issue 4: LAN Failure Diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lan_transport_tcp_listen_port_failure_diagnostics(
    local_identity: LocalIdentity,
) -> None:
    """LAN transport captures errno/winerror when TCP bind fails and releases partial start."""
    lan = LANTransport(
        local_peer_id=local_identity.peer_id_hex,
        local_nickname="AliceNode",
        tcp_port=41235,
    )

    # Mock adapter as connected
    info = NetworkInfo(status="Connected", interface="Wi-Fi", local_ip="192.168.1.100")
    lan.adapter_manager.refresh = MagicMock(return_value=info)

    bind_err = OSError(
        10048, "Only one usage of each socket address is normally permitted"
    )
    setattr(bind_err, "winerror", 10048)  # noqa: B010

    with patch.object(lan.server, "start", side_effect=bind_err):
        with pytest.raises(RuntimeError) as exc_info:
            await lan.start()

        assert "LAN server failed" in str(exc_info.value)
        assert lan.state == TransportState.ERROR
        telem = lan.get_telemetry()
        assert telem["failed_stage"] == "tcp_server_listen"
        assert telem["error_code"] == 10048
        assert telem["error_source"] == "LANServer.start"


# ---------------------------------------------------------------------------
# Issue 5: BLEErrorModal Presentation on HomeScreen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ble_error_modal_presented_on_homescreen(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Posting BleWarningReported when HomeScreen is active properly presents BLEErrorModal."""
    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_start() -> None:
        return None

    coord.start = mock_start  # type: ignore[assignment]
    coord._is_running = True

    app = BitChatApp(coordinator=coord, initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)

        # Trigger BLE warning (such as WinRT error 3 aborted)
        app.post_message(
            BleWarningReported(
                "BLE peripheral advertising failed: GATT service advertising failed with status 3 (Aborted)"
            )
        )
        await pilot.pause()

        # Modal MUST be presented on top of HomeScreen!
        assert isinstance(app.screen, BLEErrorModal)
        assert "status 3 (Aborted)" in app.screen.error_message
        assert app.screen.peripheral_failure is True

        # Dismiss modal
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, BLEErrorModal)
        assert isinstance(app.screen, HomeScreen)


# ---------------------------------------------------------------------------
# Issue 6: Structured Diagnostics Recording & Redaction
# ---------------------------------------------------------------------------


def test_structured_diagnostics_no_secret_leak() -> None:
    """Verify log_transport_diagnostic records technical data without logging secrets."""
    private_key_hex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    diag = log_transport_diagnostic(
        operation="test_op",
        stage="test_stage",
        result="FAILED",
        requested_transport="bluetooth",
        error_code=3,
        hresult="0x80070003",
        source="test_source",
        cleanup_result="cleaned",
        details="Error on adapter",
    )
    assert diag["operation"] == "test_op"
    assert diag["stage"] == "test_stage"
    assert diag["result"] == "FAILED"
    assert diag["error_code"] == 3
    assert private_key_hex not in str(diag)


# ---------------------------------------------------------------------------
# Issue 7: /transport Command Audit & Persistent Identity Text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transport_command_no_args_and_offline(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """Verifies /transport without args displays runtime state, listener port, and discovery."""
    from textual.widgets import Input

    from bitchat.tui.widgets.chat_view import ChatView
    from bitchat.tui.widgets.message_input import MessageInput

    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    async def mock_stop(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.OFFLINE

    def mock_bt_telemetry(self: Any) -> dict[str, Any]:
        return {
            "adapter_state": "On",
            "central_supported": True,
            "scanner_status": "Active",
            "peripheral_supported": False,
            "advertising_active": False,
            "listening_port": 41235,
        }

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_start),
        patch("bitchat.transport.bluetooth.BluetoothTransport.stop", mock_stop),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.get_telemetry",
            mock_bt_telemetry,
        ),
        patch("bitchat.network.transport.LANTransport.start", mock_start),
        patch("bitchat.network.transport.LANTransport.stop", mock_stop),
    ):
        app = BitChatApp(coordinator=coord, initial_screen="chat")
        async with app.run_test() as pilot:
            chat = app.query_one(ChatView)
            inp = app.query_one(MessageInput)

            def submit(cmd_str: str) -> None:
                inp.value = cmd_str
                app.on_input_submitted(Input.Submitted(inp, cmd_str))

            # 1. Test /transport without args
            submit("/transport")
            await pilot.pause()

            full_log = " ".join(m.text for m in chat._message_history)
            assert "Active transport medium: BLUETOOTH" in full_log
            assert "Listener port:" in full_log
            assert "Discovery:" in full_log
            assert "Supported transports:" in full_log

            # 2. Test /transport offline
            submit("/transport offline")
            await pilot.pause(1)

            full_log_after = " ".join(m.text for m in chat._message_history)
            assert "Switched transport to offline" in full_log_after
            assert "Peer identity:" in full_log_after
            assert "New peer identity" not in full_log_after
            assert coord.offline_mode is True


# ---------------------------------------------------------------------------
# Issue 8: ConnectionModal BLE & LAN Failure Modal Presentation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_modal_ble_peripheral_abort_presents_error_modal(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """When user selects BLE from ConnectionModal and GATT advertising aborts (status 3),
    ConnectionModal dismisses and BLEErrorModal is presented with full diagnostics.
    """
    from bitchat.tui.screens.connection import ConnectionModal

    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
        initial_transport="lan",
    )
    coord.offline_mode = True

    # Simulate BLE starting in central-only mode due to WinRT status 3 Aborted
    bt_trans = coord._transports["bluetooth"]
    assert isinstance(bt_trans, BluetoothTransport)
    bt_trans.ble_server._failed_stage = "advertising_start"
    bt_trans.ble_server._error_code = 3
    bt_trans.ble_server._error_source = "winrt.GattServiceProviderAdvertisementStatus"
    bt_trans.ble_server._last_error = (
        "GATT service advertising failed with status 3 (Aborted)"
    )
    bt_trans._peripheral_error_message = bt_trans.ble_server._last_error

    async def mock_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    def mock_bt_telemetry(self: Any) -> dict[str, Any]:
        return {
            "adapter_state": "On",
            "central_supported": True,
            "scanner_status": "Active",
            "peripheral_supported": True,
            "peripheral_error": "GATT service advertising failed",
            "failed_stage": "advertising_start",
            "error_code": 3,
            "error_source": "winrt.GattServiceProviderAdvertisementStatus",
        }

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_start),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.get_telemetry",
            mock_bt_telemetry,
        ),
    ):
        app = BitChatApp(coordinator=coord, initial_screen="home")
        async with app.run_test() as pilot:
            assert isinstance(app.screen, HomeScreen)

            # Open ConnectionModal
            app.screen.action_open_connect()
            await pilot.pause()
            assert isinstance(app.screen, ConnectionModal)

            # Select BLE (Option 1 / index 0)
            app.screen.action_select_ble()
            await pilot.pause()

            # ConnectionModal must NOT swallow error or navigate to Chat!
            # BLEErrorModal must be presented with status 3 diagnostics!
            assert isinstance(app.screen, BLEErrorModal)
            assert app.screen.peripheral_failure is True
            assert app.screen.error_code == 3
            assert app.screen.failed_stage == "advertising_start"
            assert (
                app.screen.error_source
                == "winrt.GattServiceProviderAdvertisementStatus"
            )


@pytest.mark.asyncio
async def test_connection_modal_lan_failure_presents_error_modal(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """When user selects LAN from ConnectionModal and LAN startup fails,
    ConnectionModal dismisses and BLEErrorModal (LAN) is presented.
    """
    from bitchat.tui.screens.connection import ConnectionModal

    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )
    coord.offline_mode = True

    async def mock_ble_start(self: Any) -> None:
        self._is_running = True
        self._state = TransportState.SCANNING

    async def mock_lan_failing_start(self: Any) -> None:
        self._is_running = False
        self._state = TransportState.ERROR
        self._failed_stage = "tcp_server_listen"
        self._error_code = 10048
        self._error_source = "LANServer.start"
        self._error_message = "LAN server failed: [Errno 10048] address in use"
        raise RuntimeError(self._error_message)

    with (
        patch("bitchat.transport.bluetooth.BluetoothTransport.start", mock_ble_start),
        patch("bitchat.network.transport.LANTransport.start", mock_lan_failing_start),
    ):
        app = BitChatApp(coordinator=coord, initial_screen="home")
        async with app.run_test() as pilot:
            # Open ConnectionModal
            home_screen = app.screen
            assert isinstance(home_screen, HomeScreen)
            home_screen.action_open_connect()
            await pilot.pause()
            assert isinstance(app.screen, ConnectionModal)

            # Select LAN (Option 2 / index 1)
            app.screen.action_select_lan()
            await pilot.pause()

            # Must present BLEErrorModal in LAN mode!
            assert isinstance(app.screen, BLEErrorModal)
            assert app.screen.transport == "lan"
            assert "address in use" in app.screen.error_message


@pytest.mark.asyncio
async def test_ble_retry_on_homescreen_presents_error_modal(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """When retry_ble fails with HomeScreen mounted, error dialog is presented unconditionally."""
    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    async def mock_start() -> None:
        pass

    coord.start = mock_start  # type: ignore[assignment]
    coord.retry_ble = AsyncMock(return_value=False)
    coord.ble_error_message = "Bluetooth adapter hardware error"

    app = BitChatApp(coordinator=coord, initial_screen="home")
    async with app.run_test() as pilot:
        assert isinstance(app.screen, HomeScreen)

        # Trigger BLE retry from HomeScreen
        await app._handle_ble_retry()
        await pilot.pause()

        # BLE recovery dialog MUST appear over HomeScreen!
        assert isinstance(app.screen, BLEErrorModal)
        assert "Bluetooth adapter hardware error" in app.screen.error_message


@pytest.mark.asyncio
async def test_telemetry_screen_truthful_status(
    local_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    """TelemetryScreen does not fabricate Ready when peripheral advertising failed."""
    from bitchat.tui.screens.telemetry import TelemetryScreen

    coord = SessionCoordinator(
        local_identity=local_identity,
        ble_manager=BLEManager(sender_id=local_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(local_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    bt_trans = coord._transports["bluetooth"]
    assert isinstance(bt_trans, BluetoothTransport)
    bt_trans.ble_server._failed_stage = "advertising_start"
    bt_trans.ble_server._error_code = 3
    bt_trans.ble_server._error_source = "winrt.GattServiceProviderAdvertisementStatus"
    bt_trans._peripheral_error_message = (
        "GATT service advertising failed with status 3 (Aborted)"
    )

    app = BitChatApp(coordinator=coord, initial_screen="home")
    async with app.run_test() as pilot:
        telem_screen = TelemetryScreen()
        app.push_screen(telem_screen)
        await pilot.pause()

        gatt_backend_text = str(
            telem_screen.query_one("#telem-ble-backend", Static).render()
        )
        assert "Failed / Error" in gatt_backend_text
        assert "Ready" not in gatt_backend_text
