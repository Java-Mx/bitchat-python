"""Regression tests for LAN TCP deduplication, drain lock, and rate limiters."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from bitchat.network.connection import LANConnection
from bitchat.network.discovery import LANDiscovery
from bitchat.network.models import LANDiscoveredPeer
from bitchat.network.transport import LANTransport
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def make_packet(payload: bytes = b"lan payload") -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=b"\x01" * 8,
        recipient_id=b"\x02" * 8,
        payload=payload,
        signature=None,
    )


class MockWriter:
    def __init__(self, drain_delay: float = 0.0, drain_hang: bool = False) -> None:
        self.written: list[bytes] = []
        self.drain_delay = drain_delay
        self.drain_hang = drain_hang
        self.is_closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        if self.drain_hang:
            await asyncio.sleep(100.0)
        elif self.drain_delay > 0:
            await asyncio.sleep(self.drain_delay)

    def close(self) -> None:
        self.is_closed = True

    async def wait_closed(self) -> None:
        pass


@pytest.mark.asyncio
async def test_lan_connection_drain_outside_lock() -> None:
    """Validate LANConnection drain is executed outside self._lock to avoid blocking."""
    writer = MockWriter(drain_delay=0.01)
    conn = LANConnection(
        peer_address="192.168.1.10:41235",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
    )

    pkt = make_packet(b"hello drain")
    await conn.send_packet(pkt)

    assert len(writer.written) == 1
    assert not conn._lock.locked()


@pytest.mark.asyncio
async def test_lan_connection_drain_timeout_closes_socket() -> None:
    """Validate drain timeout aborts blocked transmission and cleanly closes socket."""
    writer = MockWriter(drain_hang=True)
    conn = LANConnection(
        peer_address="192.168.1.10:41235",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
    )

    import bitchat.network.connection as conn_mod

    orig_timeout = conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS
    conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS = 0.05
    try:
        with pytest.raises(TimeoutError):
            await conn.send_packet(make_packet())
        assert writer.is_closed
        assert not conn.is_connected
    finally:
        conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS = orig_timeout


@pytest.mark.asyncio
async def test_lan_discovery_rate_limiter_pruning() -> None:
    """Validate expired and empty IP entries are pruned from discovery rate limiter."""
    discovery = LANDiscovery(
        local_peer_id="01" * 8,
        local_nickname="Tester",
        listening_port=41235,
    )

    now = 1000.0
    # Simulate packets from several IPs
    discovery._is_rate_limited("192.168.1.10", now=now)
    discovery._is_rate_limited("192.168.1.20", now=now)
    assert len(discovery._rate_limiter) == 2

    # Advance time past 1.0s window
    now_later = now + 2.0
    pruned = discovery.prune_rate_limiter(max_age=1.0, now=now_later)
    assert pruned == 2
    assert len(discovery._rate_limiter) == 0


@pytest.mark.asyncio
async def test_lan_discovery_prune_stale_peers_cleans_rate_limiter() -> None:
    """Validate prune_stale_peers cleans expired rate limiter entries as well."""
    discovery = LANDiscovery(
        local_peer_id="01" * 8,
        local_nickname="Tester",
        listening_port=41235,
    )
    discovery._rate_limiter["10.0.0.1"] = [100.0]
    discovery.prune_stale_peers(now=105.0)
    assert "10.0.0.1" not in discovery._rate_limiter


@pytest.mark.asyncio
async def test_lan_transport_connect_peer_reuses_inbound_connection() -> None:
    """Validate connect_peer reuses existing ready inbound connection to same peer."""
    transport = LANTransport(
        local_peer_id="aaaa" * 4,
        local_nickname="NodeA",
        tcp_port=41235,
    )

    bob_addr = "192.168.1.50:41235"
    transport.discovery._discovered_peers[bob_addr] = LANDiscoveredPeer(
        address=bob_addr,
        ip="192.168.1.50",
        port=41235,
        peer_id="bbbb" * 4,
        nickname="Bob",
    )

    inbound_conn = LANConnection(
        peer_address="192.168.1.50:54321",
        reader=MagicMock(),
        writer=MockWriter(),  # type: ignore[arg-type]
        is_inbound=True,
    )
    transport._handle_inbound_connection(inbound_conn)
    assert "192.168.1.50:54321" in transport.connected_peers

    conn = await transport.connect_peer("192.168.1.50:41235")
    assert conn is inbound_conn
    assert len(transport.connected_peers) == 1

    await transport.stop()


@pytest.mark.asyncio
async def test_lan_transport_simultaneous_connection_tie_breaking() -> None:
    """Validate simultaneous open resolves by deterministic lexicographic comparison."""
    node_a = LANTransport(
        local_peer_id="1111" * 4,
        local_nickname="NodeA",
        tcp_port=41235,
    )
    peer_b_addr = "192.168.1.20:41235"
    node_a.discovery._discovered_peers[peer_b_addr] = LANDiscoveredPeer(
        address=peer_b_addr,
        ip="192.168.1.20",
        port=41235,
        peer_id="2222" * 4,
        nickname="NodeB",
    )

    outbound_conn = LANConnection(
        peer_address=peer_b_addr,
        reader=MagicMock(),
        writer=MockWriter(),  # type: ignore[arg-type]
        is_inbound=False,
    )
    node_a._connections[peer_b_addr] = outbound_conn
    node_a._peer_connections["peer:" + "2222" * 4] = outbound_conn

    inbound_conn = LANConnection(
        peer_address="192.168.1.20:54321",
        reader=MagicMock(),
        writer=MockWriter(),  # type: ignore[arg-type]
        is_inbound=True,
    )
    inbound_close_called = False

    async def mock_close() -> None:
        nonlocal inbound_close_called
        inbound_close_called = True

    inbound_conn.close = mock_close  # type: ignore[method-assign]

    # NodeA has lower peer_id ("1111..." < "2222..."): keeps outbound, drops inbound
    node_a._handle_inbound_connection(inbound_conn)
    await asyncio.sleep(0.01)

    assert inbound_close_called
    assert node_a._connections[peer_b_addr] is outbound_conn

    await node_a.stop()


@pytest.mark.asyncio
async def test_lan_transport_broadcast_no_duplicate_to_same_peer() -> None:
    """Validate broadcast_packet does not duplicate transmissions to the same peer."""
    transport = LANTransport(
        local_peer_id="aaaa" * 4,
        local_nickname="NodeA",
        tcp_port=41235,
    )

    writer = MockWriter()
    conn = LANConnection(
        peer_address="192.168.1.50:54321",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
        is_inbound=True,
    )
    transport._connections["192.168.1.50:54321"] = conn
    transport._connections["192.168.1.50:41235"] = conn
    transport._address_to_peer_key["192.168.1.50:54321"] = "peer:bbbb"
    transport._address_to_peer_key["192.168.1.50:41235"] = "peer:bbbb"

    pkt = make_packet(b"single broadcast")
    await transport.broadcast_packet(pkt)

    assert len(writer.written) == 1

    await transport.stop()
