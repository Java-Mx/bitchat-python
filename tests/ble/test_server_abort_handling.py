"""Tests that BLEServer.start() handles a GATT advertising abort (status 3)."""

import sys
import types
from typing import Any

import pytest

from bitchat.ble.server import BLEError, BLEServer


@pytest.mark.asyncio
async def test_server_start_handles_gatt_abort(monkeypatch):
    """Run BLEServer._start_windows_server with dummy WinRT modules and force an abort.
    The test verifies that BLEServer.start() does not raise and leaves advertising off.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    # ---------------------------------------------------------------------
    # Create minimal dummy winrt modules that satisfy the imports in
    # BLEServer._start_windows_server
    # ---------------------------------------------------------------------
    class DummyCharacteristic:
        def add_write_requested(self, cb):
            pass

        def add_subscribed_clients_changed(self, cb):
            pass

    class DummyService:
        async def create_characteristic_async(self, uuid, params):
            return types.SimpleNamespace(error=0, characteristic=DummyCharacteristic())

    class DummyProvider:
        def __init__(self):
            self.service = DummyService()

        def start_advertising_with_parameters(self, params):
            pass

        def stop_advertising(self):
            pass

    class DummyGatt:
        class GattServiceProvider:
            @staticmethod
            async def create_async(srv_uuid):
                return types.SimpleNamespace(error=0, service_provider=DummyProvider())

        class GattServiceProviderAdvertisingParameters:
            pass

        class GattLocalCharacteristicParameters:
            pass

        class GattCharacteristicProperties:
            WRITE_WITHOUT_RESPONSE = 0
            WRITE = 0
            NOTIFY = 0

    class DummyAdv:
        class BluetoothLEAdvertisementPublisher:
            def __init__(self):
                self.advertisement = types.SimpleNamespace(manufacturer_data=[])

            def start(self):
                pass

            def stop(self):
                pass

        class BluetoothLEManufacturerData:
            def __init__(self):
                self.company_id = None
                self.data = None

    class DummyStreams:
        class DataWriter:
            def write_bytes(self, b):
                pass

            def detach_buffer(self):
                return None

    # Build a dummy winrt package hierarchy so that imports like
    #   import winrt.windows.devices.bluetooth.advertisement as adv
    # succeed. The modules are annotated as Any because the fake hierarchy is
    # assembled dynamically via attribute assignment.
    winrt_pkg: Any = types.ModuleType("winrt")
    windows_pkg: Any = types.ModuleType("winrt.windows")
    devices_pkg: Any = types.ModuleType("winrt.windows.devices")
    bluetooth_pkg: Any = types.ModuleType("winrt.windows.devices.bluetooth")
    storage_pkg: Any = types.ModuleType("winrt.windows.storage")

    # Assign submodules as attributes
    winrt_pkg.windows = windows_pkg
    windows_pkg.devices = devices_pkg
    devices_pkg.bluetooth = bluetooth_pkg
    windows_pkg.storage = storage_pkg

    # Set leaf modules
    bluetooth_pkg.advertisement = DummyAdv
    bluetooth_pkg.genericattributeprofile = DummyGatt
    storage_pkg.streams = DummyStreams

    # Register the hierarchy in sys.modules using monkeypatch so they are
    # restored after the test
    bt_name = "winrt.windows.devices.bluetooth"
    monkeypatch.setitem(sys.modules, "winrt", winrt_pkg)
    monkeypatch.setitem(sys.modules, "winrt.windows", windows_pkg)
    monkeypatch.setitem(sys.modules, "winrt.windows.devices", devices_pkg)
    monkeypatch.setitem(sys.modules, bt_name, bluetooth_pkg)
    monkeypatch.setitem(sys.modules, f"{bt_name}.advertisement", DummyAdv)
    monkeypatch.setitem(sys.modules, f"{bt_name}.genericattributeprofile", DummyGatt)
    monkeypatch.setitem(sys.modules, "winrt.windows.storage", storage_pkg)
    monkeypatch.setitem(sys.modules, "winrt.windows.storage.streams", DummyStreams)

    server = BLEServer()
    assert not server.is_advertising

    # Force the GATT wait to raise the BLEError that signals an aborted advertisement
    async def raise_abort(_):
        raise BLEError("simulated GATT abort")

    monkeypatch.setattr(
        BLEServer,
        "_wait_for_gatt_advertisement_status",
        staticmethod(raise_abort),
        raising=False,
    )

    # Ensure cleanup does not raise on dummy objects
    monkeypatch.setattr(
        BLEServer, "_cleanup_windows_resources", lambda self: None, raising=False
    )

    # Run start() - it should complete without propagating the BLEError and leave
    # advertising off
    await server.start()
    assert server.is_advertising is False


@pytest.mark.asyncio
async def test_server_stop_cleans_up_partial_winrt_resources_when_not_advertising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BLEServer.stop() releases partial WinRT handles when _is_advertising is False."""
    monkeypatch.setattr(sys, "platform", "win32")
    server = BLEServer()
    provider_stopped = False
    publisher_stopped = False

    class PartialProvider:
        def stop_advertising(self) -> None:
            nonlocal provider_stopped
            provider_stopped = True

    class PartialPublisher:
        def stop(self) -> None:
            nonlocal publisher_stopped
            publisher_stopped = True

    server._provider = PartialProvider()
    server._publisher = PartialPublisher()
    server._characteristic = object()
    server._is_advertising = False

    await server.stop()

    assert provider_stopped is True
    assert publisher_stopped is True
    assert server._provider is None
    assert server._publisher is None
    assert server._characteristic is None
