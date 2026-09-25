"""Unit tests for LAN discovery protocol, packet schema, rate limiting,
and TTL pruning.
"""

from __future__ import annotations

import json
import time

from bitchat.network.discovery import MAX_DISCOVERY_RATE_PER_IP, LANDiscovery
from bitchat.network.models import (
    MAX_DISCOVERY_PACKET_SIZE,
    DiscoveryPacket,
    LANDiscoveredPeer,
)


def test_discovery_packet_serialization() -> None:
    pkt = DiscoveryPacket(
        peer_id="abcdef0123456789",
        nickname="AliceNode",
        port=41235,
        ssid="TestWiFi",
    )
    raw = pkt.to_bytes()
    assert len(raw) <= MAX_DISCOVERY_PACKET_SIZE

    parsed = DiscoveryPacket.from_bytes(raw)
    assert parsed is not None
    assert parsed.peer_id == "abcdef0123456789"
    assert parsed.nickname == "AliceNode"
    assert parsed.port == 41235
    assert parsed.ssid == "TestWiFi"
    assert parsed.transport == "lan"


def test_discovery_packet_rejection_invalid_schema() -> None:
    # 1. Empty bytes
    assert DiscoveryPacket.from_bytes(b"") is None

    # 2. Oversized bytes
    assert DiscoveryPacket.from_bytes(b"X" * (MAX_DISCOVERY_PACKET_SIZE + 1)) is None

    # 3. Not JSON
    assert DiscoveryPacket.from_bytes(b"Not a json string") is None

    # 4. Wrong protocol
    bad_proto = json.dumps(
        {
            "protocol": "other",
            "version": 1,
            "transport": "lan",
            "peer_id": "abcdef0123456789",
            "nickname": "Test",
            "port": 41235,
        }
    ).encode()
    assert DiscoveryPacket.from_bytes(bad_proto) is None

    # 5. Invalid port (< 1024 or > 65535)
    bad_port = json.dumps(
        {
            "protocol": "bitchat",
            "version": 1,
            "transport": "lan",
            "peer_id": "abcdef0123456789",
            "nickname": "Test",
            "port": 80,
        }
    ).encode()
    assert DiscoveryPacket.from_bytes(bad_port) is None

    # 6. Non-hex peer ID
    bad_hex = json.dumps(
        {
            "protocol": "bitchat",
            "version": 1,
            "transport": "lan",
            "peer_id": "not_hex_id_value",
            "nickname": "Test",
            "port": 41235,
        }
    ).encode()
    assert DiscoveryPacket.from_bytes(bad_hex) is None


def test_discovery_peer_ttl_expiration() -> None:
    now = time.time()
    peer = LANDiscoveredPeer(
        address="192.168.1.50:41235",
        ip="192.168.1.50",
        port=41235,
        peer_id="abcdef0123456789",
        nickname="Bob",
        last_seen=now - 31.0,
    )
    assert peer.is_expired(ttl=30.0, now=now) is True

    # Peer seen recently
    peer.last_seen = now - 5.0
    assert peer.is_expired(ttl=30.0, now=now) is False


def test_discovery_rate_limiting() -> None:
    discovery = LANDiscovery(
        local_peer_id="1111222233334444",
        local_nickname="Alice",
        listening_port=41235,
    )
    ip = "192.168.1.100"
    now = time.time()

    # Under rate limit
    for _ in range(MAX_DISCOVERY_RATE_PER_IP):
        assert discovery._is_rate_limited(ip, now) is False

    # Exceeds rate limit
    assert discovery._is_rate_limited(ip, now) is True

    # After 1 second passes, rate limit window resets
    assert discovery._is_rate_limited(ip, now + 1.1) is False


def test_discovery_datagram_self_ignore() -> None:
    discovered: list[LANDiscoveredPeer] = []
    discovery = LANDiscovery(
        local_peer_id="1111222233334444",
        local_nickname="Alice",
        listening_port=41235,
        on_peer_discovered=lambda p: discovered.append(p),
    )

    # Own beacon packet should be ignored
    own_pkt = DiscoveryPacket(
        peer_id="1111222233334444",
        nickname="Alice",
        port=41235,
    )
    res1 = discovery._process_incoming_packet(own_pkt.to_bytes(), "192.168.1.50")
    assert res1 is None
    assert len(discovered) == 0
    assert len(discovery.discovered_peers) == 0

    # Peer beacon packet should be processed
    remote_pkt = DiscoveryPacket(
        peer_id="9999888877776666",
        nickname="Bob",
        port=41236,
        ssid="MeshNet",
    )
    res2 = discovery._process_incoming_packet(remote_pkt.to_bytes(), "192.168.1.60")
    assert res2 is not None
    assert len(discovered) == 1
    assert "192.168.1.60:41236" in discovery.discovered_peers
    peer = discovery.discovered_peers["192.168.1.60:41236"]
    assert peer.nickname == "Bob"
    assert peer.ssid == "MeshNet"
