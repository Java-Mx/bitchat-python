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


@dataclass(frozen=True)
class DiscoveredPeer:
    """Represents a discovered BitChat BLE peripheral."""

    address: str
    name: str | None = None
    rssi: int = -100
    service_uuids: tuple[str, ...] = field(default_factory=tuple)
    last_seen: float = field(default_factory=time.time)
