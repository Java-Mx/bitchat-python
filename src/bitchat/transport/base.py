"""Abstract transport layer interface and common transport models."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.protocol.packet import BitchatPacket


class TransportType(StrEnum):
    """Supported network and physical transport mediums."""

    BLUETOOTH = "bluetooth"
    LAN = "lan"


class TransportState(StrEnum):
    """High-level transport lifecycle and connectivity states."""

    OFFLINE = "offline"
    CHECKING = "checking"
    READY = "ready"
    SCANNING = "scanning"
    PEER_FOUND = "peer_found"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass
class TransportPeer:
    """Represents a remote endpoint discovered or connected via a transport."""

    address: str
    name: str | None = None
    peer_id: str | None = None
    transport: TransportType = TransportType.BLUETOOTH
    rssi: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)

    def is_expired(self, ttl: float = 30.0, now: float | None = None) -> bool:
        """Return True if peer hasn't been seen within TTL seconds."""
        current = time.time() if now is None else now
        return (current - self.last_seen) > ttl


class BaseTransport(ABC):
    """Abstract interface defining required operations for all BitChat transports.

    Decouples the application, protocol, encryption, and mesh routing layers
    from specific network or physical mediums (e.g. Bluetooth LE, LAN/Wi-Fi).
    """

    def __init__(self) -> None:
        self.on_packet_received: Callable[[BitchatPacket, str], None] | None = None
        self.on_peer_discovered: Callable[[Any], None] | None = None
        self.on_peer_connected: Callable[[str], None] | None = None
        self.on_peer_disconnected: Callable[[str], None] | None = None
        self.on_state_changed: Callable[[TransportState], None] | None = None
        self.on_error: Callable[[str], None] | None = None

    @property
    @abstractmethod
    def transport_type(self) -> TransportType:
        """Return the transport type identifier."""

    @property
    @abstractmethod
    def state(self) -> TransportState:
        """Return the current lifecycle state of the transport."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the transport is actively running."""

    @property
    @abstractmethod
    def connected_peers(self) -> list[str]:
        """Return list of addresses of currently connected peers."""

    @property
    @abstractmethod
    def discovered_peers(self) -> dict[str, Any]:
        """Return mapping of discovered peer addresses to their metadata records."""

    @abstractmethod
    async def start(self) -> None:
        """Initialize and start transport services (listeners, adapters, beacons)."""

    @abstractmethod
    async def stop(self) -> None:
        """Shut down transport services and disconnect all peers cleanly."""

    @abstractmethod
    async def start_discovery(self) -> None:
        """Start actively scanning or listening for peer discovery beacons."""

    @abstractmethod
    async def stop_discovery(self) -> None:
        """Stop peer discovery scanning/listening."""

    @abstractmethod
    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        """Establish a connection to the specified peer address."""

    @abstractmethod
    async def disconnect_peer(self, address: str) -> None:
        """Disconnect and clean up resources for a specific peer address."""

    @abstractmethod
    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        """Send a packet directly to a specific connected peer."""

    @abstractmethod
    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        """Broadcast a packet to all active peers, optionally excluding one."""

    @abstractmethod
    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        """Update local identity advertised by this transport."""

    @abstractmethod
    def resolve_peer_id_to_address(self, target: str) -> str | None:
        """Resolve a peer ID prefix, nickname, or address to an endpoint."""

    @abstractmethod
    def get_telemetry(self) -> dict[str, Any]:
        """Return comprehensive diagnostics telemetry for status reporting."""
