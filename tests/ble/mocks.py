"""Mock Bleak interfaces for hardware-independent testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    BITCHAT_SERVICE_UUID,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass
class MockBLEDevice:
    address: str
    name: str | None = "BitChat Node"
    rssi: int = -55
    details: Any = None


@dataclass
class MockAdvertisementData:
    local_name: str | None = "BitChat Node"
    service_uuids: list[str] = field(
        default_factory=lambda: [BITCHAT_SERVICE_UUID.lower()]
    )
    rssi: int = -55


@dataclass
class MockBleakCharacteristic:
    uuid: str = BITCHAT_CHARACTERISTIC_UUID.lower()
    properties: list[str] = field(
        default_factory=lambda: ["write-without-response", "notify"]
    )
    handle: int = 42


@dataclass
class MockBleakService:
    uuid: str = BITCHAT_SERVICE_UUID.lower()
    characteristics: list[MockBleakCharacteristic] = field(
        default_factory=lambda: [MockBleakCharacteristic()]
    )


class MockBleakScanner:
    """Mock BleakScanner recording start/stop and simulating detections."""

    def __init__(
        self,
        detection_callback: Callable[[MockBLEDevice, MockAdvertisementData], None],
        service_uuids: list[str],
    ) -> None:
        self.detection_callback = detection_callback
        self.service_uuids = [u.lower() for u in service_uuids]
        self.is_started: bool = False
        self.should_fail_start: bool = False

    async def start(self) -> None:
        if self.should_fail_start:
            raise RuntimeError("Bluetooth adapter offline")
        self.is_started = True

    async def stop(self) -> None:
        self.is_started = False

    def emit_device(
        self,
        address: str = "AA:BB:CC:DD:EE:01",
        name: str | None = "BitChat Node",
        service_uuids: list[str] | None = None,
        rssi: int = -60,
    ) -> None:
        if service_uuids is None:
            service_uuids = [BITCHAT_SERVICE_UUID.lower()]
        device = MockBLEDevice(address=address, name=name, rssi=rssi)
        adv = MockAdvertisementData(
            local_name=name, service_uuids=service_uuids, rssi=rssi
        )
        self.detection_callback(device, adv)


class MockBleakClient:
    """Mock BleakClient simulating connections, GATT, and notifications."""

    def __init__(
        self,
        address: str,
        disconnected_callback: Callable[[Any], None] | None = None,
        services: list[MockBleakService] | None = None,
    ) -> None:
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.services = services or [MockBleakService()]
        self.is_connected: bool = False
        self.should_fail_connect: bool = False
        self.should_fail_write: bool = False
        self.written_chunks: list[tuple[str, bytes, bool]] = []
        self.subscribed_callback: Callable[[Any, bytearray], None] | None = None
        self.subscribed_char: Any | None = None

    async def connect(self, timeout: float = 10.0) -> bool:
        if self.should_fail_connect:
            return False
        self.is_connected = True
        return True

    async def disconnect(self) -> bool:
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)
        return True

    async def get_services(self) -> list[MockBleakService]:
        return self.services

    async def start_notify(
        self,
        char: Any,
        callback: Callable[[Any, bytearray], None],
    ) -> None:
        self.subscribed_char = char
        self.subscribed_callback = callback

    async def stop_notify(self, char: Any) -> None:
        if self.subscribed_char == char:
            self.subscribed_char = None
            self.subscribed_callback = None

    async def write_gatt_char(
        self,
        char: Any,
        data: bytes,
        response: bool = False,
    ) -> None:
        if not self.is_connected:
            raise RuntimeError("Client not connected")
        if self.should_fail_write:
            raise RuntimeError("Write failed")
        char_uuid = getattr(char, "uuid", str(char))
        self.written_chunks.append((char_uuid, data, response))

    def emit_notification(self, data: bytes) -> None:
        if self.subscribed_callback and self.subscribed_char:
            self.subscribed_callback(self.subscribed_char, bytearray(data))

    def trigger_unexpected_disconnect(self) -> None:
        self.is_connected = False
        if self.disconnected_callback:
            self.disconnected_callback(self)
