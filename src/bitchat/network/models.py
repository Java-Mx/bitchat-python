"""Data models and packet schemas for LAN/Wi-Fi transport."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_DISCOVERY_PACKET_SIZE: int = 1024


@dataclass(frozen=True)
class NetworkInfo:
    """Represents real local network adapter, IP, and SSID telemetry."""

    status: str = "Disconnected"  # "Connected", "Disconnected"
    interface: str = "Unavailable"  # "Wi-Fi", "Ethernet", "Loopback", "Unavailable"
    ssid: str = "unavailable"
    local_ip: str = ""
    listening_address: str = "0.0.0.0"
    listening_port: int = 0
    discovery_active: bool = False

    @property
    def is_connected(self) -> bool:
        return (
            self.status == "Connected"
            and bool(self.local_ip)
            and not self.local_ip.startswith("127.")
            and self.local_ip not in ("0.0.0.0", "::1")
        )


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

            return cls(
                peer_id=peer_id,
                nickname=nickname,
                port=port,
                ssid=ssid,
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
