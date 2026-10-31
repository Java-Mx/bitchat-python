"""Linux BlueZ D-Bus backend for BitChat GATT server and LE advertising."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import uuid
from typing import TYPE_CHECKING, Annotated, Any

from bitchat.exceptions import BLEError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

if sys.platform == "linux":
    try:
        from dbus_fast import (  # pyright: ignore[reportMissingImports]
            BusType,
            Message,
            MessageType,
            Variant,
        )
        from dbus_fast.aio import MessageBus  # pyright: ignore[reportMissingImports]
        from dbus_fast.annotations import (  # pyright: ignore[reportMissingImports]
            DBusBool,
            DBusBytes,
            DBusDict,
            DBusObjectPath,
            DBusSignature,
            DBusStr,
        )
        from dbus_fast.constants import PropertyAccess  # pyright: ignore[reportMissingImports]
        from dbus_fast.errors import DBusError  # pyright: ignore[reportMissingImports]
        from dbus_fast.service import (  # pyright: ignore[reportMissingImports]
            ServiceInterface,
            dbus_property,
            method,
        )

        try:
            from dbus_fast.constants import MessageFlag  # pyright: ignore[reportMissingImports]
        except ImportError:
            from enum import IntFlag

            class MessageFlag(IntFlag):
                NONE = 0
                NO_REPLY_EXPECTED = 1
                NO_AUTO_START = 2
                ALLOW_INTERACTIVE_AUTHORIZATION = 4

        try:
            from dbus_fast.constants import PropertyAccessFlag  # pyright: ignore[reportMissingImports]
        except ImportError:
            PropertyAccessFlag = PropertyAccess

        HAS_DBUS_FAST = True
    except ImportError:
        HAS_DBUS_FAST = False
else:
    HAS_DBUS_FAST = False

if sys.platform != "linux" or not HAS_DBUS_FAST:
    from enum import Enum, IntFlag

    type DBusBool = bool
    type DBusBytes = bytes
    type DBusDict = dict[Any, Any]
    type DBusObjectPath = str
    type DBusStr = str

    class PropertyAccess(Enum):
        READ = "read"
        WRITE = "write"
        READWRITE = "readwrite"

    PropertyAccessFlag = PropertyAccess

    class BusType(Enum):
        SESSION = 1
        SYSTEM = 2

    class MessageType(Enum):
        METHOD_CALL = 1
        METHOD_RETURN = 2
        ERROR = 3
        SIGNAL = 4

    class MessageFlag(IntFlag):
        NONE = 0
        NO_REPLY_EXPECTED = 1
        NO_AUTO_START = 2
        ALLOW_INTERACTIVE_AUTHORIZATION = 4

    class DBusError(Exception):
        def __init__(self, name: str, msg: str) -> None:
            super().__init__(msg)
            self.type = name
            self.name = name
            self.text = msg

    class Message:
        def __init__(
            self,
            destination: str | None = None,
            path: str | None = None,
            interface: str | None = None,
            member: str | None = None,
            message_type: MessageType = MessageType.METHOD_CALL,
            flags: MessageFlag = MessageFlag.NONE,
            signature: str = "",
            body: list[Any] | None = None,
            serial: int = 0,
            error_name: str | None = None,
            reply_serial: int = 0,
        ) -> None:
            self.destination = destination
            self.path = path
            self.interface = interface
            self.member = member
            self.message_type = message_type
            self.flags = flags
            self.signature = signature
            self.body: list[Any] = list(body) if body is not None else []
            self.serial = serial
            self.error_name = error_name
            self.reply_serial = reply_serial

        @classmethod
        def new_method_return(
            cls,
            msg: Message,
            signature: str = "",
            body: list[Any] | None = None,
        ) -> Message:
            return cls(
                message_type=MessageType.METHOD_RETURN,
                signature=signature,
                body=list(body) if body is not None else [],
                reply_serial=msg.serial,
            )

        @classmethod
        def new_error(cls, msg: Message, error_name: str, error_text: str) -> Message:
            return cls(
                message_type=MessageType.ERROR,
                error_name=error_name,
                signature="s",
                body=[error_text],
                reply_serial=msg.serial,
            )

    class Variant:
        def __init__(self, signature: str, value: Any) -> None:
            self.signature = signature
            self.value = value

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, Variant):
                return NotImplemented
            return self.signature == other.signature and self.value == other.value

    class DBusSignature:
        def __init__(self, signature: str) -> None:
            self.signature = signature

    class ServiceInterface:
        def __init__(self, name: str) -> None:
            self.name = name

        def emit_properties_changed(
            self,
            changed_properties: dict[str, Any],
            invalidated_properties: list[str] | None = None,
        ) -> None:
            pass

    class MessageBus:
        def __init__(self, bus_type: Any = None, **kwargs: Any) -> None:
            self.bus_type = bus_type

        async def connect(self) -> Any:
            raise BLEError("dbus-fast is required for Linux BlueZ peripheral mode")

    def dbus_property(*args: Any, **kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            return property(fn)

        return decorator

    def method(*args: Any, **kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            fn.__wrapped__ = fn
            return fn

        return decorator


ArrayOfString = Annotated[list[str], DBusSignature("as")]
ArrayOfObject = Annotated[list[str], DBusSignature("ao")]
ManufacturerDict = Annotated[dict[int, Variant], DBusSignature("a{qv}")]
ManagedObjectsDict = Annotated[
    dict[str, dict[str, dict[str, Variant]]], DBusSignature("a{oa{sa{sv}}}")
]

_counter = 0


def _next_id() -> int:
    global _counter
    _counter += 1
    return _counter


def _manufacturer_advertisement_payload(service_uuid: str) -> bytes:
    return b"BC" + uuid.UUID(service_uuid).bytes


class BlueZGattApplication(ServiceInterface):
    """DBus ObjectManager exposing BitChat GATT service and characteristic."""

    def __init__(
        self,
        service_path: str,
        service_uuid: str,
        characteristic_path: str,
        characteristic_uuid: str,
        characteristic: BlueZGattCharacteristic | None = None,
    ) -> None:
        super().__init__("org.freedesktop.DBus.ObjectManager")
        self.service_path = service_path
        self.service_uuid = service_uuid.lower()
        self.characteristic_path = characteristic_path
        self.characteristic_uuid = characteristic_uuid.lower()
        self.characteristic = characteristic

    def get_managed_objects(self) -> dict[str, dict[str, dict[str, Variant]]]:
        """Return raw managed objects dictionary for testing and inspection."""
        char_val = (
            self.characteristic.read_value() if self.characteristic is not None else b""
        )
        is_notifying = (
            self.characteristic.Notifying if self.characteristic is not None else False
        )
        return {
            self.service_path: {
                "org.bluez.GattService1": {
                    "UUID": Variant("s", self.service_uuid),
                    "Primary": Variant("b", True),
                    "Characteristics": Variant("ao", [self.characteristic_path]),
                }
            },
            self.characteristic_path: {
                "org.bluez.GattCharacteristic1": {
                    "UUID": Variant("s", self.characteristic_uuid),
                    "Service": Variant("o", self.service_path),
                    "Flags": Variant(
                        "as",
                        ["read", "write", "write-without-response", "notify"],
                    ),
                    "Value": Variant("ay", char_val),
                    "Notifying": Variant("b", is_notifying),
                }
            },
        }

    @method()
    def GetManagedObjects(self) -> ManagedObjectsDict:
        return self.get_managed_objects()


class BlueZGattService(ServiceInterface):
    """BlueZ GattService1 representing the BitChat primary service."""

    def __init__(self, service_uuid: str, characteristic_path: str) -> None:
        super().__init__("org.bluez.GattService1")
        self._uuid = service_uuid.lower()
        self._characteristic_path = characteristic_path

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> DBusStr:
        return self._uuid

    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> DBusBool:
        return True

    @dbus_property(access=PropertyAccess.READ)
    def Characteristics(self) -> ArrayOfObject:
        return [self._characteristic_path]


class BlueZGattCharacteristic(ServiceInterface):
    """BlueZ GattCharacteristic1 representing the BitChat characteristic."""

    def __init__(
        self,
        characteristic_uuid: str,
        service_path: str,
        on_data_received: Callable[[bytes, str], None] | None = None,
        on_client_subscribed: Callable[[str], None] | None = None,
        on_client_unsubscribed: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__("org.bluez.GattCharacteristic1")
        self._uuid = characteristic_uuid.lower()
        self._service_path = service_path
        self._value = b""
        self._notifying = False
        self.on_data_received = on_data_received
        self.on_client_subscribed = on_client_subscribed
        self.on_client_unsubscribed = on_client_unsubscribed

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> DBusStr:
        return self._uuid

    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> DBusObjectPath:
        return self._service_path

    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> ArrayOfString:
        return ["read", "write", "write-without-response", "notify"]

    @dbus_property(access=PropertyAccess.READ)
    def Value(self) -> DBusBytes:
        return self._value

    @dbus_property(access=PropertyAccess.READ)
    def Notifying(self) -> DBusBool:
        return self._notifying

    def read_value(self, offset: int = 0) -> bytes:
        """Read bytes from the characteristic value."""
        if offset < 0 or offset > len(self._value):
            raise DBusError("org.bluez.Error.InvalidOffset", "Offset out of bounds")
        return self._value[offset:]

    def write_value(
        self, data: bytes, client_id: str = "bluez_client", offset: int = 0
    ) -> None:
        """Process incoming write to the characteristic."""
        if offset < 0 or offset > len(self._value):
            raise DBusError("org.bluez.Error.InvalidOffset", "Offset out of bounds")
        if offset == 0:
            self._value = data
        else:
            self._value = self._value[:offset] + data

        if self.on_data_received is not None:
            try:
                self.on_data_received(data, client_id)
            except Exception as e:
                logger.warning("Error in on_data_received callback: %s", e)

    def start_notify(self) -> None:
        """Handle notification subscription."""
        self._notifying = True
        logger.info("BlueZ GATT characteristic notifications started")
        with contextlib.suppress(Exception):
            self.emit_properties_changed({"Notifying": True})
        if self.on_client_subscribed is not None:
            try:
                self.on_client_subscribed("bluez_client")
            except Exception as e:
                logger.warning("Error in on_client_subscribed callback: %s", e)

    def stop_notify(self) -> None:
        """Handle notification unsubscription."""
        self._notifying = False
        logger.info("BlueZ GATT characteristic notifications stopped")
        with contextlib.suppress(Exception):
            self.emit_properties_changed({"Notifying": False})
        if self.on_client_unsubscribed is not None:
            try:
                self.on_client_unsubscribed("bluez_client")
            except Exception as e:
                logger.warning("Error in on_client_unsubscribed callback: %s", e)

    @method()
    def ReadValue(self, options: DBusDict) -> DBusBytes:
        offset = 0
        if "offset" in options:
            off_var = options["offset"]
            raw_off = getattr(off_var, "value", off_var)
            if isinstance(raw_off, int | str | bytes):
                offset = int(raw_off)
        return self.read_value(offset)

    @method()
    def WriteValue(self, value: DBusBytes, options: DBusDict):
        offset = 0
        if "offset" in options:
            off_var = options["offset"]
            raw_off = getattr(off_var, "value", off_var)
            if isinstance(raw_off, int | str | bytes):
                offset = int(raw_off)

        client_id = "bluez_client"
        if "device" in options:
            dev_val = options["device"]
            dev_path = str(getattr(dev_val, "value", dev_val))
            dev_name = dev_path.split("/")[-1]
            if dev_name.startswith("dev_"):
                client_id = dev_name[4:].replace("_", ":")
            else:
                client_id = dev_name

        self.write_value(bytes(value), client_id, offset)

    @method()
    def StartNotify(self):
        self.start_notify()

    @method()
    def StopNotify(self):
        self.stop_notify()

    def send_notification(self, data: bytes) -> None:
        self._value = data
        self.emit_properties_changed({"Value": data})


class BlueZAdvertisement(ServiceInterface):
    """BlueZ LEAdvertisement1 for broadcasting BitChat peripheral presence."""

    def __init__(
        self,
        service_uuid: str,
        include_manufacturer_data: bool = True,
        local_name: str | None = None,
        on_released: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("org.bluez.LEAdvertisement1")
        self._service_uuid = service_uuid.lower()
        self._include_manufacturer_data = include_manufacturer_data
        self._local_name = local_name
        self._on_released = on_released
        self._released = False

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> DBusStr:
        return "peripheral"

    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> ArrayOfString:
        return [self._service_uuid]

    @dbus_property(access=PropertyAccess.READ)
    def Discoverable(self) -> DBusBool:
        return True

    @dbus_property(access=PropertyAccess.READ)
    def ManufacturerData(self) -> ManufacturerDict:
        if not self._include_manufacturer_data:
            return {}
        payload = _manufacturer_advertisement_payload(self._service_uuid)
        return {0xFFFF: Variant("ay", payload)}

    @dbus_property(access=PropertyAccess.READ)
    def Includes(self) -> ArrayOfString:
        return []

    @method()
    def Release(self):
        logger.info("BlueZ LEAdvertisement1 released by daemon")
        self._released = True
        if self._on_released is not None:
            try:
                self._on_released()
            except Exception as e:
                logger.warning("Error in advertisement on_released callback: %s", e)


class BlueZServerBackend:
    """Coordinates BlueZ GattManager1 and LEAdvertisingManager1 via D-Bus."""

    def __init__(
        self,
        service_uuid: str = BITCHAT_SERVICE_UUID,
        characteristic_uuid: str = BITCHAT_CHARACTERISTIC_UUID,
        on_data_received: Callable[[bytes, str], None] | None = None,
        on_client_subscribed: Callable[[str], None] | None = None,
        on_client_unsubscribed: Callable[[str], None] | None = None,
        on_advertising_state_changed: Callable[[bool], None] | None = None,
        bus: Any | None = None,
        adapter_path: str | None = None,
        peer_id: str = "",
        nickname: str = "",
    ) -> None:
        self.service_uuid = service_uuid.lower()
        self.characteristic_uuid = characteristic_uuid.lower()
        self.on_data_received = on_data_received
        self.on_client_subscribed = on_client_subscribed
        self.on_client_unsubscribed = on_client_unsubscribed
        self.on_advertising_state_changed = on_advertising_state_changed
        self._bus = bus
        self._bus_owned: bool = bus is None
        self._initial_adapter_path = adapter_path
        self._adapter_path = adapter_path
        self.peer_id = peer_id
        self.nickname = nickname

        self._app: BlueZGattApplication | None = None
        self._service: BlueZGattService | None = None
        self._characteristic: BlueZGattCharacteristic | None = None
        self._advertisement: BlueZAdvertisement | None = None

        self._app_path: str | None = None
        self._service_path: str | None = None
        self._char_path: str | None = None
        self._adv_path: str | None = None

        self._app_registered: bool = False
        self._adv_registered: bool = False
        self._is_advertising: bool = False
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    @property
    def is_advertising(self) -> bool:
        """Return True if LE advertising is active."""
        return self._is_advertising

    @property
    def has_provider(self) -> bool:
        """Return True if GATT application is currently registered."""
        return self._app_registered

    @property
    def has_publisher(self) -> bool:
        """Return True if LE advertisement is currently registered."""
        return self._adv_registered

    @property
    def last_error(self) -> str | None:
        """Return the last error string if startup failed."""
        return self._last_error

    def update_identity(self, peer_id: str, nickname: str) -> None:
        """Update advertised identity metadata."""
        self.peer_id = peer_id
        self.nickname = nickname

    def _on_advertisement_released(self) -> None:
        """Invoked when BlueZ daemon unexpectedly releases our advertisement."""
        logger.warning("BlueZ advertisement was released by system daemon")
        self._is_advertising = False
        self._adv_registered = False
        if self.on_advertising_state_changed is not None:
            try:
                self.on_advertising_state_changed(False)
            except Exception as e:
                logger.warning("Error in on_advertising_state_changed callback: %s", e)

    async def start(self) -> None:
        """Register GATT application and LE advertisement with BlueZ."""
        async with self._lock:
            if self._is_advertising:
                return

            if not HAS_DBUS_FAST:
                raise BLEError("dbus-fast is required for Linux BlueZ peripheral mode")

            self._last_error = None
            try:
                # 1. Connect message bus if not provided
                if self._bus is None:
                    try:
                        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                        self._bus_owned = True
                    except Exception as e:
                        raise BLEError(
                            f"Failed to connect to D-Bus system bus: {e}"
                        ) from e

                bus = self._bus

                # 2. Find and validate adapter
                adapter_path = await self._find_adapter(bus, self._adapter_path)
                self._adapter_path = adapter_path

                # 3. Setup unique D-Bus object paths
                obj_id = _next_id()
                base_path = f"/io/github/java_mx/bitchat/srv{obj_id}"
                self._app_path = f"{base_path}/app"
                self._service_path = f"{self._app_path}/service0"
                self._char_path = f"{self._service_path}/char0"
                self._adv_path = f"{base_path}/adv0"

                # 4. Create and export GATT characteristic, service, application
                self._characteristic = BlueZGattCharacteristic(
                    characteristic_uuid=self.characteristic_uuid,
                    service_path=self._service_path,
                    on_data_received=self.on_data_received,
                    on_client_subscribed=self.on_client_subscribed,
                    on_client_unsubscribed=self.on_client_unsubscribed,
                )
                self._service = BlueZGattService(
                    service_uuid=self.service_uuid,
                    characteristic_path=self._char_path,
                )
                self._app = BlueZGattApplication(
                    service_path=self._service_path,
                    service_uuid=self.service_uuid,
                    characteristic_path=self._char_path,
                    characteristic_uuid=self.characteristic_uuid,
                    characteristic=self._characteristic,
                )

                bus.export(self._app_path, self._app)
                bus.export(self._service_path, self._service)
                bus.export(self._char_path, self._characteristic)

                # 5. Register GATT application with GattManager1
                reply = await bus.call(
                    Message(
                        destination="org.bluez",
                        path=adapter_path,
                        interface="org.bluez.GattManager1",
                        member="RegisterApplication",
                        signature="oa{sv}",
                        body=[self._app_path, {}],
                    )
                )
                if reply.message_type == MessageType.ERROR:
                    raise BLEError(
                        "GattManager1.RegisterApplication failed: "
                        f"{reply.error_name}: {reply.body}"
                    )
                self._app_registered = True
                logger.info("BlueZ GATT application registered on %s", adapter_path)

                # 6. Create and export Advertisement
                self._advertisement = BlueZAdvertisement(
                    service_uuid=self.service_uuid,
                    include_manufacturer_data=True,
                    on_released=self._on_advertisement_released,
                )
                bus.export(self._adv_path, self._advertisement)

                # 7. Register Advertisement with LEAdvertisingManager1
                adv_reply = await bus.call(
                    Message(
                        destination="org.bluez",
                        path=adapter_path,
                        interface="org.bluez.LEAdvertisingManager1",
                        member="RegisterAdvertisement",
                        signature="oa{sv}",
                        body=[self._adv_path, {}],
                    )
                )
                if adv_reply.message_type == MessageType.ERROR:
                    logger.warning(
                        "Initial LE advertisement registration failed (%s: %s); "
                        "retrying without ManufacturerData",
                        adv_reply.error_name,
                        adv_reply.body,
                    )
                    with contextlib.suppress(Exception):
                        bus.unexport(self._adv_path)
                    self._advertisement = BlueZAdvertisement(
                        service_uuid=self.service_uuid,
                        include_manufacturer_data=False,
                        on_released=self._on_advertisement_released,
                    )
                    bus.export(self._adv_path, self._advertisement)
                    adv_reply = await bus.call(
                        Message(
                            destination="org.bluez",
                            path=adapter_path,
                            interface="org.bluez.LEAdvertisingManager1",
                            member="RegisterAdvertisement",
                            signature="oa{sv}",
                            body=[self._adv_path, {}],
                        )
                    )

                if adv_reply.message_type == MessageType.ERROR:
                    raise BLEError(
                        "LEAdvertisingManager1.RegisterAdvertisement failed: "
                        f"{adv_reply.error_name}: {adv_reply.body}"
                    )

                self._adv_registered = True
                self._is_advertising = True
                logger.info("BlueZ LE advertisement registered on %s", adapter_path)
            except asyncio.CancelledError:
                await self._cleanup()
                self._is_advertising = False
                raise
            except Exception as e:
                await self._cleanup()
                self._is_advertising = False
                self._last_error = str(e)
                raise

    async def _find_adapter(self, bus: Any, target_path: str | None = None) -> str:
        """Locate a powered Bluetooth adapter supporting GATT and advertising."""
        reply = await bus.call(
            Message(
                destination="org.bluez",
                path="/",
                interface="org.freedesktop.DBus.ObjectManager",
                member="GetManagedObjects",
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise BLEError(
                "Failed to query BlueZ managed objects: "
                f"{reply.error_name}: {reply.body}"
            )

        if not reply.body:
            raise BLEError("BlueZ returned empty managed objects")

        managed = reply.body[0]
        adapters: dict[str, dict[str, Any]] = {}
        for path, ifaces in managed.items():
            if "org.bluez.Adapter1" in ifaces:
                adapters[str(path)] = ifaces

        if not adapters:
            raise BLEError("No Bluetooth adapter found in BlueZ")

        def _is_powered(ifaces: dict[str, Any]) -> bool:
            props = ifaces.get("org.bluez.Adapter1", {})
            powered = props.get("Powered", True)
            return bool(getattr(powered, "value", powered))

        # If a specific target adapter path was requested, validate it directly
        if target_path is not None:
            if target_path not in adapters:
                if f"/org/bluez/{target_path}" in adapters:
                    target_path = f"/org/bluez/{target_path}"
                else:
                    raise BLEError(
                        f"Bluetooth adapter {target_path} not found in BlueZ"
                    )
            ifaces = adapters[target_path]
            if not _is_powered(ifaces):
                raise BLEError(f"Bluetooth adapter {target_path} is powered off")
            if "org.bluez.GattManager1" not in ifaces:
                raise BLEError(
                    f"Bluetooth adapter {target_path} does not support GattManager1"
                )
            if "org.bluez.LEAdvertisingManager1" not in ifaces:
                raise BLEError(
                    f"Bluetooth adapter {target_path} does not support "
                    "LEAdvertisingManager1"
                )
            return target_path

        # Find powered adapters supporting both GattManager1 and LEAdvertisingManager1
        fully_capable: list[str] = []
        powered_adapters: list[str] = []
        for path, ifaces in adapters.items():
            if _is_powered(ifaces):
                powered_adapters.append(path)
                if (
                    "org.bluez.GattManager1" in ifaces
                    and "org.bluez.LEAdvertisingManager1" in ifaces
                ):
                    fully_capable.append(path)

        fully_capable.sort()
        if fully_capable:
            return fully_capable[0]

        # If powered adapters exist but lack capabilities, report specific deficiency
        powered_adapters.sort()
        if powered_adapters:
            first_powered = powered_adapters[0]
            ifaces = adapters[first_powered]
            if "org.bluez.GattManager1" not in ifaces:
                raise BLEError(
                    f"Bluetooth adapter {first_powered} does not support GattManager1"
                )
            if "org.bluez.LEAdvertisingManager1" not in ifaces:
                raise BLEError(
                    f"Bluetooth adapter {first_powered} does not support "
                    "LEAdvertisingManager1"
                )
            return first_powered

        # No powered adapters; report first adapter is powered off
        first_path = sorted(adapters.keys())[0]
        raise BLEError(f"Bluetooth adapter {first_path} is powered off")

    async def stop(self) -> None:
        """Stop advertising and clean up all D-Bus objects and registrations."""
        async with self._lock:
            await self._cleanup()
            self._is_advertising = False
            logger.info("BlueZ BLEServer backend stopped")

    async def _cleanup(self) -> None:
        """Unregister from BlueZ and unexport objects."""
        bus = self._bus
        adapter_path = self._adapter_path

        if bus is not None and adapter_path is not None:
            if self._adv_registered and self._adv_path:
                with contextlib.suppress(Exception):
                    await bus.call(
                        Message(
                            destination="org.bluez",
                            path=adapter_path,
                            interface="org.bluez.LEAdvertisingManager1",
                            member="UnregisterAdvertisement",
                            signature="o",
                            body=[self._adv_path],
                        )
                    )
            self._adv_registered = False

            if self._app_registered and self._app_path:
                with contextlib.suppress(Exception):
                    await bus.call(
                        Message(
                            destination="org.bluez",
                            path=adapter_path,
                            interface="org.bluez.GattManager1",
                            member="UnregisterApplication",
                            signature="o",
                            body=[self._app_path],
                        )
                    )
            self._app_registered = False

        if bus is not None:
            for p in (
                self._adv_path,
                self._char_path,
                self._service_path,
                self._app_path,
            ):
                if p:
                    with contextlib.suppress(Exception):
                        bus.unexport(p)

        if self._bus_owned and self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.disconnect()
            self._bus = None

        if self._initial_adapter_path is None:
            self._adapter_path = None

        self._app = None
        self._service = None
        self._characteristic = None
        self._advertisement = None
        self._app_path = None
        self._service_path = None
        self._char_path = None
        self._adv_path = None

    async def send_notification(
        self, data: bytes, client_id: str | None = None
    ) -> None:
        """Emit notification for the GATT characteristic."""
        if not self._is_advertising or self._characteristic is None:
            raise BLEError("Cannot send notification: BlueZ BLEServer is not active")
        try:
            self._characteristic.send_notification(data)
        except Exception as e:
            raise BLEError(f"Failed to notify Linux BLE characteristic: {e}") from e
