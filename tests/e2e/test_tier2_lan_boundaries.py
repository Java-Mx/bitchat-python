"""Tier 2: Boundary & Corner Cases — LAN TCP Transport Boundaries."""

from __future__ import annotations

import asyncio

import pytest

from bitchat.network.connection import LANConnection
from bitchat.network.discovery import MAX_DISCOVERY_RATE_PER_IP, LANDiscovery
from bitchat.network.framing import (
    FramingError,
    StreamFramer,
    encode_frame,
)
from bitchat.network.server import LANServer
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def test_framing_invalid_magic_raises_framing_error() -> None:
    """Validate stream framer rejects chunks with invalid magic prefix."""
    framer = StreamFramer()
    bad_magic_frame = b"XX\x01\x00\x00\x00\x00\x05Hello"
    with pytest.raises(FramingError, match="Invalid frame magic"):
        framer.feed(bad_magic_frame)


def test_framing_oversized_payload_raises_framing_error() -> None:
    """Validate frames claiming size > 65536 bytes are rejected."""
    # Attempt to encode 70 KB payload
    oversized = b"X" * 70000
    with pytest.raises(FramingError, match="exceeds maximum frame limit"):
        encode_frame(oversized)

    # Attempt to feed frame header claiming 100,000 bytes
    framer = StreamFramer()
    crafted_header = b"BC\x01\x00\x00\x01\x86\xa0"  # 100,000 in hex
    with pytest.raises(FramingError, match="exceeds limit"):
        framer.feed(crafted_header)


@pytest.mark.asyncio
async def test_lan_server_max_concurrent_connections_bound() -> None:
    """Validate LANServer bounds concurrent client connections to max_connections."""
    max_allowed = 2
    server = LANServer(
        host="127.0.0.1",
        port=0,
        max_connections=max_allowed,
    )
    await server.start()

    # Connect 2 allowed clients
    _r1, w1 = await asyncio.open_connection("127.0.0.1", server.bound_port)
    _r2, w2 = await asyncio.open_connection("127.0.0.1", server.bound_port)
    await asyncio.sleep(0.05)
    assert len(server._connections) == 2

    # Connect 3rd client exceeding limit
    _r3, w3 = await asyncio.open_connection("127.0.0.1", server.bound_port)
    await asyncio.sleep(0.05)

    # 3rd client should have been closed/rejected immediately
    assert len(server._connections) <= max_allowed

    w1.close()
    w2.close()
    w3.close()
    await server.stop()


@pytest.mark.asyncio
async def test_lan_connection_send_before_connected_raises_error() -> None:
    """Validate attempting to send a packet over an unconnected LANConnection raises ConnectionError."""
    conn = LANConnection(peer_address="127.0.0.1:9999")
    pkt = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=1,
        timestamp=100,
        flags=0,
        sender_id=b"\x00" * 8,
        recipient_id=None,
        payload=b"test",
        signature=None,
    )

    with pytest.raises(ConnectionError, match="not connected"):
        await conn.send_packet(pkt)


@pytest.mark.asyncio
async def test_lan_connection_invalid_address_format() -> None:
    """Validate connection attempt to malformed address format raises ValueError."""
    conn = LANConnection(peer_address="missing_port_address")
    with pytest.raises(ValueError, match="Invalid peer address format"):
        await conn.connect()


def test_lan_discovery_rate_limiting_bounds() -> None:
    """Validate discovery rate limiter throttles sender exceeding packet/sec threshold."""
    discovery = LANDiscovery(
        local_peer_id="alice",
        local_nickname="Alice",
        listening_port=4000,
    )

    sender_ip = "192.168.1.100"
    # First 10 packets are allowed
    for _ in range(MAX_DISCOVERY_RATE_PER_IP):
        assert discovery._is_rate_limited(sender_ip) is False

    # 11th packet exceeds rate limit and is throttled
    assert discovery._is_rate_limited(sender_ip) is True
