'''Tests that BLEServer.start() gracefully handles a GATT advertising abort (status 3).'''

import sys
import types
import pytest
import logging
from bitchat.ble.server import BLEServer, BLEError

@pytest.mark.asyncio
async def test_server_start_handles_gatt_abort(monkeypatch):
    """Run BLEServer._start_windows_server with dummy WinRT modules and force an abort.
    The test verifies that BLEServer.start() does not raise and leaves advertising off.
    """
    # ---------------------------------------------------------------------
    # Create minimal dummy winrt modules that satisfy the imports in BLEServer._start_windows_server
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
    # succeed.
    winrt_pkg = types.ModuleType('winrt')
    windows_pkg = types.ModuleType('winrt.windows')
    devices_pkg = types.ModuleType('winrt.windows.devices')
    bluetooth_pkg = types.ModuleType('winrt.windows.devices.bluetooth')
    storage_pkg = types.ModuleType('winrt.windows.storage')

    # Assign submodules as attributes
    winrt_pkg.windows = windows_pkg
    windows_pkg.devices = devices_pkg
    devices_pkg.bluetooth = bluetooth_pkg
    windows_pkg.storage = storage_pkg

    # Set leaf modules
    bluetooth_pkg.advertisement = DummyAdv
    bluetooth_pkg.genericattributeprofile = DummyGatt
    storage_pkg.streams = DummyStreams

    # Register the hierarchy in sys.modules using monkeypatch so they are restored after the test
    monkeypatch.setitem(sys.modules, 'winrt', winrt_pkg)
    monkeypatch.setitem(sys.modules, 'winrt.windows', windows_pkg)
    monkeypatch.setitem(sys.modules, 'winrt.windows.devices', devices_pkg)
    monkeypatch.setitem(sys.modules, 'winrt.windows.devices.bluetooth', bluetooth_pkg)
    monkeypatch.setitem(sys.modules, 'winrt.windows.devices.bluetooth.advertisement', DummyAdv)
    monkeypatch.setitem(sys.modules, 'winrt.windows.devices.bluetooth.genericattributeprofile', DummyGatt)
    monkeypatch.setitem(sys.modules, 'winrt.windows.storage', storage_pkg)
    monkeypatch.setitem(sys.modules, 'winrt.windows.storage.streams', DummyStreams)

    server = BLEServer()
    assert not server.is_advertising

    # Force the GATT wait to raise the BLEError that signals an aborted advertisement
    async def raise_abort(_):
        raise BLEError('simulated GATT abort')
    monkeypatch.setattr(BLEServer, '_wait_for_gatt_advertisement_status', staticmethod(raise_abort), raising=False)

    # Ensure cleanup does not raise on dummy objects
    monkeypatch.setattr(BLEServer, '_cleanup_windows_resources', lambda self: None, raising=False)

    # Run start() – it should complete without propagating the BLEError and leave advertising off
    await server.start()
    assert server.is_advertising is False
