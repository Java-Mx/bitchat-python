"""Data models and packet schemas for LAN/Wi-Fi transport."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_DISCOVERY_PACKET_SIZE: int = 1024


@dataclass(frozen=True)
class NetworkInterfaceInfo:
    """Read-only details for one operating-system network interface."""

    name: str
    description: str = ""
    kind: str = "Other"
    operational_state: str = "Unknown"
    ipv4_addresses: tuple[str, ...] = ()
    ipv6_addresses: tuple[str, ...] = ()
    subnet_prefixes: tuple[int, ...] = ()
    gateways: tuple[str, ...] = ()
    dns_servers: tuple[str, ...] = ()
    ssid: str | None = None
    connection_name: str | None = None
    interface_id: str | None = None
    interface_index: int | None = None
    signal_strength_percent: int | None = None
    signal_strength_dbm: int | None = None
    link_speed: str | None = None
    default_route: bool = False


@dataclass(frozen=True)
class NetworkInfo:
    """Operating-system network state, independent of BitChat transport state."""

    status: str = "Disconnected"  # "Connected", "Disconnected", "Unknown"
    interface: str = "Unavailable"  # Connection type: Wi-Fi, Ethernet, Other
    ssid: str = "unavailable"
    local_ip: str = ""
    listening_address: str = "0.0.0.0"
    listening_port: int = 0
    discovery_active: bool = False
    interface_name: str = "Unavailable"
    interface_state: str = "Unknown"
    ipv4_addresses: tuple[str, ...] = ()
    ipv6_addresses: tuple[str, ...] = ()
    subnet_prefixes: tuple[int, ...] = ()
    default_gateway: str = "Unavailable"
    dns_servers: tuple[str, ...] = ()
    default_route_interface: str = "Unavailable"
    connection_name: str = "Unavailable"
    network_name_reason: str | None = None
    interface_description: str = "Unavailable"
    interface_id: str | None = None
    interface_index: int | None = None
    signal_strength_percent: int | None = None
    signal_strength_dbm: int | None = None
    interfaces: tuple[NetworkInterfaceInfo, ...] = ()
    discovery_error: str | None = None
    collected_at: float | None = None
    provider_backend: str = "unknown"
    field_availability: tuple[tuple[str, str], ...] = ()
    collection_errors: tuple[str, ...] = ()

    @property
    def cache_age_seconds(self) -> float | None:
        """Return the snapshot age, when its collection timestamp is known."""
        return max(0.0, time.time() - self.collected_at) if self.collected_at else None

    @property
    def is_configured(self) -> bool:
        """Whether a valid network interface has been identified and configured."""
        return bool(self.interface_name and self.interface_name != "Unavailable")

    @property
    def is_detected(self) -> bool:
        """Whether host network interfaces were successfully detected by the OS."""
        return bool(self.interfaces)

    @property
    def is_administratively_enabled(self) -> bool:
        """Whether any detected network interface is administratively enabled."""
        if self.interfaces:
            disabled = {"disabled", "administratively down"}
            return any(
                item.operational_state.lower() not in disabled
                for item in self.interfaces
            )
        return self.status != "Disabled"

    @property
    def is_operational(self) -> bool:
        """Whether the selected interface is in an operational UP / Connected state."""
        st = self.interface_state.lower()
        if st in {"up", "connected"}:
            return True
        if st in {
            "down",
            "disconnected",
            "disabled",
            "administratively down",
            "no carrier",
        }:
            return False
        return self.status == "Connected"

    @property
    def is_ip_assigned(self) -> bool:
        """Whether the selected interface has at least one valid IPv4/IPv6 assigned."""
        return bool(self.local_ip or self.ipv4_addresses or self.ipv6_addresses)

    @property
    def is_discovery_active(self) -> bool:
        """Whether UDP peer discovery is actively running."""
        return bool(self.discovery_active)

    @property
    def is_listener_bound(self) -> bool:
        """Whether the TCP peer transport listener socket is bound to a valid port."""
        return bool(self.listening_port > 0)

    @property
    def is_connected(self) -> bool:
        """Whether an operational interface has a usable assigned address."""
        return (
            self.status == "Connected" and self.is_operational and self.is_ip_assigned
        )

    @property
    def has_ipv4(self) -> bool:
        return bool(self.local_ip or self.ipv4_addresses)


@dataclass(frozen=True)
class DiscoveryPacket:
    """Compact UDP broadcast beacon packet identifying a local BitChat node."""

    peer_id: str
    nickname: str
    port: int
    ssid: str = ""
    protocol: str = "bitchat"
    version: int = 1
    transport: str = "lan"
    instance_id: str = ""

    def to_bytes(self) -> bytes:
        """Serialize discovery packet to compact UTF-8 JSON bytes."""
        payload = {
            "protocol": self.protocol,
            "version": self.version,
            "transport": self.transport,
            "peer_id": self.peer_id,
            "nickname": self.nickname[:32],
            "port": self.port,
            "ssid": self.ssid[:64] if self.ssid else "",
            "instance_id": self.instance_id[:32] if self.instance_id else "",
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if len(raw) > MAX_DISCOVERY_PACKET_SIZE:
            raise ValueError(
                f"Discovery packet exceeds max size {MAX_DISCOVERY_PACKET_SIZE} bytes"
            )
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> DiscoveryPacket | None:
        """Validate and parse incoming raw UDP bytes into DiscoveryPacket."""
        if not raw or len(raw) > MAX_DISCOVERY_PACKET_SIZE:
            return None

        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                return None

            if (
                data.get("protocol") != "bitchat"
                or data.get("version") != 1
                or data.get("transport") != "lan"
            ):
                return None

            peer_id = str(data.get("peer_id", "")).strip().lower()
            if not peer_id or len(peer_id) < 8 or len(peer_id) > 64:
                return None
            # Validate hex characters
            int(peer_id, 16)

            port = int(data.get("port", 0))
            if port < 1024 or port > 65535:
                return None

            nickname = str(data.get("nickname", "Anonymous")).strip()[:32]
            ssid = str(data.get("ssid", "")).strip()[:64]
            instance_id = str(data.get("instance_id", "")).strip()[:32]

            return cls(
                peer_id=peer_id,
                nickname=nickname,
                port=port,
                ssid=ssid,
                instance_id=instance_id,
            )
        except Exception:
            return None


@dataclass
class LANDiscoveredPeer:
    """Record of a discovered LAN BitChat peer with network metadata and TTL."""

    address: str  # Format: "ip:port"
    ip: str
    port: int
    peer_id: str
    nickname: str
    ssid: str = ""
    instance_id: str = ""
    transport: str = "lan"
    last_seen: float = field(default_factory=time.time)

    @property
    def name(self) -> str:
        return self.nickname if self.nickname else f"Peer {self.peer_id[:8]}"

    def is_expired(self, ttl: float = 30.0, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        return (current - self.last_seen) > ttl

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
