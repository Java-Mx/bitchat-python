"""In-memory fake of the BlueZ D-Bus surface used by BitChat.

Allows testing the real Linux BlueZ BLEServer and BluetoothTransport control flows
(GATT application, service, characteristic, LE advertisement, D-Bus message handling,
client read/write/notify, error states, and cleanup) on any platform without host
Bluetooth hardware or system D-Bus daemon.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any

from bitchat.ble.bluez import (
    BusType,
    DBusError,
    Message,
    MessageBus,
    MessageFlag,
    MessageType,
    PropertyAccess,
    PropertyAccessFlag,
    Variant,
)

if TYPE_CHECKING:
    import pytest


class FakeBlueZBus:
    """Mock D-Bus MessageBus that intercepts BlueZ method calls and routes exports."""

    def __init__(self, owner: FakeBlueZ) -> None:
        self._owner = owner
        self.exported: dict[str, Any] = {}
        self.is_connected: bool = True
        self.call_history: list[Message] = []
        self._serial: int = 0

    def export(self, path: str, interface: Any) -> None:
        self.exported[path] = interface
        # Track characteristic for notification capture
        if getattr(interface, "name", "") == "org.bluez.GattCharacteristic1":
            self._owner.characteristics.append(interface)
            if not getattr(interface, "_fake_patched", False):
                orig_emit = interface.emit_properties_changed

                def patched_emit(
                    changed: dict[str, Any], invalidated: list[str] | None = None
                ) -> None:
                    self._owner.emitted_notifications.append(changed)
                    orig_emit(changed, invalidated or [])

                interface.emit_properties_changed = patched_emit
                interface._fake_patched = True

    def unexport(self, path: str, interface: Any | None = None) -> None:
        old_iface = self.exported.pop(path, None)
        if old_iface is not None and old_iface in self._owner.characteristics:
            self._owner.characteristics.remove(old_iface)

    def disconnect(self) -> None:
        self.is_connected = False

    async def call(self, message: Message) -> Message:
        if message.serial == 0:
            self._serial += 1
            message.serial = self._serial
        self.call_history.append(message)

        # 1. DBus NameOwner check for org.bluez
        if (
            message.destination == "org.freedesktop.DBus"
            and message.member == "GetNameOwner"
        ):
            if self._owner.bluez_running and message.body == ["org.bluez"]:
                return Message.new_method_return(
                    message,
                    "s",
                    [":1.42"],
                )
            return Message.new_error(
                message,
                "org.freedesktop.DBus.Error.NameHasNoOwner",
                "Name org.bluez has no owner",
            )

        # 2. ObjectManager.GetManagedObjects on org.bluez
        if message.destination == "org.bluez" and message.member == "GetManagedObjects":
            if not self._owner.bluez_running:
                return Message.new_error(
                    message,
                    "org.freedesktop.DBus.Error.ServiceUnknown",
                    "The name org.bluez was not provided by any .service files",
                )
            if self._owner.managed_objects_error:
                return Message.new_error(
                    message,
                    self._owner.managed_objects_error,
                    "Error retrieving managed objects",
                )

            if not self._owner.has_adapter:
                return Message.new_method_return(
                    message,
                    "a{oa{sa{sv}}}",
                    [{}],
                )

            ifaces: dict[str, dict[str, Variant]] = {}
            adapter_props: dict[str, Variant] = {
                "Address": Variant("s", self._owner.adapter_address),
                "Name": Variant("s", self._owner.adapter_name),
                "Alias": Variant("s", self._owner.adapter_name),
                "Powered": Variant("b", self._owner.adapter_powered),
                "Discovering": Variant("b", False),
            }
            ifaces["org.bluez.Adapter1"] = adapter_props

            if self._owner.has_gatt_manager:
                ifaces["org.bluez.GattManager1"] = {}

            if self._owner.has_advertising_manager:
                ifaces["org.bluez.LEAdvertisingManager1"] = {
                    "ActiveInstances": Variant(
                        "y", len(self._owner.registered_advertisements)
                    ),
                    "SupportedInstances": Variant("y", 12),
                }

            return Message.new_method_return(
                message,
                "a{oa{sa{sv}}}",
                [{self._owner.adapter_path: ifaces}],
            )

        # 3. GattManager1.RegisterApplication
        if (
            message.interface == "org.bluez.GattManager1"
            and message.member == "RegisterApplication"
        ):
            if self._owner.register_app_error:
                return Message.new_error(
                    message,
                    self._owner.register_app_error,
                    "Failed to register GATT application",
                )
            app_path = message.body[0]
            if app_path not in self.exported:
                return Message.new_error(
                    message,
                    "org.bluez.Error.InvalidArguments",
                    f"Application object {app_path} is not exported on D-Bus",
                )
            self._owner.registered_applications.append(app_path)
            app_obj = self.exported.get(app_path)
            if app_obj and hasattr(app_obj, "get_managed_objects"):
                self._owner.app_managed_objects[app_path] = (
                    app_obj.get_managed_objects()
                )
            elif app_obj and hasattr(app_obj, "GetManagedObjects"):
                self._owner.app_managed_objects[app_path] = getattr(
                    app_obj.GetManagedObjects,
                    "__wrapped__",
                    app_obj.GetManagedObjects,
                )(app_obj)
            return Message.new_method_return(
                message,
                "",
                [],
            )

        # 4. GattManager1.UnregisterApplication
        if (
            message.interface == "org.bluez.GattManager1"
            and message.member == "UnregisterApplication"
        ):
            app_path = message.body[0]
            if app_path in self._owner.registered_applications:
                self._owner.registered_applications.remove(app_path)
            return Message.new_method_return(
                message,
                "",
                [],
            )

        # 5. LEAdvertisingManager1.RegisterAdvertisement
        if (
            message.interface == "org.bluez.LEAdvertisingManager1"
            and message.member == "RegisterAdvertisement"
        ):
            if self._owner.register_adv_error:
                return Message.new_error(
                    message,
                    self._owner.register_adv_error,
                    "Failed to register LE advertisement",
                )
            adv_path = message.body[0]
            if adv_path not in self.exported:
                return Message.new_error(
                    message,
                    "org.bluez.Error.InvalidArguments",
                    f"Advertisement object {adv_path} is not exported on D-Bus",
                )
            self._owner.registered_advertisements.append(adv_path)
            return Message.new_method_return(
                message,
                "",
                [],
            )

        # 6. LEAdvertisingManager1.UnregisterAdvertisement
        if (
            message.interface == "org.bluez.LEAdvertisingManager1"
            and message.member == "UnregisterAdvertisement"
        ):
            adv_path = message.body[0]
            if adv_path in self._owner.registered_advertisements:
                self._owner.registered_advertisements.remove(adv_path)
            return Message.new_method_return(
                message,
                "",
                [],
            )

        # Fallback default success
        return Message.new_method_return(
            message,
            "",
            [],
        )


class FakeBlueZ:
    """Configurable test fixture simulating BlueZ daemon and Bluetooth adapter
    over D-Bus.
    """

    def __init__(self) -> None:
        self.bluez_running: bool = True
        self.has_adapter: bool = True
        self.adapter_path: str = "/org/bluez/hci0"
        self.adapter_name: str = "Fake-HCI0"
        self.adapter_address: str = "00:11:22:33:44:55"
        self.adapter_powered: bool = True
        self.has_gatt_manager: bool = True
        self.has_advertising_manager: bool = True

        self.managed_objects_error: str | None = None
        self.register_app_error: str | None = None
        self.register_adv_error: str | None = None

        self.registered_applications: list[str] = []
        self.registered_advertisements: list[str] = []
        self.app_managed_objects: dict[str, Any] = {}
        self.characteristics: list[Any] = []
        self.emitted_notifications: list[dict[str, Any]] = []

        self.bus: FakeBlueZBus = FakeBlueZBus(self)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeBlueZ:
        """Patch system MessageBus and platform detection to use this FakeBlueZ."""
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("bitchat.ble.bluez.HAS_DBUS_FAST", True)

        async def fake_connect(*args: Any, **kwargs: Any) -> FakeBlueZBus:
            self.bus.is_connected = True
            return self.bus

        monkeypatch.setattr(MessageBus, "connect", fake_connect)

        try:
            import dbus_fast.aio  # pyright: ignore[reportMissingImports]

            monkeypatch.setattr(dbus_fast.aio.MessageBus, "connect", fake_connect)
        except ImportError:
            aio_mod: Any = types.ModuleType("dbus_fast.aio")
            aio_mod.MessageBus = MessageBus
            errors_mod: Any = types.ModuleType("dbus_fast.errors")
            errors_mod.DBusError = DBusError
            constants_mod: Any = types.ModuleType("dbus_fast.constants")
            constants_mod.BusType = BusType
            constants_mod.MessageFlag = MessageFlag
            constants_mod.MessageType = MessageType
            constants_mod.PropertyAccess = PropertyAccess
            constants_mod.PropertyAccessFlag = PropertyAccessFlag
            root_mod: Any = types.ModuleType("dbus_fast")
            root_mod.__path__ = []
            root_mod.BusType = BusType
            root_mod.Message = Message
            root_mod.MessageFlag = MessageFlag
            root_mod.MessageType = MessageType
            root_mod.PropertyAccess = PropertyAccess
            root_mod.PropertyAccessFlag = PropertyAccessFlag
            root_mod.Variant = Variant
            root_mod.aio = aio_mod
            root_mod.constants = constants_mod
            root_mod.errors = errors_mod
            monkeypatch.setitem(sys.modules, "dbus_fast", root_mod)
            monkeypatch.setitem(sys.modules, "dbus_fast.aio", aio_mod)
            monkeypatch.setitem(sys.modules, "dbus_fast.constants", constants_mod)
            monkeypatch.setitem(sys.modules, "dbus_fast.errors", errors_mod)

        return self

    def get_characteristic(self) -> Any | None:
        """Return the active BitChat characteristic if exported."""
        for obj in self.bus.exported.values():
            if getattr(obj, "name", "") == "org.bluez.GattCharacteristic1":
                return obj
        if self.characteristics:
            return self.characteristics[-1]
        return None

    def release_advertisement(self) -> None:
        """Simulate BlueZ daemon releasing the active advertisement."""
        for adv_path in list(self.registered_advertisements):
            adv_obj = self.bus.exported.get(adv_path)
            if adv_obj:
                rel_fn = getattr(getattr(adv_obj, "Release", None), "__wrapped__", None)
                if rel_fn is not None:
                    rel_fn(adv_obj)
                elif hasattr(adv_obj, "Release"):
                    adv_obj.Release()
            self.registered_advertisements.remove(adv_path)

    def write_characteristic(
        self,
        data: bytes,
        client_id: str = "11:22:33:44:55:66",
        offset: int = 0,
    ) -> None:
        """Simulate an incoming client write to the GATT characteristic."""
        char = self.get_characteristic()
        if char is None:
            raise RuntimeError("No GATT characteristic exported on FakeBlueZ")
        device_path = f"/org/bluez/hci0/dev_{client_id.replace(':', '_')}"
        options: dict[str, Any] = {"device": Variant("o", device_path)}
        if offset != 0:
            options["offset"] = Variant("i" if offset < 0 else "q", offset)
        method_fn = getattr(getattr(char, "WriteValue", None), "__wrapped__", None)
        if method_fn is not None:
            method_fn(char, data, options)
        elif hasattr(char, "write_value"):
            char.write_value(data, client_id, offset)
        else:
            char.WriteValue(data, options)

    def read_characteristic(self, offset: int = 0) -> bytes:
        """Simulate an incoming client read from the GATT characteristic."""
        char = self.get_characteristic()
        if char is None:
            raise RuntimeError("No GATT characteristic exported on FakeBlueZ")
        options: dict[str, Any] = {}
        if offset != 0:
            options["offset"] = Variant("i" if offset < 0 else "q", offset)
        method_fn = getattr(getattr(char, "ReadValue", None), "__wrapped__", None)
        if method_fn is not None:
            return bytes(method_fn(char, options))
        elif hasattr(char, "read_value"):
            return char.read_value(offset)
        return bytes(char.ReadValue(options))

    def start_notify(self) -> None:
        """Simulate a client enabling notifications."""
        char = self.get_characteristic()
        if char is None:
            raise RuntimeError("No GATT characteristic exported on FakeBlueZ")
        method_fn = getattr(getattr(char, "StartNotify", None), "__wrapped__", None)
        if method_fn is not None:
            method_fn(char)
        elif hasattr(char, "start_notify"):
            char.start_notify()
        else:
            char.StartNotify()

    def stop_notify(self) -> None:
        """Simulate a client disabling notifications."""
        char = self.get_characteristic()
        if char is None:
            raise RuntimeError("No GATT characteristic exported on FakeBlueZ")
        method_fn = getattr(getattr(char, "StopNotify", None), "__wrapped__", None)
        if method_fn is not None:
            method_fn(char)
        elif hasattr(char, "stop_notify"):
            char.stop_notify()
        else:
            char.StopNotify()
