"""Abstract transport layer interface and common transport models."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.protocol.packet import BitchatPacket


class TransportType(StrEnum):
    """Supported network and physical transport mediums."""

    BLUETOOTH = "bluetooth"
    LAN = "lan"
    OFFLINE = "offline"


def normalize_transport_name(value: str) -> str | None:
    """Return the canonical transport name for a supported command or alias."""
    aliases = {
        "bluetooth": "bluetooth",
        "ble": "bluetooth",
        "bt": "bluetooth",
        "lan": "lan",
        "wifi": "lan",
        "wi-fi": "lan",
        "ethernet": "lan",
        "offline": "offline",
        "off": "offline",
        "none": "offline",
    }
    return aliases.get(value.strip().casefold())


@dataclass(frozen=True)
class TransportError:
    """A failure tied to the transport and operation that produced it."""

    transport: TransportType
    operation: str
    message: str
    stage: str | None = None
    occurred_at: float = field(default_factory=time.time)
    original_error: str | None = None
    native_error_code: int | None = None
    hresult: str | None = None
    operation_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class TransportWarning:
    """A non-fatal diagnostic tied to its originating transport operation."""

    transport: TransportType
    operation: str
    message: str
    stage: str | None = None
    occurred_at: float = field(default_factory=time.time)
    original_error: str | None = None
    native_error_code: int | None = None
    hresult: str | None = None
    operation_id: str = field(default_factory=lambda: uuid4().hex)


def format_connection_failure(exc: BaseException) -> str:
    """Map a connection exception to a bounded, user-visible terminal reason."""
    if isinstance(exc, TimeoutError):
        return "Connection failed: timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "Connection failed: refused"

    errno = getattr(exc, "errno", None)
    if errno in {111, 10061}:
        return "Connection failed: refused"
    if errno in {101, 113, 10051, 10065}:
        return "Connection failed: unreachable"
    if errno in {110, 10060}:
        return "Connection failed: timeout"

    text = str(exc).lower()
    if "timed out" in text or "timeout" in text:
        return "Connection failed: timeout"
    if "refused" in text:
        return "Connection failed: refused"
    if "unreachable" in text or "no route" in text:
        return "Connection failed: unreachable"
    if "unavailable" in text or "disabled" in text or "offline" in text:
        return "Connection failed: transport unavailable"
    return f"Connection failed: {exc}"


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
        self.on_error: Callable[[TransportError], None] | None = None
        self.on_warning: Callable[[TransportWarning], None] | None = None
        self.last_error: TransportError | None = None

    def report_error(
        self,
        operation: str,
        message: str,
        *,
        stage: str | None = None,
        original_error: BaseException | None = None,
        native_error_code: int | None = None,
        hresult: str | None = None,
    ) -> TransportError:
        """Record and emit a transport-scoped error event."""
        event = TransportError(
            transport=self.transport_type,
            operation=operation,
            message=message,
            stage=stage,
            original_error=repr(original_error) if original_error else None,
            native_error_code=native_error_code,
            hresult=hresult,
        )
        self.last_error = event
        if self.on_error:
            self.on_error(event)
        return event

    def report_warning(
        self,
        operation: str,
        message: str,
        *,
        stage: str | None = None,
        original_error: BaseException | None = None,
        native_error_code: int | None = None,
        hresult: str | None = None,
    ) -> TransportWarning:
        """Emit a transport-scoped non-fatal warning event."""
        event = TransportWarning(
            transport=self.transport_type,
            operation=operation,
            message=message,
            stage=stage,
            original_error=repr(original_error) if original_error else None,
            native_error_code=native_error_code,
            hresult=hresult,
        )
        if self.on_warning:
            self.on_warning(event)
        return event

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

    def is_available(self) -> bool:
        """Return True if the underlying transport medium is available."""
        return self.state not in (TransportState.UNAVAILABLE, TransportState.DISABLED)

    def set_offline(self, offline: bool) -> None:
        """Enforce or release offline mode constraint."""
        _ = offline


class OfflineTransport(BaseTransport):
    """Authoritative null transport for offline mode.

    Strictly guarantees no socket binding, no scanning, no advertising,
    no connections, and no network packet transmissions.
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = TransportState.OFFLINE
        self.offline_mode = True

    @property
    def transport_type(self) -> TransportType:
        return TransportType.OFFLINE

    @property
    def state(self) -> TransportState:
        return TransportState.OFFLINE

    @property
    def is_running(self) -> bool:
        return False

    @property
    def connected_peers(self) -> list[str]:
        return []

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return {}

    @property
    def is_scanning(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True

    def set_offline(self, offline: bool) -> None:
        self.offline_mode = offline

    async def start(self) -> None:
        """Offline transport does not start any sockets or network services."""
        self._state = TransportState.OFFLINE

    async def stop(self) -> None:
        """Cleanly confirm offline state."""
        self._state = TransportState.OFFLINE

    async def start_discovery(self) -> None:
        raise RuntimeError("Cannot start discovery: offline mode is active")

    async def stop_discovery(self) -> None:
        pass

    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        raise RuntimeError("Cannot connect to peer: offline mode is active")

    async def disconnect_peer(self, address: str) -> None:
        pass

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        raise RuntimeError("Cannot transmit packet: offline mode is active")

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        pass

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        pass

    def resolve_peer_id_to_address(self, target: str) -> str | None:
        return None

    def get_telemetry(self) -> dict[str, Any]:
        return {
            "transport": "offline",
            "state": "offline",
            "offline_mode": True,
            "connected_peers_count": 0,
            "discovered_peers_count": 0,
        }
