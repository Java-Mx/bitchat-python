"""Peer model representing a participant in the BitChat mesh."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PeerConnectionState(StrEnum):
    """Connection state of a peer, matching the BitChat protocol specification."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"


@dataclass
class Peer:
    """Represents a remote peer in the network.

    Independent of UI and BLE transport layers.
    """

    peer_id: str
    nickname: str | None = None
    fingerprint: str | None = None
    last_seen: datetime | None = None
    connection_state: PeerConnectionState = PeerConnectionState.DISCONNECTED
    transport: str = "bluetooth"
    address: str = ""
    ssid: str | None = None

    @property
    def is_online(self) -> bool:
        """Return True if the peer is currently reachable (not disconnected)."""
        return self.connection_state != PeerConnectionState.DISCONNECTED

    @property
    def display_name(self) -> str:
        """Return the user's nickname if available, falling back to peer_id."""
        return self.nickname if self.nickname else self.peer_id
