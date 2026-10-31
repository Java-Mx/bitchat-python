"""Cross-platform BLE lifecycle tests driven through mocked platform APIs.

Windows paths run the real ``BLEServer`` WinRT code against an in-memory fake of
``winrt.*``; Linux paths run with ``sys.platform`` mocked and WinRT imports
forbidden. Nothing here needs Bluetooth hardware or a particular host OS.
"""

from __future__ import annotations

import asyncio
import importlib.abc
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from tests.ble.fake_bluez import FakeBlueZ
from tests.ble.fake_winrt import (
    STATUS_ABORTED,
    STATUS_CREATED,
    STATUS_STARTED,
    FakeWinRT,
)
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend

from bitchat.app import session_coordinator as coordinator_module
from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import BLEError
from bitchat.network.models import NetworkInfo
from bitchat.storage.config import AppConfig, FileConfigStorage
from bitchat.transport.base import TransportState
from bitchat.transport.bluetooth import BluetoothTransport

if TYPE_CHECKING:
    from pathlib import Path


class MutableAdapterBackend:
    """Adapter backend whose reported hardware state tests can change."""

    def __init__(self, info: AdapterInfo) -> None:
        self.info = info
        self.checks = 0

    async def check_adapter(self) -> AdapterInfo:
        self.checks += 1
        return self.info


def hardware(
    *,
    available: bool = True,
    radio: str = "on",
    central: bool = True,
    peripheral: bool = True,
) -> AdapterInfo:
    return AdapterInfo(
        is_available=available,
        radio_state=radio if available else "unavailable",
        is_central_supported=central,
        is_peripheral_supported=peripheral,
        device_id="fake-adapter",
        name="Fake Bluetooth",
    )


def make_manager(
    sender_id: bytes, adapter: MutableAdapterBackend
) -> tuple[BLEManager, BLEAdapterManager]:
    adapter_manager = BLEAdapterManager(custom_backend=adapter)
    manager = BLEManager(
        sender_id=sender_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
        adapter_manager=adapter_manager,
    )
    return manager, adapter_manager


def make_transport(
    adapter: MutableAdapterBackend, server: BLEServer
) -> BluetoothTransport:
    manager, _ = make_manager(b"\x01" * 8, adapter)
    return BluetoothTransport(manager, server)


class _ForbiddenImports(importlib.abc.MetaPathFinder):
    """Meta-path hook that records (and blocks) imports of foreign backends."""

    def __init__(self, *prefixes: str) -> None:
        self.prefixes = prefixes
        self.attempted: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname.split(".")[0] in self.prefixes:
            self.attempted.append(fullname)
            raise ImportError(f"{fullname} is forbidden on this platform in tests")


@pytest.fixture
def forbid_winrt(monkeypatch: pytest.MonkeyPatch) -> _ForbiddenImports:
    for name in [m for m in sys.modules if m.split(".")[0] == "winrt"]:
        monkeypatch.delitem(sys.modules, name)
    finder = _ForbiddenImports("winrt")
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    return finder


@pytest.fixture
def forbid_dbus(monkeypatch: pytest.MonkeyPatch) -> _ForbiddenImports:
    for name in [m for m in sys.modules if m.split(".")[0] == "dbus_fast"]:
        monkeypatch.delitem(sys.modules, name)
    finder = _ForbiddenImports("dbus_fast")
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    return finder


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> FakeWinRT:
    monkeypatch.setattr(sys, "platform", "win32")
    return FakeWinRT().install(monkeypatch)


@pytest.fixture
def bluez(monkeypatch: pytest.MonkeyPatch) -> FakeBlueZ:
    monkeypatch.setattr(sys, "platform", "linux")
    return FakeBlueZ().install(monkeypatch)


# ---------------------------------------------------------------------------
# Windows: BLEServer (real WinRT control flow against the fake)
# ---------------------------------------------------------------------------


async def test_windows_server_starts_advertising_and_registers_handlers(
    windows: FakeWinRT,
) -> None:
    server = BLEServer()
    assert server.supports_peripheral is True

    await server.start()

    assert server.is_advertising is True
    assert windows.advertising_providers == 1
    assert windows.running_publishers == 1
    assert windows.active_handlers == 2
    assert server.get_telemetry()["last_error"] is None

    await server.stop()

    assert server.is_advertising is False
    assert windows.advertising_providers == 0
    assert windows.running_publishers == 0
    assert windows.active_handlers == 0
    assert server.get_telemetry()["has_provider"] is False


async def test_windows_server_repeated_cycles_do_not_leak_handlers_or_publishers(
    windows: FakeWinRT,
) -> None:
    server = BLEServer()
    for _ in range(3):
        await server.start()
        assert windows.active_handlers == 2
        await server.stop()
        assert windows.active_handlers == 0
        assert windows.advertising_providers == 0
        assert windows.running_publishers == 0

    # Stopping again is a harmless no-op.
    await server.stop()
    assert len(windows.providers) == 3


async def test_windows_gatt_abort_then_recovery(windows: FakeWinRT) -> None:
    windows.provider_status = STATUS_ABORTED
    server = BLEServer()

    await server.start()

    assert server.is_advertising is False
    assert "Aborted" in (server.get_telemetry()["last_error"] or "")
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0

    windows.provider_status = STATUS_STARTED
    await server.start()

    assert server.is_advertising is True
    assert server.get_telemetry()["last_error"] is None
    assert windows.active_handlers == 2

    await server.stop()
    assert windows.active_handlers == 0


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("create_error", 5, "GattServiceProvider"),
        ("characteristic_error", 7, "GattLocalCharacteristic"),
    ],
)
async def test_windows_backend_initialization_failure_cleans_up(
    windows: FakeWinRT, attribute: str, value: int, message: str
) -> None:
    setattr(windows, attribute, value)
    server = BLEServer()

    with pytest.raises(BLEError, match=message):
        await server.start()

    assert server.is_advertising is False
    assert message in (server.get_telemetry()["last_error"] or "")
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0

    # Shutdown after partial initialization must not raise and stays clean.
    await server.stop()
    await server.stop()
    assert server.get_telemetry()["has_provider"] is False


async def test_windows_publisher_failure_releases_provider_and_handlers(
    windows: FakeWinRT,
) -> None:
    windows.publisher_status = STATUS_ABORTED
    server = BLEServer()

    with pytest.raises(BLEError, match="discovery advertisement failed"):
        await server.start()

    assert server.is_advertising is False
    assert windows.advertising_providers == 0
    assert windows.running_publishers == 0
    assert windows.active_handlers == 0


async def test_windows_cancelled_start_releases_resources(
    windows: FakeWinRT,
) -> None:
    windows.provider_status = STATUS_CREATED  # never reaches a terminal state
    server = BLEServer()

    task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert server.is_advertising is False
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0


async def test_windows_notify_uses_characteristic(windows: FakeWinRT) -> None:
    server = BLEServer()
    await server.start()

    await server.send_notification(b"payload")

    assert len(windows.characteristics[0].notifications) == 1
    await server.stop()


# ---------------------------------------------------------------------------
# Linux: BlueZ GATT server and LE advertising, never touches WinRT
# ---------------------------------------------------------------------------


async def test_linux_server_starts_advertising_and_never_imports_winrt(
    bluez: FakeBlueZ, forbid_winrt: _ForbiddenImports
) -> None:
    server = BLEServer()
    assert server.supports_peripheral is True

    await server.start()

    assert server.is_advertising is True
    assert len(bluez.registered_applications) == 1
    assert len(bluez.registered_advertisements) == 1
    assert server.get_telemetry()["last_error"] is None
    assert forbid_winrt.attempted == []

    await server.stop()
    await server.stop()
    assert server.is_advertising is False
    assert len(bluez.registered_applications) == 0
    assert len(bluez.registered_advertisements) == 0
    assert forbid_winrt.attempted == []


async def test_linux_server_repeated_cycles_do_not_leak_registrations(
    bluez: FakeBlueZ,
) -> None:
    server = BLEServer()
    for _ in range(3):
        await server.start()
        assert server.is_advertising is True
        assert len(bluez.registered_applications) == 1
        assert len(bluez.registered_advertisements) == 1
        await server.stop()
        assert server.is_advertising is False
        assert len(bluez.registered_applications) == 0
        assert len(bluez.registered_advertisements) == 0


async def test_linux_notify_uses_characteristic(bluez: FakeBlueZ) -> None:
    server = BLEServer()
    await server.start()

    await server.send_notification(b"payload")

    assert len(bluez.emitted_notifications) == 1
    assert bluez.emitted_notifications[0]["Value"] == b"payload"
    await server.stop()


# ---------------------------------------------------------------------------
# Unsupported platform (e.g. Darwin): central-only, never touches WinRT
# ---------------------------------------------------------------------------


async def test_darwin_server_is_central_only_and_never_imports_winrt(
    monkeypatch: pytest.MonkeyPatch, forbid_winrt: _ForbiddenImports
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    server = BLEServer()
    assert server.supports_peripheral is False

    await server.start()

    assert server.is_advertising is False
    assert server.get_telemetry()["last_error"] is None
    with pytest.raises(BLEError, match="not active"):
        await server.send_notification(b"x")

    await server.stop()
    await server.stop()
    assert forbid_winrt.attempted == []


async def test_windows_server_never_imports_dbus(
    windows: FakeWinRT, forbid_dbus: _ForbiddenImports
) -> None:
    server = BLEServer()
    await server.start()
    await server.stop()
    assert forbid_dbus.attempted == []


# ---------------------------------------------------------------------------
# BluetoothTransport on each platform
# ---------------------------------------------------------------------------


async def test_windows_transport_advertises_and_scans(windows: FakeWinRT) -> None:
    transport = make_transport(MutableAdapterBackend(hardware()), BLEServer())

    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["advertising_active"] is True
    assert telemetry["gatt_server_status"] == "Advertising"
    assert telemetry["peripheral_error"] is None

    await transport.stop()
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0


async def test_windows_advertising_failure_keeps_central_and_recovers_on_retry(
    windows: FakeWinRT,
) -> None:
    windows.provider_status = STATUS_ABORTED
    transport = make_transport(MutableAdapterBackend(hardware()), BLEServer())
    warnings: list[str] = []
    transport.on_warning = warnings.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Failed"
    assert "Aborted" in (telemetry["peripheral_error"] or "")
    assert len(warnings) == 1
    assert windows.advertising_providers == 0

    windows.provider_status = STATUS_STARTED
    await transport.stop()
    assert windows.advertising_providers == 0
    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["advertising_active"] is True
    assert telemetry["peripheral_error"] is None
    assert len(warnings) == 1  # no new warning on the successful retry
    await transport.stop()


async def test_linux_transport_advertises_and_scans(bluez: FakeBlueZ) -> None:
    transport = make_transport(MutableAdapterBackend(hardware()), BLEServer())

    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["advertising_active"] is True
    assert telemetry["gatt_server_status"] == "Advertising"
    assert telemetry["peripheral_error"] is None

    await transport.stop()
    assert len(bluez.registered_applications) == 0
    assert len(bluez.registered_advertisements) == 0


async def test_linux_advertising_failure_keeps_central_and_recovers_on_retry(
    bluez: FakeBlueZ,
) -> None:
    bluez.register_adv_error = "org.bluez.Error.Failed"
    transport = make_transport(MutableAdapterBackend(hardware()), BLEServer())
    warnings: list[str] = []
    transport.on_warning = warnings.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Failed"
    assert "Failed" in (telemetry["peripheral_error"] or "")
    assert len(warnings) == 1
    assert len(bluez.registered_advertisements) == 0

    bluez.register_adv_error = None
    await transport.stop()
    assert len(bluez.registered_advertisements) == 0
    await transport.start()

    telemetry = transport.get_telemetry()
    assert telemetry["advertising_active"] is True
    assert telemetry["peripheral_error"] is None
    assert len(warnings) == 1
    await transport.stop()


async def test_darwin_transport_runs_central_only_without_warning(
    monkeypatch: pytest.MonkeyPatch, forbid_winrt: _ForbiddenImports
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    # The adapter hardware claims peripheral support, but BitChat has no Darwin
    # GATT server, so the transport must report central-only truthfully.
    transport = make_transport(MutableAdapterBackend(hardware()), BLEServer())
    warnings: list[str] = []
    transport.on_warning = warnings.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert transport.state == TransportState.SCANNING
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["peripheral_supported"] is False
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Unsupported"
    assert telemetry["peripheral_error"] is None
    assert warnings == []
    assert forbid_winrt.attempted == []

    await transport.stop()


async def test_linux_transport_hardware_unsupported_peripheral(
    bluez: FakeBlueZ,
) -> None:
    transport = make_transport(
        MutableAdapterBackend(hardware(peripheral=False)), BLEServer()
    )
    warnings: list[str] = []
    transport.on_warning = warnings.append

    await transport.start()

    telemetry = transport.get_telemetry()
    assert transport.state == TransportState.SCANNING
    assert telemetry["scanner_status"] == "Active"
    assert telemetry["peripheral_supported"] is False
    assert telemetry["advertising_active"] is False
    assert telemetry["gatt_server_status"] == "Unsupported"
    assert telemetry["peripheral_error"] is not None
    assert len(warnings) == 1
    await transport.stop()


async def test_linux_adapter_unavailable_does_not_start_any_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    transport = make_transport(
        MutableAdapterBackend(hardware(available=False)), BLEServer()
    )

    with pytest.raises(RuntimeError, match="Bluetooth unavailable"):
        await transport.start()

    assert transport.state == TransportState.UNAVAILABLE
    assert transport.is_scanning is False
    assert transport.get_telemetry()["gatt_server_status"] != "Advertising"
    await transport.stop()


@pytest.mark.parametrize("platform_id", ["win32", "linux"])
async def test_repeated_transport_cycles_do_not_leak_tasks_or_handlers(
    monkeypatch: pytest.MonkeyPatch, platform_id: str
) -> None:
    fake_win = FakeWinRT().install(monkeypatch)
    fake_bluez = FakeBlueZ().install(monkeypatch)
    monkeypatch.setattr(sys, "platform", platform_id)
    adapter = MutableAdapterBackend(hardware())
    transport = make_transport(adapter, BLEServer())
    manager = transport.ble_manager

    baseline = len(asyncio.all_tasks())
    for _ in range(3):
        await transport.start()
        await transport.stop()
        assert manager.adapter_manager._monitor_task is None
        assert len(asyncio.all_tasks()) == baseline
        assert fake_win.active_handlers == 0
        assert fake_win.advertising_providers == 0
        assert fake_win.running_publishers == 0
        assert len(fake_bluez.registered_applications) == 0
        assert len(fake_bluez.registered_advertisements) == 0
        assert not manager.scanner.is_scanning


# ---------------------------------------------------------------------------
# Recovery flow through SessionCoordinator: retry, LAN fallback, offline
# ---------------------------------------------------------------------------


@pytest.fixture
def storage(tmp_path: Path) -> FileConfigStorage:
    store = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    store.save_config(AppConfig(nickname="Alice", transport="bluetooth"))
    return store


@pytest.fixture
def identity(storage: FileConfigStorage) -> LocalIdentity:
    persisted = LocalIdentity.generate()
    storage.save_identity(persisted)
    return persisted


def make_coordinator(
    identity: LocalIdentity,
    storage: FileConfigStorage,
    adapter: MutableAdapterBackend,
    server: BLEServer | None = None,
) -> SessionCoordinator:
    manager, _ = make_manager(identity.peer_id, adapter)
    return SessionCoordinator(
        local_identity=identity,
        ble_manager=manager,
        ble_server=server or BLEServer(backend=MockBLEServerBackend()),
        storage=storage,
        nickname="Alice",
    )


WIFI = NetworkInfo(
    status="Connected", interface="Wi-Fi", ssid="TestLAN", local_ip="192.168.1.50"
)
NO_NETWORK = NetworkInfo(
    status="Disconnected", interface="Unavailable", ssid="", local_ip=""
)


async def test_retry_fails_without_hardware_then_succeeds_and_cleans_up(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware(available=False))
    coordinator = make_coordinator(identity, storage, adapter)
    errors: list[str] = []
    coordinator.on_ble_error = errors.append
    manager = coordinator.ble_manager

    await coordinator.start()
    assert coordinator.is_running is False
    assert errors == ["Bluetooth unavailable"]

    # Still no hardware: a real retry runs, fails, and leaves nothing running.
    assert await coordinator.retry_active_transport() is False
    assert coordinator.ble_error_message == "Bluetooth unavailable"
    assert coordinator.is_running is False
    assert manager.adapter_manager._monitor_task is None
    assert not manager.scanner.is_scanning
    assert adapter.checks >= 2

    adapter.info = hardware()
    assert await coordinator.retry_active_transport() is True
    assert coordinator.is_running is True
    assert manager.scanner.is_scanning

    await coordinator.stop()
    assert manager.adapter_manager._monitor_task is None
    assert not manager.scanner.is_scanning


async def test_retry_is_bounded_and_releases_resources_on_hang(
    monkeypatch: pytest.MonkeyPatch,
    identity: LocalIdentity,
    storage: FileConfigStorage,
) -> None:
    monkeypatch.setattr(coordinator_module, "TRANSPORT_RETRY_TIMEOUT_SECONDS", 0.2)

    class HangingBackend(MockBLEServerBackend):
        async def start(self, server: Any) -> None:
            await asyncio.Event().wait()

    adapter = MutableAdapterBackend(hardware())
    coordinator = make_coordinator(
        identity, storage, adapter, BLEServer(backend=HangingBackend())
    )

    assert await coordinator.retry_active_transport() is False

    assert "timed out" in (coordinator.ble_error_message or "")
    assert coordinator.active_transport.is_running is False
    assert coordinator.active_transport.state == TransportState.UNAVAILABLE
    assert coordinator.ble_manager.adapter_manager._monitor_task is None


async def test_gatt_failure_retry_recovers_with_real_windows_server(
    windows: FakeWinRT,
    identity: LocalIdentity,
    storage: FileConfigStorage,
) -> None:
    windows.create_error = 3
    adapter = MutableAdapterBackend(hardware())
    coordinator = make_coordinator(identity, storage, adapter, BLEServer())
    warnings: list[str] = []
    coordinator.on_ble_warning = warnings.append

    await coordinator.start()
    # Central scanning still works; the peripheral failure is surfaced as a warning.
    assert coordinator.is_running is True
    assert len(warnings) == 1
    assert windows.advertising_providers == 0

    windows.create_error = 0
    assert await coordinator.retry_active_transport() is True
    telemetry = coordinator.active_transport.get_telemetry()
    assert telemetry["advertising_active"] is True
    assert telemetry["peripheral_error"] is None
    assert windows.advertising_providers == 1

    await coordinator.stop()
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0


async def test_lan_fallback_is_verified_and_preserves_persisted_identity(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware(available=False))
    coordinator = make_coordinator(identity, storage, adapter)
    await coordinator.start()
    assert coordinator.is_running is False

    with patch("bitchat.network.adapter.detect_network_info", return_value=WIFI):
        ok, _ = await coordinator.switch_transport("lan")

        assert ok is True
        lan: Any = coordinator.active_transport
        assert coordinator.active_transport_name == "lan"
        assert lan.is_running is True
        assert lan.discovery.is_running is True
        assert lan.server.is_listening is True
        assert coordinator.is_running is True

        stored = storage.load_identity()
        assert stored is not None
        assert stored.peer_id_hex == identity.peer_id_hex
        assert coordinator.local_identity.peer_id_hex == identity.peer_id_hex

        await coordinator.stop()
        assert lan.server.is_listening is False
        assert lan.discovery.is_running is False


async def test_lan_fallback_failure_is_reported_and_releases_sockets(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware(available=False))
    coordinator = make_coordinator(identity, storage, adapter)
    await coordinator.start()

    with patch("bitchat.network.adapter.detect_network_info", return_value=NO_NETWORK):
        ok, message = await coordinator.switch_transport("lan")

    lan: Any = coordinator.active_transport
    assert ok is False
    assert "Failed starting lan transport" in message
    assert coordinator.is_running is False
    assert lan.is_running is False
    assert lan.server.is_listening is False
    assert lan.discovery.is_running is False
    assert coordinator.ble_status != "ready"
    stored = storage.load_identity()
    assert stored is not None
    assert stored.peer_id_hex == identity.peer_id_hex


async def test_offline_mode_stops_everything_and_blocks_ble_restart(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware())
    coordinator = make_coordinator(identity, storage, adapter)
    await coordinator.start()
    assert coordinator.is_running is True
    manager = coordinator.ble_manager

    await coordinator.go_offline()
    assert coordinator.offline_mode is True
    assert coordinator.is_running is False
    assert coordinator.ble_status == "offline"
    assert not manager.scanner.is_scanning
    assert manager.adapter_manager._monitor_task is None

    # A stray start() must not silently bring Bluetooth back up.
    checks_before = adapter.checks
    await coordinator.start()
    assert coordinator.is_running is False
    assert adapter.checks == checks_before

    # Going offline twice is harmless, and the identity is untouched.
    await coordinator.go_offline()
    stored = storage.load_identity()
    assert stored is not None
    assert stored.peer_id_hex == identity.peer_id_hex


async def test_repeated_transport_switching_does_not_leak_tasks_or_listeners(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware())
    coordinator = make_coordinator(identity, storage, adapter)

    with patch("bitchat.network.adapter.detect_network_info", return_value=WIFI):
        await coordinator.start()
        lan: Any = coordinator._transports["lan"]

        counts: list[int] = []
        for _ in range(3):
            assert (await coordinator.switch_transport("lan"))[0] is True
            assert lan.discovery.is_running
            assert lan.server.is_listening
            assert (await coordinator.switch_transport("bluetooth"))[0] is True
            assert not lan.discovery.is_running
            assert not lan.server.is_listening
            assert lan.adapter_manager._monitor_task is None
            counts.append(len(asyncio.all_tasks()))

        assert counts[0] == counts[1] == counts[2]
        assert len(lan.discovery._discovered_peers) == 0
        await coordinator.stop()


async def test_partial_ble_startup_failure_and_cancellation_do_not_leak_monitor(
    windows: FakeWinRT,
    identity: LocalIdentity,
    storage: FileConfigStorage,
) -> None:
    # 1. Radio off at coordinator.start() must not leave _monitor_task running
    adapter = MutableAdapterBackend(hardware(radio="off"))
    coordinator = make_coordinator(identity, storage, adapter, BLEServer())
    manager = coordinator.ble_manager

    await coordinator.start()
    assert coordinator.is_running is False
    assert coordinator.ble_status == "disabled"
    assert manager.adapter_manager._monitor_task is None

    # 2. Scan failure after server start must stop server and adapter monitor
    adapter.info = hardware(radio="on")

    async def fail_scan() -> None:
        raise RuntimeError("BlueZ scan failed")

    with patch.object(manager, "start_discovery", side_effect=fail_scan):
        await coordinator.start()

    assert coordinator.is_running is False
    assert coordinator.ble_status == "error"
    assert manager.adapter_manager._monitor_task is None
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0

    # 3. Cancelled transport.start() mid-flight cleans up monitor and server
    windows.provider_status = STATUS_CREATED
    transport = coordinator.active_transport
    task = asyncio.create_task(transport.start())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.is_running is False
    assert manager.adapter_manager._monitor_task is None
    assert windows.advertising_providers == 0
    assert windows.active_handlers == 0


async def test_concurrent_retry_switch_and_offline_are_serialized_safely(
    identity: LocalIdentity, storage: FileConfigStorage
) -> None:
    adapter = MutableAdapterBackend(hardware())
    coordinator = make_coordinator(identity, storage, adapter)

    with patch("bitchat.network.adapter.detect_network_info", return_value=WIFI):
        await coordinator.start()
        await asyncio.gather(
            coordinator.retry_active_transport(),
            coordinator.switch_transport("lan"),
            coordinator.go_offline(),
        )
        # Regardless of scheduling order, the final state must be internally consistent
        # with no orphaned monitor tasks on inactive transports.
        bt: Any = coordinator._transports["bluetooth"]
        lan: Any = coordinator._transports["lan"]
        if coordinator.offline_mode:
            assert coordinator.is_running is False
            assert bt.is_running is False
            assert lan.is_running is False
            assert coordinator.ble_manager.adapter_manager._monitor_task is None
            assert lan.adapter_manager._monitor_task is None
        await coordinator.stop()
