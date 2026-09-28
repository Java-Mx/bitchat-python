"""
BLE GATT Peripheral Diagnostic Script
======================================
Runs progressive tests to pinpoint why GattServiceProvider returns status 3.

Usage:
    uv run python tools/diag_ble_gatt.py

Tests (in order):
  1. Adapter info -- capabilities reported by WinRT
  2. Minimal GATT service (no characteristics, no publisher)
  3. Minimal GATT + one characteristic (notify-only)
  4. BitChat characteristic properties (write + write-without-response + notify)
  5. is_connectable=False, is_discoverable=True (connectable=False variant)
  6. Full BitChat service UUID + characteristic
  7. GATT + companion BluetoothLEAdvertisementPublisher (BitChat full)
  8. Publisher alone (no GATT)
  9. Exact BitChat server.py _start_windows_server() reproduction
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import uuid
from typing import Any

# Force UTF-8 so check/cross marks survive Windows cp1252 console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

if sys.platform != "win32":
    print("ERROR: This script requires Windows WinRT.")
    sys.exit(1)

BITCHAT_SERVICE_UUID = "F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"
BITCHAT_CHAR_UUID = "A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"
MINIMAL_SERVICE_UUID = "12345678-0000-1000-8000-00805F9B34FB"
MINIMAL_CHAR_UUID = "12345678-0001-1000-8000-00805F9B34FB"

POLL_INTERVAL = 0.05
POLL_TIMEOUT = 6.0

# GattServiceProviderAdvertisementStatus values (confirmed via WinRT enum inspection)
# 0 = Created
# 1 = Stopped
# 2 = Started                           <- full success
# 3 = Aborted                           <- failure
# 4 = StartedWithoutAllAdvertisementData <- partial success (not a failure!)
GATT_STATUS_NAMES = {
    0: "Created",
    1: "Stopped",
    2: "Started",
    3: "Aborted",
    4: "StartedWithoutAllAdvertisementData",
}
# BluetoothLEAdvertisementPublisherStatus values
# 0 = Created
# 1 = Waiting
# 2 = Started
# 3 = Stopping
# 4 = Stopped
# 5 = Aborted
ADV_STATUS_NAMES = {
    0: "Created",
    1: "Waiting",
    2: "Started",
    3: "Stopping",
    4: "Stopped",
    5: "Aborted",
}

SEP = "-" * 72


def header(msg: str) -> None:
    print(f"\n{SEP}\n{msg}\n{SEP}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"  [..]   {msg}")


async def poll_gatt_status(provider: object, timeout: float = POLL_TIMEOUT) -> int:
    """Poll GattServiceProvider.advertisement_status until terminal state.

    Terminal states: Started(2), Aborted(3), StartedWithoutAllAdvertisementData(4)
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        status = int(getattr(provider, "advertisement_status", 0))
        if status in (2, 3, 4):  # Started=2, Aborted=3, StartedWithoutAllAdData=4
            return status
        await asyncio.sleep(POLL_INTERVAL)
    return int(getattr(provider, "advertisement_status", -1))


async def poll_publisher_status(publisher: object, timeout: float = POLL_TIMEOUT) -> int:
    """Poll BluetoothLEAdvertisementPublisher.status until terminal state."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        status = int(getattr(publisher, "status", 0))
        if status in (2, 3, 4, 5):  # Started=2, Stopped=3, Aborted=4, Error=5
            return status
        await asyncio.sleep(POLL_INTERVAL)
    return int(getattr(publisher, "status", -1))


def stop_provider(provider: Any) -> None:
    if provider is not None:
        with contextlib.suppress(Exception):
            provider.stop_advertising()


def stop_publisher(pub: Any) -> None:
    if pub is not None:
        with contextlib.suppress(Exception):
            pub.stop()


# ------------------------------------------------------------------------------
# PHASE 1: Adapter Info
# ------------------------------------------------------------------------------

async def test_adapter_info() -> dict:
    header("PHASE 1 -- Adapter Information")
    try:
        from winrt.windows.devices.bluetooth import BluetoothAdapter
        from winrt.windows.devices.radios import RadioState

        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            fail("No Bluetooth adapter found")
            return {}

        radio = None
        with contextlib.suppress(Exception):
            radio = await adapter.get_radio_async()

        state_map = {
            RadioState.ON: "ON",
            RadioState.OFF: "OFF",
            RadioState.DISABLED: "DISABLED",
            RadioState.UNKNOWN: "UNKNOWN",
        }
        radio_state = (
            state_map.get(radio.state, f"UNKNOWN({radio.state})") if radio else "N/A"
        )
        radio_name = getattr(radio, "name", "N/A") if radio else "N/A"

        is_peripheral = bool(getattr(adapter, "is_peripheral_role_supported", False))
        is_central = bool(getattr(adapter, "is_central_role_supported", False))
        is_adv_offload = bool(
            getattr(adapter, "is_advertisement_offload_supported", False)
        )
        device_id = str(getattr(adapter, "device_id", "N/A"))

        info(f"Adapter name          : {radio_name}")
        info(f"Device ID             : {device_id}")
        info(f"Radio state           : {radio_state}")
        info(f"Central role          : {is_central}")
        info(f"Peripheral role       : {is_peripheral}")
        info(f"Adv offload supported : {is_adv_offload}")

        if not is_peripheral:
            fail("Adapter reports peripheral role NOT supported -- GATT server cannot work")
        else:
            ok("Adapter reports peripheral role supported")

        return {
            "is_peripheral": is_peripheral,
            "is_central": is_central,
            "is_adv_offload": is_adv_offload,
            "radio_state": radio_state,
            "radio_name": radio_name,
            "device_id": device_id,
        }
    except Exception as e:
        fail(f"Adapter info failed: {e}")
        return {}


# ------------------------------------------------------------------------------
# PHASE 2: Minimal GATT service -- no characteristics, no publisher
# ------------------------------------------------------------------------------

async def test_minimal_gatt_no_char() -> bool:
    header("PHASE 2 -- Minimal GATT Service (no characteristics, no publisher)")
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt

    provider = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(MINIMAL_SERVICE_UUID))
        error_code = int(res.error)
        provider = res.service_provider

        if error_code != 0 or provider is None:
            fail(f"GattServiceProvider.create_async error={error_code}")
            return False

        ok(f"GattServiceProvider created (error={error_code})")

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        status = await poll_gatt_status(provider)
        name = GATT_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"advertisement_status = {status} ({name})")
            return True
        else:
            fail(f"advertisement_status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 3: Minimal GATT + notify-only characteristic
# ------------------------------------------------------------------------------

async def test_minimal_gatt_notify_char() -> bool:
    header("PHASE 3 -- Minimal GATT + Notify-Only Characteristic")
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt

    provider = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(MINIMAL_SERVICE_UUID))
        error_code = int(res.error)
        provider = res.service_provider
        if error_code != 0 or provider is None:
            fail(f"create_async error={error_code}")
            return False

        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = gatt.GattCharacteristicProperties.NOTIFY
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(MINIMAL_CHAR_UUID), char_params
        )
        c_err = int(c_res.error)
        if c_err != 0 or c_res.characteristic is None:
            fail(f"Characteristic creation error={c_err}")
            return False
        ok(f"Characteristic created (notify-only, error={c_err})")

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        status = await poll_gatt_status(provider)
        name = GATT_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"advertisement_status = {status} ({name})")
            return True
        else:
            fail(f"advertisement_status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 4: BitChat characteristic properties
# ------------------------------------------------------------------------------

async def test_bitchat_char_properties() -> bool:
    header(
        "PHASE 4 -- BitChat Characteristic Properties "
        "(Write + WriteWithoutResponse + Notify)"
    )
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt

    provider = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(MINIMAL_SERVICE_UUID))
        error_code = int(res.error)
        provider = res.service_provider
        if error_code != 0 or provider is None:
            fail(f"create_async error={error_code}")
            return False

        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            | gatt.GattCharacteristicProperties.WRITE
            | gatt.GattCharacteristicProperties.NOTIFY
        )
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(MINIMAL_CHAR_UUID), char_params
        )
        c_err = int(c_res.error)
        if c_err != 0 or c_res.characteristic is None:
            fail(f"Characteristic creation error={c_err}")
            return False
        ok(f"Characteristic created (Write+WriteWithoutResponse+Notify, error={c_err})")

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        status = await poll_gatt_status(provider)
        name = GATT_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"advertisement_status = {status} ({name})")
            return True
        else:
            fail(f"advertisement_status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 5: is_connectable=False
# ------------------------------------------------------------------------------

async def test_gatt_not_connectable() -> bool:
    header("PHASE 5 -- GATT Advertising: is_connectable=False, is_discoverable=True")
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt

    provider = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(MINIMAL_SERVICE_UUID))
        provider = res.service_provider
        if int(res.error) != 0 or provider is None:
            fail(f"create_async error={res.error}")
            return False

        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            | gatt.GattCharacteristicProperties.WRITE
            | gatt.GattCharacteristicProperties.NOTIFY
        )
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(MINIMAL_CHAR_UUID), char_params
        )
        if int(c_res.error) != 0:
            fail(f"Characteristic error={c_res.error}")
            return False

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = False   # KEY DIFFERENCE vs BitChat default
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        status = await poll_gatt_status(provider)
        name = GATT_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"advertisement_status = {status} ({name}) -- is_connectable=False WORKS!")
            return True
        else:
            fail(f"advertisement_status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 6: Full BitChat service UUID + characteristic
# ------------------------------------------------------------------------------

async def test_bitchat_service_uuid() -> bool:
    header("PHASE 6 -- Full BitChat Service UUID + Characteristic")
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt

    provider = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(BITCHAT_SERVICE_UUID))
        error_code = int(res.error)
        provider = res.service_provider
        if error_code != 0 or provider is None:
            fail(f"create_async error={error_code}")
            return False
        ok(f"GattServiceProvider created with BitChat UUID (error={error_code})")

        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            | gatt.GattCharacteristicProperties.WRITE
            | gatt.GattCharacteristicProperties.NOTIFY
        )
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(BITCHAT_CHAR_UUID), char_params
        )
        c_err = int(c_res.error)
        if c_err != 0 or c_res.characteristic is None:
            fail(f"Characteristic creation error={c_err}")
            return False
        ok(f"BitChat characteristic created (error={c_err})")

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        status = await poll_gatt_status(provider)
        name = GATT_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"advertisement_status = {status} ({name})")
            return True
        else:
            fail(f"advertisement_status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 7: GATT + companion BluetoothLEAdvertisementPublisher
# ------------------------------------------------------------------------------

async def test_gatt_with_publisher() -> bool:
    header("PHASE 7 -- GATT + Companion BluetoothLEAdvertisementPublisher (BitChat full)")
    import winrt.windows.devices.bluetooth.advertisement as adv
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt
    from winrt.windows.storage.streams import DataWriter

    provider = None
    publisher = None
    try:
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(BITCHAT_SERVICE_UUID))
        error_code = int(res.error)
        provider = res.service_provider
        if error_code != 0 or provider is None:
            fail(f"create_async error={error_code}")
            return False

        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            | gatt.GattCharacteristicProperties.WRITE
            | gatt.GattCharacteristicProperties.NOTIFY
        )
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(BITCHAT_CHAR_UUID), char_params
        )
        if int(c_res.error) != 0:
            fail(f"Characteristic error={c_res.error}")
            return False

        params = gatt.GattServiceProviderAdvertisingParameters()
        params.is_connectable = True
        params.is_discoverable = True
        provider.start_advertising_with_parameters(params)

        gatt_status = await poll_gatt_status(provider)
        gatt_name = GATT_STATUS_NAMES.get(gatt_status, f"Unknown({gatt_status})")
        if gatt_status == 2:
            ok(f"GATT advertisement_status = {gatt_status} ({gatt_name})")
        else:
            fail(f"GATT advertisement_status = {gatt_status} ({gatt_name})")

        # Start companion publisher
        info("Starting companion BluetoothLEAdvertisementPublisher...")
        publisher = adv.BluetoothLEAdvertisementPublisher()
        m = adv.BluetoothLEManufacturerData()
        m.company_id = 0xFFFF
        writer = DataWriter()
        payload = b"BC" + uuid.UUID(BITCHAT_SERVICE_UUID).bytes
        writer.write_bytes(payload)
        m.data = writer.detach_buffer()
        publisher.advertisement.manufacturer_data.append(m)
        publisher.start()

        pub_status = await poll_publisher_status(publisher)
        pub_name = ADV_STATUS_NAMES.get(pub_status, f"Unknown({pub_status})")
        if pub_status == 2:
            ok(f"Publisher status = {pub_status} ({pub_name})")
        else:
            fail(f"Publisher status = {pub_status} ({pub_name})")

        # Re-check GATT status after publisher starts
        await asyncio.sleep(0.5)
        gatt_after = int(getattr(provider, "advertisement_status", -1))
        gatt_after_name = GATT_STATUS_NAMES.get(gatt_after, f"Unknown({gatt_after})")
        if gatt_after == gatt_status:
            ok(f"GATT status unchanged after publisher start: {gatt_after} ({gatt_after_name})")
        else:
            fail(
                f"GATT status CHANGED after publisher start: "
                f"{gatt_after} ({gatt_after_name}) was {gatt_status} ({gatt_name})"
            )

        return gatt_status in (2, 4) and pub_status == 2
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_publisher(publisher)
        stop_provider(provider)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 8: Publisher alone (no GATT)
# ------------------------------------------------------------------------------

async def test_publisher_only() -> bool:
    header("PHASE 8 -- BluetoothLEAdvertisementPublisher Alone (no GATT)")
    import winrt.windows.devices.bluetooth.advertisement as adv
    from winrt.windows.storage.streams import DataWriter

    publisher = None
    try:
        publisher = adv.BluetoothLEAdvertisementPublisher()
        m = adv.BluetoothLEManufacturerData()
        m.company_id = 0xFFFF
        writer = DataWriter()
        payload = b"BC" + uuid.UUID(BITCHAT_SERVICE_UUID).bytes
        writer.write_bytes(payload)
        m.data = writer.detach_buffer()
        publisher.advertisement.manufacturer_data.append(m)
        publisher.start()

        status = await poll_publisher_status(publisher)
        name = ADV_STATUS_NAMES.get(status, f"Unknown({status})")
        if status == 2:
            ok(f"Publisher status = {status} ({name})")
            return True
        else:
            fail(f"Publisher status = {status} ({name})")
            return False
    except Exception as e:
        fail(f"Exception: {e}")
        return False
    finally:
        stop_publisher(publisher)
        await asyncio.sleep(0.3)


# ------------------------------------------------------------------------------
# PHASE 9: Exact server.py _start_windows_server() reproduction
# ------------------------------------------------------------------------------

async def test_exact_bitchat_server() -> bool:
    header("PHASE 9 -- Exact BitChat server.py _start_windows_server() Reproduction")
    import winrt.windows.devices.bluetooth.advertisement as adv
    import winrt.windows.devices.bluetooth.genericattributeprofile as gatt
    from winrt.windows.storage.streams import DataWriter

    provider = None
    publisher = None

    try:
        # Step 1: Create service provider
        res = await gatt.GattServiceProvider.create_async(uuid.UUID(BITCHAT_SERVICE_UUID))
        if int(res.error) != 0 or res.service_provider is None:
            fail(f"GattServiceProvider.create_async error={res.error}")
            return False
        provider = res.service_provider
        ok(f"GattServiceProvider created (error={res.error})")

        # Step 2: Create characteristic
        char_params = gatt.GattLocalCharacteristicParameters()
        char_params.characteristic_properties = (
            gatt.GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            | gatt.GattCharacteristicProperties.WRITE
            | gatt.GattCharacteristicProperties.NOTIFY
        )
        c_res = await provider.service.create_characteristic_async(
            uuid.UUID(BITCHAT_CHAR_UUID), char_params
        )
        if int(c_res.error) != 0 or c_res.characteristic is None:
            fail(f"Characteristic create error={c_res.error}")
            return False
        ok(f"Characteristic created (error={c_res.error})")

        # Step 3: Start GATT advertising (exact server.py params)
        advertising_params = gatt.GattServiceProviderAdvertisingParameters()
        advertising_params.is_connectable = True
        advertising_params.is_discoverable = True
        provider.start_advertising_with_parameters(advertising_params)

        # Poll with correct enum values: Started=2, Aborted=3, StartedWithoutAllAdData=4
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5.0
        gatt_status = -1
        while loop.time() < deadline:
            gatt_status = int(getattr(provider, "advertisement_status", 0))
            if gatt_status in (2, 3, 4):
                break
            await asyncio.sleep(0.05)

        gatt_name = GATT_STATUS_NAMES.get(gatt_status, f"Unknown({gatt_status})")
        if gatt_status in (2, 4):
            ok(f"GATT advertisement_status = {gatt_status} ({gatt_name})")
        else:
            fail(f"GATT advertisement_status = {gatt_status} ({gatt_name})")
            info("-> Stopping here. Companion publisher tested separately in Phase 8.")
            return False

        # Step 4: Start companion publisher
        publisher = adv.BluetoothLEAdvertisementPublisher()
        m = adv.BluetoothLEManufacturerData()
        m.company_id = 0xFFFF
        writer = DataWriter()
        payload = b"BC" + uuid.UUID(BITCHAT_SERVICE_UUID).bytes
        writer.write_bytes(payload)
        m.data = writer.detach_buffer()
        publisher.advertisement.manufacturer_data.append(m)
        publisher.start()

        await asyncio.sleep(1.0)
        pub_status = int(getattr(publisher, "status", -1))
        pub_name = ADV_STATUS_NAMES.get(pub_status, f"Unknown({pub_status})")
        if pub_status == 2:
            ok(f"Publisher status = {pub_status} ({pub_name})")
        else:
            fail(f"Publisher status = {pub_status} ({pub_name})")

        return gatt_status in (2, 4) and pub_status == 2
    except Exception as e:
        fail(f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        stop_publisher(publisher)
        stop_provider(provider)
        await asyncio.sleep(0.5)


# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

async def main() -> None:
    print("=" * 72)
    print("  BitChat BLE GATT Peripheral Diagnostic")
    print("=" * 72)

    adapter_info = await test_adapter_info()

    if not adapter_info.get("is_peripheral"):
        print(
            "\n[WARNING] Adapter reports peripheral NOT supported "
            "-- GATT tests will likely all fail.\n"
            "          This is a hardware/driver limitation, not a BitChat bug."
        )

    results: dict[str, bool] = {}
    results["minimal_gatt_no_char"] = await test_minimal_gatt_no_char()
    results["minimal_gatt_notify_char"] = await test_minimal_gatt_notify_char()
    results["bitchat_char_properties"] = await test_bitchat_char_properties()
    results["gatt_not_connectable"] = await test_gatt_not_connectable()
    results["bitchat_service_uuid"] = await test_bitchat_service_uuid()
    results["gatt_with_publisher"] = await test_gatt_with_publisher()
    results["publisher_only"] = await test_publisher_only()
    results["exact_bitchat_server"] = await test_exact_bitchat_server()

    print(f"\n{'=' * 72}")
    print("  DIAGNOSTIC SUMMARY")
    print(f"{'=' * 72}")
    print(f"  Adapter: {adapter_info.get('radio_name', 'Unknown')}")
    print(f"  Radio state: {adapter_info.get('radio_state', 'Unknown')}")
    print(f"  Peripheral supported (WinRT): {adapter_info.get('is_peripheral', 'Unknown')}")
    print()
    for name, result in results.items():
        symbol = "[OK]  " if result else "[FAIL]"
        print(f"  {symbol} {name}")

    any_gatt_works = any(
        results.get(k)
        for k in [
            "minimal_gatt_no_char",
            "minimal_gatt_notify_char",
            "bitchat_char_properties",
            "bitchat_service_uuid",
        ]
    )

    print()
    if not any_gatt_works:
        print(
            "CONCLUSION: No GATT server configuration works on this machine.\n"
            "  -> This is a Windows/adapter/driver limitation, NOT a BitChat code bug.\n"
            "  -> BitChat should remain in Central-only mode with the current warning.\n"
            "  -> Possible causes: adapter driver does not actually implement peripheral\n"
            "     role even though WinRT capability metadata says it is supported.\n"
            "  -> Try: reboot, update Bluetooth driver, check Windows Bluetooth Support Service."
        )
    elif results.get("exact_bitchat_server"):
        print(
            "CONCLUSION: BitChat GATT server works correctly.\n"
            "  -> Status 3 seen previously may be transient/environmental (stale state).\n"
            "  -> Recommend: reboot + re-test to confirm."
        )
    else:
        # Some GATT configs work, not all -- find the diff
        passed = [k for k, v in results.items() if v]
        failed = [k for k, v in results.items() if not v]
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(
            "\nCONCLUSION: Some GATT configurations work. The specific BitChat config may\n"
            "  be triggering the failure. Check the passed/failed list above for the\n"
            "  minimal difference that causes status 3."
        )

        # Specific diagnosis for is_connectable=False success
        if results.get("gatt_not_connectable") and not results.get("bitchat_char_properties"):
            print(
                "\n  SPECIFIC FINDING: is_connectable=False succeeds but is_connectable=True fails.\n"
                "  -> Root cause: this adapter/driver does not support connectable GATT advertising.\n"
                "  -> Fix: use is_connectable=False in GattServiceProviderAdvertisingParameters.\n"
                "  -> Trade-off: central devices can discover the service but cannot connect via GATT."
            )

    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    asyncio.run(main())

