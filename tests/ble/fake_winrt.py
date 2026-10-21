"""In-memory fake of the WinRT BLE surface used by BitChat.

Lets the real ``BLEServer`` Windows code path (GATT provider, characteristic,
advertisement publisher, event handlers) run on any host so Windows control flow
is exercised through mocked platform APIs instead of an injected test backend.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

# GattServiceProviderAdvertisementStatus / BluetoothLEAdvertisementPublisherStatus
STATUS_CREATED = 0
STATUS_STOPPED = 1
STATUS_STARTED = 2
STATUS_ABORTED = 3


class FakeCharacteristic:
    def __init__(self) -> None:
        self.write_handlers: dict[int, Any] = {}
        self.subscriber_handlers: dict[int, Any] = {}
        self._next_token = 1
        self.notifications: list[Any] = []

    def add_write_requested(self, handler: Any) -> int:
        token = self._next_token
        self._next_token += 1
        self.write_handlers[token] = handler
        return token

    def remove_write_requested(self, token: int) -> None:
        del self.write_handlers[token]

    def add_subscribed_clients_changed(self, handler: Any) -> int:
        token = self._next_token
        self._next_token += 1
        self.subscriber_handlers[token] = handler
        return token

    def remove_subscribed_clients_changed(self, token: int) -> None:
        del self.subscriber_handlers[token]

    async def notify_value_async(self, buf: Any) -> None:
        self.notifications.append(buf)

    @property
    def handler_count(self) -> int:
        return len(self.write_handlers) + len(self.subscriber_handlers)


class FakeService:
    def __init__(self, owner: FakeWinRT) -> None:
        self._owner = owner

    async def create_characteristic_async(self, uuid: Any, params: Any) -> Any:
        if self._owner.characteristic_error:
            return types.SimpleNamespace(
                error=self._owner.characteristic_error, characteristic=None
            )
        char = FakeCharacteristic()
        self._owner.characteristics.append(char)
        return types.SimpleNamespace(error=0, characteristic=char)


class FakeProvider:
    def __init__(self, owner: FakeWinRT) -> None:
        self._owner = owner
        self.service = FakeService(owner)
        self.advertisement_status = STATUS_CREATED
        self.advertising = False

    def start_advertising_with_parameters(self, params: Any) -> None:
        self.advertising = True
        self.advertisement_status = self._owner.provider_status

    def stop_advertising(self) -> None:
        self.advertising = False
        self.advertisement_status = STATUS_STOPPED


class FakePublisher:
    def __init__(self, owner: FakeWinRT) -> None:
        self._owner = owner
        self.advertisement = types.SimpleNamespace(manufacturer_data=[])
        self.status = STATUS_CREATED
        self.running = False

    def start(self) -> None:
        self.running = True
        self.status = self._owner.publisher_status

    def stop(self) -> None:
        self.running = False
        self.status = STATUS_STOPPED


@dataclass
class FakeWinRT:
    """Configurable fake; call :meth:`install` to expose it as ``winrt.*``."""

    provider_status: int = STATUS_STARTED
    publisher_status: int = STATUS_STARTED
    create_error: int = 0
    characteristic_error: int = 0
    providers: list[FakeProvider] = field(default_factory=list)
    publishers: list[FakePublisher] = field(default_factory=list)
    characteristics: list[FakeCharacteristic] = field(default_factory=list)

    @property
    def active_handlers(self) -> int:
        return sum(c.handler_count for c in self.characteristics)

    @property
    def advertising_providers(self) -> int:
        return sum(1 for p in self.providers if p.advertising)

    @property
    def running_publishers(self) -> int:
        return sum(1 for p in self.publishers if p.running)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> FakeWinRT:
        owner = self

        class GattServiceProvider:
            @staticmethod
            async def create_async(srv_uuid: Any) -> Any:
                if owner.create_error:
                    return types.SimpleNamespace(
                        error=owner.create_error, service_provider=None
                    )
                provider = FakeProvider(owner)
                owner.providers.append(provider)
                return types.SimpleNamespace(error=0, service_provider=provider)

        class GattProps(int):
            pass

        class GattCharacteristicProperties:
            WRITE_WITHOUT_RESPONSE = GattProps(4)
            WRITE = GattProps(8)
            NOTIFY = GattProps(16)

        class Params:
            pass

        class AdvPublisher(FakePublisher):
            def __init__(self) -> None:
                super().__init__(owner)
                owner.publishers.append(self)

        class ManufacturerData:
            def __init__(self) -> None:
                self.company_id: int | None = None
                self.data: Any = None

        class DataWriter:
            def write_bytes(self, data: bytes) -> None:
                self.data = data

            def detach_buffer(self) -> Any:
                return getattr(self, "data", b"")

        def module(name: str, **attrs: Any) -> Any:
            mod: Any = types.ModuleType(name)
            mod.__path__ = []
            for key, value in attrs.items():
                setattr(mod, key, value)
            return mod

        gatt = module(
            "winrt.windows.devices.bluetooth.genericattributeprofile",
            GattServiceProvider=GattServiceProvider,
            GattServiceProviderAdvertisingParameters=Params,
            GattLocalCharacteristicParameters=Params,
            GattCharacteristicProperties=GattCharacteristicProperties,
        )
        adv = module(
            "winrt.windows.devices.bluetooth.advertisement",
            BluetoothLEAdvertisementPublisher=AdvPublisher,
            BluetoothLEManufacturerData=ManufacturerData,
        )
        bluetooth = module(
            "winrt.windows.devices.bluetooth",
            advertisement=adv,
            genericattributeprofile=gatt,
        )
        radios = module("winrt.windows.devices.radios")
        devices = module("winrt.windows.devices", bluetooth=bluetooth, radios=radios)
        streams = module("winrt.windows.storage.streams", DataWriter=DataWriter)
        storage = module("winrt.windows.storage", streams=streams)
        windows = module("winrt.windows", devices=devices, storage=storage)
        root = module("winrt", windows=windows)

        for mod in (
            root,
            windows,
            devices,
            bluetooth,
            adv,
            gatt,
            radios,
            storage,
            streams,
        ):
            monkeypatch.setitem(sys.modules, mod.__name__, mod)
        return self
