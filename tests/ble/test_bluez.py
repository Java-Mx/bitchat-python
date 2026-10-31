# pyright: reportAttributeAccessIssue=false
"""Unit tests for Linux BlueZ BLEServer backend and D-Bus integration."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from tests.ble.fake_bluez import FakeBlueZ

from bitchat.ble.bluez import (
    _manufacturer_advertisement_payload,
)
from bitchat.ble.server import BLEServer
from bitchat.exceptions import BLEError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)


@pytest.fixture
def fake_bluez(monkeypatch: pytest.MonkeyPatch) -> FakeBlueZ:
    return FakeBlueZ().install(monkeypatch)


@pytest.mark.asyncio
async def test_bluez_server_registers_application_and_advertisement(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    assert server.supports_peripheral is True

    await server.start()

    assert server.is_advertising is True
    assert len(fake_bluez.registered_applications) == 1
    assert len(fake_bluez.registered_advertisements) == 1

    telemetry = server.get_telemetry()
    assert telemetry["server_active"] is True
    assert telemetry["has_provider"] is True
    assert telemetry["has_publisher"] is True
    assert telemetry["last_error"] is None

    # Check that application registered service and characteristic UUIDs correctly
    app_path = fake_bluez.registered_applications[0]
    managed = fake_bluez.app_managed_objects.get(app_path, {})
    service_entry = next(
        v["org.bluez.GattService1"]
        for v in managed.values()
        if "org.bluez.GattService1" in v
    )
    assert service_entry["UUID"].value == BITCHAT_SERVICE_UUID.lower()
    char_entry = next(
        v["org.bluez.GattCharacteristic1"]
        for v in managed.values()
        if "org.bluez.GattCharacteristic1" in v
    )
    assert char_entry["UUID"].value == BITCHAT_CHARACTERISTIC_UUID.lower()
    assert char_entry["Notifying"].value is False

    await server.stop()

    assert server.is_advertising is False
    assert len(fake_bluez.registered_applications) == 0
    assert len(fake_bluez.registered_advertisements) == 0
    assert len(fake_bluez.bus.exported) == 0


@pytest.mark.asyncio
async def test_bluez_server_receive_write_with_device_address(
    fake_bluez: FakeBlueZ,
) -> None:
    received: list[tuple[bytes, str]] = []

    def on_recv(data: bytes, client_id: str) -> None:
        received.append((data, client_id))

    server = BLEServer(on_data_received=on_recv, linux_bus=fake_bluez.bus)
    await server.start()

    # Simulate client writing to the exported characteristic
    fake_bluez.write_characteristic(b"packet_bytes", client_id="AA:BB:CC:DD:EE:FF")

    assert len(received) == 1
    assert received[0] == (b"packet_bytes", "AA:BB:CC:DD:EE:FF")

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_read_value(fake_bluez: FakeBlueZ) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    char = fake_bluez.get_characteristic()
    assert char is not None
    assert fake_bluez.read_characteristic() == b""

    # Send notification sets characteristic value
    await server.send_notification(b"current_state")
    assert fake_bluez.read_characteristic() == b"current_state"

    # Test read with offset
    offset_val = char.read_value(offset=8)
    assert bytes(offset_val) == b"state"

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_send_notification(fake_bluez: FakeBlueZ) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    await server.send_notification(b"test_payload")

    assert len(fake_bluez.emitted_notifications) == 1
    assert fake_bluez.emitted_notifications[0]["Value"] == b"test_payload"

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_subscribe_unsubscribe_callbacks(
    fake_bluez: FakeBlueZ,
) -> None:
    events: list[str] = []

    server = BLEServer(
        on_client_subscribed=lambda c: events.append(f"sub:{c}"),
        on_client_unsubscribed=lambda c: events.append(f"unsub:{c}"),
        linux_bus=fake_bluez.bus,
    )
    await server.start()

    fake_bluez.start_notify()
    assert events == ["sub:bluez_client"]

    fake_bluez.stop_notify()
    assert events == ["sub:bluez_client", "unsub:bluez_client"]

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_unsupported_gatt_manager(fake_bluez: FakeBlueZ) -> None:
    fake_bluez.has_gatt_manager = False
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "GattManager1" in (server.get_telemetry()["last_error"] or "")
    assert len(fake_bluez.registered_applications) == 0
    assert len(fake_bluez.registered_advertisements) == 0


@pytest.mark.asyncio
async def test_bluez_server_unsupported_advertising_manager(
    fake_bluez: FakeBlueZ,
) -> None:
    fake_bluez.has_advertising_manager = False
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "LEAdvertisingManager1" in (server.get_telemetry()["last_error"] or "")
    assert len(fake_bluez.registered_applications) == 0
    assert len(fake_bluez.registered_advertisements) == 0


@pytest.mark.asyncio
async def test_bluez_server_adapter_powered_off(fake_bluez: FakeBlueZ) -> None:
    fake_bluez.adapter_powered = False
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "powered off" in (server.get_telemetry()["last_error"] or "")


@pytest.mark.asyncio
async def test_bluez_server_no_adapter_found(fake_bluez: FakeBlueZ) -> None:
    fake_bluez.has_adapter = False
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "No Bluetooth adapter" in (server.get_telemetry()["last_error"] or "")


@pytest.mark.asyncio
async def test_bluez_server_bluez_not_running(fake_bluez: FakeBlueZ) -> None:
    fake_bluez.bluez_running = False
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "ServiceUnknown" in (server.get_telemetry()["last_error"] or "")


@pytest.mark.asyncio
async def test_bluez_server_gatt_registration_error_cleanup(
    fake_bluez: FakeBlueZ,
) -> None:
    fake_bluez.register_app_error = "org.bluez.Error.Failed"
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "GattManager1.RegisterApplication failed" in (
        server.get_telemetry()["last_error"] or ""
    )
    # Check that no objects remain leaked on D-Bus
    assert len(fake_bluez.bus.exported) == 0


@pytest.mark.asyncio
async def test_bluez_server_adv_registration_error_cleanup(
    fake_bluez: FakeBlueZ,
) -> None:
    fake_bluez.register_adv_error = "org.bluez.Error.Failed"
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is False
    assert "LEAdvertisingManager1.RegisterAdvertisement failed" in (
        server.get_telemetry()["last_error"] or ""
    )
    # Check that application was unregistered and no exports remain
    assert len(fake_bluez.registered_applications) == 0
    assert len(fake_bluez.bus.exported) == 0


@pytest.mark.asyncio
async def test_bluez_server_advertisement_fallback_on_initial_failure(
    fake_bluez: FakeBlueZ,
) -> None:
    # First attempt to register advertisement returns error,
    # but second attempt (without manufacturer data) succeeds
    attempts = 0
    orig_call = fake_bluez.bus.call

    async def custom_call(msg: Any) -> Any:
        nonlocal attempts
        if getattr(msg, "serial", 0) == 0:
            fake_bluez.bus._serial += 1
            msg.serial = fake_bluez.bus._serial
        if (
            msg.interface == "org.bluez.LEAdvertisingManager1"
            and msg.member == "RegisterAdvertisement"
        ):
            attempts += 1
            if attempts == 1:
                from bitchat.ble.bluez import Message

                return Message.new_error(
                    msg,
                    "org.bluez.Error.Failed",
                    "Data exceeds maximum advertisement size",
                )
        return await orig_call(msg)

    fake_bluez.bus.call = custom_call  # type: ignore[method-assign]
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is True
    assert attempts == 2
    assert len(fake_bluez.registered_advertisements) == 1

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_repeated_start_stop_cycles(fake_bluez: FakeBlueZ) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)

    for _ in range(3):
        await server.start()
        assert server.is_advertising is True
        assert len(fake_bluez.registered_applications) == 1
        assert len(fake_bluez.registered_advertisements) == 1

        await server.stop()
        assert server.is_advertising is False
        assert len(fake_bluez.registered_applications) == 0
        assert len(fake_bluez.registered_advertisements) == 0
        assert len(fake_bluez.bus.exported) == 0


@pytest.mark.asyncio
async def test_bluez_server_cancel_during_start_cleans_up(
    fake_bluez: FakeBlueZ,
) -> None:
    # Suspend inside RegisterAdvertisement
    pause_event = asyncio.Event()
    orig_call = fake_bluez.bus.call

    async def hanging_call(msg: Any) -> Any:
        if (
            msg.interface == "org.bluez.LEAdvertisingManager1"
            and msg.member == "RegisterAdvertisement"
        ):
            await pause_event.wait()
        return await orig_call(msg)

    server = BLEServer(linux_bus=fake_bluez.bus)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fake_bluez.bus, "call", hanging_call)
        task = asyncio.create_task(server.start())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert server.is_advertising is False
    assert len(fake_bluez.registered_applications) == 0
    assert len(fake_bluez.bus.exported) == 0


@pytest.mark.asyncio
async def test_bluez_server_send_notification_when_not_active_raises() -> None:
    server = BLEServer()
    with pytest.raises(BLEError, match="not active"):
        await server.send_notification(b"test")


@pytest.mark.asyncio
async def test_bluez_server_send_notification_emits_error_raises_ble_error(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()
    char = fake_bluez.get_characteristic()
    assert char is not None

    def raise_err(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("DBus signal failed")

    char.emit_properties_changed = raise_err
    with pytest.raises(BLEError, match="Failed to notify Linux BLE characteristic"):
        await server.send_notification(b"test")
    await server.stop()


def test_manufacturer_advertisement_payload() -> None:
    payload = _manufacturer_advertisement_payload(BITCHAT_SERVICE_UUID)
    assert payload.startswith(b"BC")
    assert len(payload) == 18


@pytest.mark.asyncio
async def test_bluez_server_daemon_releases_advertisement_updates_state(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()
    assert server.is_advertising is True

    # Simulate BlueZ daemon releasing the advertisement
    fake_bluez.release_advertisement()

    assert server.is_advertising is False
    assert server.get_telemetry()["is_advertising"] is False
    assert server.get_telemetry()["has_publisher"] is False

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_multiple_adapters_selects_fully_capable(
    fake_bluez: FakeBlueZ,
) -> None:
    # Setup bus to return two adapters:
    # hci0: powered, has GattManager1 but lacks LEAdvertisingManager1
    # hci1: powered, has BOTH GattManager1 and LEAdvertisingManager1
    from bitchat.ble.bluez import Message, Variant

    orig_call = fake_bluez.bus.call

    async def multi_adapter_call(msg: Message) -> Message:
        if msg.serial == 0:
            fake_bluez.bus._serial += 1
            msg.serial = fake_bluez.bus._serial
        if msg.destination == "org.bluez" and msg.member == "GetManagedObjects":
            ifaces_hci0 = {
                "org.bluez.Adapter1": {
                    "Address": Variant("s", "00:11:22:33:44:00"),
                    "Powered": Variant("b", True),
                },
                "org.bluez.GattManager1": {},
            }
            ifaces_hci1 = {
                "org.bluez.Adapter1": {
                    "Address": Variant("s", "00:11:22:33:44:01"),
                    "Powered": Variant("b", True),
                },
                "org.bluez.GattManager1": {},
                "org.bluez.LEAdvertisingManager1": {
                    "ActiveInstances": Variant("y", 0),
                    "SupportedInstances": Variant("y", 12),
                },
            }
            return Message.new_method_return(
                msg,
                "a{oa{sa{sv}}}",
                [{"/org/bluez/hci0": ifaces_hci0, "/org/bluez/hci1": ifaces_hci1}],
            )
        return await orig_call(msg)

    fake_bluez.bus.call = multi_adapter_call  # type: ignore[method-assign]
    server = BLEServer(linux_bus=fake_bluez.bus)

    await server.start()

    assert server.is_advertising is True
    assert fake_bluez.registered_applications[0].startswith(
        "/io/github/java_mx/bitchat/"
    )
    # Registration was sent to /org/bluez/hci1
    call_paths = [
        m.path
        for m in fake_bluez.bus.call_history
        if m.interface == "org.bluez.GattManager1"
    ]
    assert "/org/bluez/hci1" in call_paths

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_target_adapter_path_validation(
    fake_bluez: FakeBlueZ,
) -> None:
    from bitchat.ble.bluez import BlueZServerBackend

    # Requesting non-existent adapter raises
    backend = BlueZServerBackend(bus=fake_bluez.bus, adapter_path="/org/bluez/hci99")
    with pytest.raises(BLEError, match="not found in BlueZ"):
        await backend.start()

    # Requesting powered off adapter raises
    fake_bluez.adapter_powered = False
    backend2 = BlueZServerBackend(
        bus=fake_bluez.bus, adapter_path=fake_bluez.adapter_path
    )
    with pytest.raises(BLEError, match="powered off"):
        await backend2.start()


@pytest.mark.asyncio
async def test_bluez_server_dynamic_callback_updates(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    # Set callbacks AFTER server.start()
    received: list[tuple[bytes, str]] = []
    events: list[str] = []
    server.on_data_received = lambda d, c: received.append((d, c))
    server.on_client_subscribed = lambda c: events.append(f"sub:{c}")
    server.on_client_unsubscribed = lambda c: events.append(f"unsub:{c}")

    fake_bluez.write_characteristic(b"dynamic_data", client_id="11:22:33:44:55:66")
    assert received == [(b"dynamic_data", "11:22:33:44:55:66")]

    fake_bluez.start_notify()
    assert events == ["sub:bluez_client"]

    fake_bluez.stop_notify()
    assert events == ["sub:bluez_client", "unsub:bluez_client"]

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_characteristic_notifying_property_and_properties_changed(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    char = fake_bluez.get_characteristic()
    assert char is not None
    assert char.Notifying is False

    fake_bluez.start_notify()
    assert char.Notifying is True
    assert any(n.get("Notifying") is True for n in fake_bluez.emitted_notifications)

    fake_bluez.stop_notify()
    assert char.Notifying is False
    assert any(n.get("Notifying") is False for n in fake_bluez.emitted_notifications)

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_read_value_out_of_bounds_offset_raises_dbus_error(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    char = fake_bluez.get_characteristic()
    assert char is not None
    await server.send_notification(b"short")

    with pytest.raises(Exception) as exc_info:
        fake_bluez.read_characteristic(offset=10)
    assert getattr(exc_info.value, "type", "") == "org.bluez.Error.InvalidOffset"

    with pytest.raises(Exception) as exc_info:
        fake_bluez.read_characteristic(offset=-1)
    assert getattr(exc_info.value, "type", "") == "org.bluez.Error.InvalidOffset"

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_write_value_offset_handling(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    char = fake_bluez.get_characteristic()
    assert char is not None

    # Write initial data
    fake_bluez.write_characteristic(b"hello world")
    assert fake_bluez.read_characteristic() == b"hello world"

    # Splice write at offset 6
    fake_bluez.write_characteristic(b"bitchat", offset=6)
    assert fake_bluez.read_characteristic() == b"hello bitchat"

    # Out of bounds offset write raises InvalidOffset
    with pytest.raises(Exception) as exc_info:
        fake_bluez.write_characteristic(b"err", offset=100)
    assert getattr(exc_info.value, "type", "") == "org.bluez.Error.InvalidOffset"

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_server_target_adapter_short_name_resolved(
    fake_bluez: FakeBlueZ,
) -> None:
    from bitchat.ble.bluez import BlueZServerBackend

    # Specify short name "hci0" instead of "/org/bluez/hci0"
    backend = BlueZServerBackend(bus=fake_bluez.bus, adapter_path="hci0")
    await backend.start()
    assert backend.is_advertising is True
    assert backend._adapter_path == "/org/bluez/hci0"
    await backend.stop()


@pytest.mark.asyncio
async def test_bluez_server_identity_tracking(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(
        peer_id="peer123",
        nickname="alice",
        linux_bus=fake_bluez.bus,
    )
    await server.start()
    assert server._linux_backend is not None
    assert server._linux_backend.peer_id == "peer123"
    assert server._linux_backend.nickname == "alice"

    server.update_identity("peer456", "bob")
    assert server._linux_backend.peer_id == "peer456"
    assert server._linux_backend.nickname == "bob"

    await server.stop()


@pytest.mark.asyncio
async def test_bluez_managed_objects_reflects_characteristic_state(
    fake_bluez: FakeBlueZ,
) -> None:
    server = BLEServer(linux_bus=fake_bluez.bus)
    await server.start()

    backend = server._linux_backend
    assert backend is not None
    app = backend._app
    assert app is not None

    # Initially not notifying
    managed = app.get_managed_objects()
    char_entry = next(
        v["org.bluez.GattCharacteristic1"]
        for v in managed.values()
        if "org.bluez.GattCharacteristic1" in v
    )
    assert char_entry["Notifying"].value is False
    assert char_entry["Value"].value == b""

    # Start notify and send notification
    fake_bluez.start_notify()
    await server.send_notification(b"active_data")

    # Managed objects reflect live value and notifying flag
    managed2 = app.get_managed_objects()
    char_entry2 = next(
        v["org.bluez.GattCharacteristic1"]
        for v in managed2.values()
        if "org.bluez.GattCharacteristic1" in v
    )
    assert char_entry2["Notifying"].value is True
    assert char_entry2["Value"].value == b"active_data"

    await server.stop()


@pytest.mark.asyncio
async def test_fake_bluez_unexported_application_and_advertisement_rejected(
    fake_bluez: FakeBlueZ,
) -> None:
    from bitchat.ble.bluez import Message

    # Try registering application without exporting it first
    reply = await fake_bluez.bus.call(
        Message(
            destination="org.bluez",
            path="/org/bluez/hci0",
            interface="org.bluez.GattManager1",
            member="RegisterApplication",
            signature="oa{sv}",
            body=["/unexported/app", {}],
        )
    )
    assert reply.message_type.name == "ERROR"
    assert reply.error_name == "org.bluez.Error.InvalidArguments"

    # Try registering advertisement without exporting it first
    reply_adv = await fake_bluez.bus.call(
        Message(
            destination="org.bluez",
            path="/org/bluez/hci0",
            interface="org.bluez.LEAdvertisingManager1",
            member="RegisterAdvertisement",
            signature="oa{sv}",
            body=["/unexported/adv", {}],
        )
    )
    assert reply_adv.message_type.name == "ERROR"
    assert reply_adv.error_name == "org.bluez.Error.InvalidArguments"
