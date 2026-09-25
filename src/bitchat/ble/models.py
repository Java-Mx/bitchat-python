"""Models and state enumerations for the BLE transport layer."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class BLEConnectionState(StrEnum):
    """Lifecycle connection state of a BLE peer connection."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCOVERING_GATT = "discovering_gatt"
    SUBSCRIBING = "subscribing"
    READY = "ready"
    DISCONNECTING = "disconnecting"


class BLEState(StrEnum):
    """Overall operational state of the local BLE subsystem."""

    OFFLINE = "offline"
    CHECKING = "checking"
    BLUETOOTH_UNAVAILABLE = "unavailable"
    BLUETOOTH_DISABLED = "disabled"
    READY = "ready"
    SCANNING = "scanning"
    PEER_FOUND = "peer_found"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class DiscoveredPeer:
    """Represents a discovered BitChat BLE peripheral."""

    address: str
    name: str | None = None
    rssi: int = -100
    service_uuids: tuple[str, ...] = field(default_factory=tuple)
    last_seen: float = field(default_factory=time.time)
    peer_id: str | None = None
    nickname: str | None = None

    def is_expired(self, ttl: float = 30.0) -> bool:
        """Return True if this peer advertisement record has expired."""
        return (time.time() - self.last_seen) > ttl
