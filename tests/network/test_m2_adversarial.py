"""Adversarial stress harness for Milestone 2: LAN connection and limiters."""

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


def make_packet(
    sender_id: bytes = b"\x01" * 8,
    recipient_id: bytes = b"\x02" * 8,
    payload: bytes = b"adversarial payload",
) -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        signature=None,
    )


class SlowOrStalledWriter:
    """Mock writer with controllable drain delay and stall flag."""

    def __init__(self, drain_delay: float = 0.0, drain_hang: bool = False) -> None:
        self.written: list[bytes] = []
        self.drain_delay = drain_delay
        self.drain_hang = drain_hang
        self.is_closed = False
        self.drain_count = 0
        self.in_drain = False
        self.drain_started = asyncio.Event()

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        self.drain_count += 1
        self.in_drain = True
        self.drain_started.set()
        try:
            if self.drain_hang:
                await asyncio.sleep(100.0)
            elif self.drain_delay > 0:
                await asyncio.sleep(self.drain_delay)
        finally:
            self.in_drain = False

    def close(self) -> None:
        self.is_closed = True

    async def wait_closed(self) -> None:
        pass


@pytest.mark.asyncio
async def test_adversarial_drain_lock_not_held_during_slow_drain() -> None:
    """Verify slow drain() does NOT hold self._lock and allows concurrency."""
    writer = SlowOrStalledWriter(drain_delay=0.3)
    conn = LANConnection(
        peer_address="192.168.1.50:41235",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
    )

    pkt1 = make_packet(payload=b"packet 1")
    pkt2 = make_packet(payload=b"packet 2")

    task1 = asyncio.create_task(conn.send_packet(pkt1))

    await asyncio.wait_for(writer.drain_started.wait(), timeout=1.0)
    assert writer.in_drain is True

    # Crucial assertion: conn._lock MUST NOT be locked while drain is executing
    assert not conn._lock.locked(), "Lock is held while writer.drain() is executing!"

    lock_acquired_during_drain = False

    async def send_pkt2() -> None:
        nonlocal lock_acquired_during_drain
        async with conn._lock:
            lock_acquired_during_drain = True
        await conn.send_packet(pkt2)

    task2 = asyncio.create_task(send_pkt2())

    await asyncio.sleep(0.05)
    assert lock_acquired_during_drain is True
    assert len(writer.written) >= 2, "Task 2 was blocked by task 1's slow drain!"

    await asyncio.gather(task1, task2)
    assert len(writer.written) == 2
    assert writer.drain_count == 2
    await conn.close()


@pytest.mark.asyncio
async def test_adversarial_drain_stalled_triggers_5s_timeout() -> None:
    """Verify stalled drain() cleanly triggers drain timeout and closes socket."""
    import bitchat.network.connection as conn_mod

    writer = SlowOrStalledWriter(drain_hang=True)
    conn = LANConnection(
        peer_address="192.168.1.50:41235",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
    )

    assert conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS == 5.0

    orig_timeout = conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS
    conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS = 0.15

    start_time = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            await conn.send_packet(make_packet())
        elapsed = time.monotonic() - start_time
        assert 0.10 <= elapsed <= 0.35, f"Timeout took unexpected duration: {elapsed}s"
        assert writer.is_closed is True, "Socket writer was not closed after timeout!"
        assert conn.is_connected is False, "Connection state not marked disconnected!"
        assert conn.is_ready is False
    finally:
        conn_mod.DEFAULT_DRAIN_TIMEOUT_SECONDS = orig_timeout


@pytest.mark.asyncio
async def test_adversarial_close_during_pending_drain() -> None:
    """Verify that calling close() while drain() is pending does not deadlock."""
    writer = SlowOrStalledWriter(drain_hang=True)
    conn = LANConnection(
        peer_address="192.168.1.50:41235",
        reader=MagicMock(),
        writer=writer,  # type: ignore[arg-type]
    )

    send_task = asyncio.create_task(conn.send_packet(make_packet()))
    await asyncio.wait_for(writer.drain_started.wait(), timeout=1.0)

    close_task = asyncio.create_task(conn.close())
    await asyncio.wait_for(close_task, timeout=1.0)

    assert writer.is_closed is True
    assert conn.is_connected is False

    send_task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await send_task


@pytest.mark.asyncio
async def test_adversarial_lan_simultaneous_connect_race() -> None:
    """Simulate simultaneous bidirectional connect race between peers A and B."""
    transport_a = LANTransport(
        local_peer_id="aaaa111122223333",
        local_nickname="Alice",
        tcp_port=41235,
    )
    transport_b = LANTransport(
        local_peer_id="bbbb111122223333",
        local_nickname="Bob",
        tcp_port=41236,
    )

    transport_a.discovery._discovered_peers["192.168.1.20:41236"] = LANDiscoveredPeer(
        address="192.168.1.20:41236",
        ip="192.168.1.20",
        port=41236,
        peer_id="bbbb111122223333",
        nickname="Bob",
    )
    transport_b.discovery._discovered_peers["192.168.1.10:41235"] = LANDiscoveredPeer(
        address="192.168.1.10:41235",
        ip="192.168.1.10",
        port=41235,
        peer_id="aaaa111122223333",
        nickname="Alice",
    )

    # Connection 1: Outbound from A to B
    conn_a_outbound = LANConnection(
        peer_address="192.168.1.20:41236",
        reader=MagicMock(),
        writer=SlowOrStalledWriter(),  # type: ignore[arg-type]
        is_inbound=False,
    )
    # Inbound on B from A
    conn_b_inbound = LANConnection(
        peer_address="192.168.1.10:54321",
        reader=MagicMock(),
        writer=SlowOrStalledWriter(),  # type: ignore[arg-type]
        is_inbound=True,
    )

    # Connection 2: Outbound from B to A
    conn_b_outbound = LANConnection(
        peer_address="192.168.1.10:41235",
        reader=MagicMock(),
        writer=SlowOrStalledWriter(),  # type: ignore[arg-type]
        is_inbound=False,
    )
    # Inbound on A from B
    conn_a_inbound = LANConnection(
        peer_address="192.168.1.20:54322",
        reader=MagicMock(),
        writer=SlowOrStalledWriter(),  # type: ignore[arg-type]
        is_inbound=True,
    )

    transport_a._connections[conn_a_outbound.peer_address] = conn_a_outbound
    transport_a._peer_connections["peer:bbbb111122223333"] = conn_a_outbound
    transport_a._address_to_peer_key[conn_a_outbound.peer_address] = (
        "peer:bbbb111122223333"
    )

    transport_b._connections[conn_b_outbound.peer_address] = conn_b_outbound
    transport_b._peer_connections["peer:aaaa111122223333"] = conn_b_outbound
    transport_b._address_to_peer_key[conn_b_outbound.peer_address] = (
        "peer:aaaa111122223333"
    )

    transport_a._handle_inbound_connection(conn_a_inbound)
    transport_b._handle_inbound_connection(conn_b_inbound)

    await asyncio.sleep(0.05)

    # 'aaaa' < 'bbbb': Peer A keeps outbound, drops inbound
    assert transport_a._peer_connections["peer:bbbb111122223333"] is conn_a_outbound, (
        "Peer A should have kept outbound connection!"
    )
    assert conn_a_inbound.peer_address not in transport_a._connections

    # Peer B keeps inbound from A, drops outbound
    assert transport_b._peer_connections["peer:aaaa111122223333"] is conn_b_inbound, (
        "Peer B should have kept inbound connection!"
    )
    assert conn_b_outbound.peer_address not in transport_b._connections


@pytest.mark.asyncio
async def test_adversarial_discovery_rate_limiter_flood_pruning() -> None:
    """Simulate a flood of 5,000 unique IP packets into LANDiscovery."""
    discovery = LANDiscovery(
        local_peer_id="01" * 8,
        local_nickname="Tester",
        listening_port=41235,
    )
    base_time = 1000.0

    for i in range(5000):
        fake_ip = f"10.0.{i // 256}.{i % 256}"
        discovery._is_rate_limited(fake_ip, now=base_time)

    assert len(discovery._rate_limiter) == 5000

    pruned_half = discovery.prune_rate_limiter(max_age=1.0, now=base_time + 0.5)
    assert pruned_half == 0
    assert len(discovery._rate_limiter) == 5000

    discovery._is_rate_limited("192.168.1.99", now=base_time + 1.1)

    assert len(discovery._rate_limiter) == 1, (
        f"Expected 1 entry remaining, found {len(discovery._rate_limiter)}"
    )
    assert "192.168.1.99" in discovery._rate_limiter


@pytest.mark.asyncio
async def test_adversarial_mesh_router_rate_limiter_flood_pruning() -> None:
    """Simulate a flood of 10,000 unique sender peer IDs into MeshRouter."""
    from bitchat.mesh.router import MeshRouter

    router = MeshRouter(local_peer_id=b"\x00" * 8)
    base_time = 2000.0

    # Flood with 1,500 unique hex sender IDs at t=base_time (exceeding 1000 threshold)
    for i in range(1500):
        sender_hex = f"{i:016x}"
        router.is_rate_limited(sender_hex, now=base_time)

    assert len(router._rate_limiter) == 1500

    router.is_rate_limited("ffffffffffffffff", now=base_time + 1.5)

    assert len(router._rate_limiter) == 1
    assert "ffffffffffffffff" in router._rate_limiter
