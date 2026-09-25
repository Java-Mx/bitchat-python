"""BitChat LAN and local Wi-Fi transport package."""

from bitchat.network.adapter import (
    NetworkAdapterManager,
    detect_network_info,
    get_local_ip,
)
from bitchat.network.connection import LANConnection
from bitchat.network.discovery import LANDiscovery
from bitchat.network.framing import FramingError, StreamFramer, encode_frame
from bitchat.network.models import DiscoveryPacket, LANDiscoveredPeer, NetworkInfo
from bitchat.network.server import LANServer
from bitchat.network.transport import LANTransport

__all__ = [
    "DiscoveryPacket",
    "FramingError",
    "LANConnection",
    "LANDiscoveredPeer",
    "LANDiscovery",
    "LANServer",
    "LANTransport",
    "NetworkAdapterManager",
    "NetworkInfo",
    "StreamFramer",
    "detect_network_info",
    "encode_frame",
    "get_local_ip",
]
