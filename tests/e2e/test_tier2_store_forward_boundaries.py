"""Tier 2: Boundary & Corner Cases — Store-and-Forward Boundaries."""

from __future__ import annotations

import os
import time

from bitchat.mesh.store_forward import StoreAndForwardQueue
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def _make_sample_packet(payload: bytes, ts: int | None = None) -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time() * 1000) if ts is None else ts,
        flags=FLAG_HAS_RECIPIENT,
        sender_id=os.urandom(SENDER_ID_SIZE),
        recipient_id=os.urandom(SENDER_ID_SIZE),
        payload=payload,
        signature=None,
    )


def test_store_forward_oversized_packet_rejected() -> None:
    """Validate packet exceeding max_total_bytes (256 KB) is rejected on enqueue."""
    queue = StoreAndForwardQueue(max_total_bytes=1024)  # 1 KB limit
    oversized_pkt = _make_sample_packet(b"X" * 2000)

    assert queue.enqueue("target_peer", oversized_pkt) is False
    assert queue.total_packets == 0


def test_store_forward_max_per_peer_eviction() -> None:
    """Validate enqueuing more than max_per_peer evicts oldest packet for that peer."""
    queue = StoreAndForwardQueue(max_per_peer=3)
    target = "peer_charlie"

    p1 = _make_sample_packet(b"First message", ts=100)
    p2 = _make_sample_packet(b"Second message", ts=200)
    p3 = _make_sample_packet(b"Third message", ts=300)
    p4 = _make_sample_packet(b"Fourth message", ts=400)

    queue.enqueue(target, p1)
    queue.enqueue(target, p2)
    queue.enqueue(target, p3)
    assert queue.total_packets == 3

    # Enqueueing 4th should evict p1
    queue.enqueue(target, p4)
    assert queue.total_packets == 3

    dequeued = queue.dequeue_for_peer(target)
    assert len(dequeued) == 3
    # p1 evicted, p2, p3, p4 remain
    assert dequeued[0].payload == b"Second message"
    assert dequeued[1].payload == b"Third message"
    assert dequeued[2].payload == b"Fourth message"


def test_store_forward_max_total_packets_eviction() -> None:
    """Validate enqueuing beyond max_total_packets evicts globally oldest packet."""
    queue = StoreAndForwardQueue(max_total_packets=3, max_per_peer=10)

    p1 = _make_sample_packet(b"Peer1 msg", ts=100)
    p2 = _make_sample_packet(b"Peer2 msg", ts=200)
    p3 = _make_sample_packet(b"Peer3 msg", ts=300)
    p4 = _make_sample_packet(b"Peer4 msg", ts=400)

    t0 = 1000.0
    queue.enqueue("peer1", p1, now=t0)
    queue.enqueue("peer2", p2, now=t0 + 1)
    queue.enqueue("peer3", p3, now=t0 + 2)
    assert queue.total_packets == 3

    # 4th enqueued -> oldest (p1 on peer1) evicted
    queue.enqueue("peer4", p4, now=t0 + 3)
    assert queue.total_packets == 3

    assert queue.has_pending("peer1") is False
    assert queue.has_pending("peer2") is True
    assert queue.has_pending("peer3") is True
    assert queue.has_pending("peer4") is True


def test_store_forward_expired_packets_filtered_on_dequeue() -> None:
    """Validate packets that expire while queued are filtered out upon dequeue."""
    queue = StoreAndForwardQueue(packet_ttl_seconds=10.0)
    target = "transient_peer"

    t0 = 1000.0
    p1 = _make_sample_packet(b"Expired packet")
    p2 = _make_sample_packet(b"Fresh packet")

    queue.enqueue(target, p1, now=t0)
    queue.enqueue(target, p2, now=t0 + 15.0)  # enqueued 15s later

    # Dequeue at t0 + 18.0: p1 is 18s old (expired), p2 is 3s old (valid)
    dequeued = queue.dequeue_for_peer(target, now=t0 + 18.0)
    assert len(dequeued) == 1
    assert dequeued[0].payload == b"Fresh packet"


def test_store_forward_byte_budget_enforcement() -> None:
    """Validate store and forward queue strictly bounds total byte memory usage."""
    queue = StoreAndForwardQueue(max_total_bytes=300, max_total_packets=10)

    # Each packet payload is 100 bytes (plus ~32B overhead estimate = ~132B)
    p1 = _make_sample_packet(b"A" * 100)
    p2 = _make_sample_packet(b"B" * 100)
    p3 = _make_sample_packet(b"C" * 100)

    t0 = 1000.0
    assert queue.enqueue("peerA", p1, now=t0) is True
    assert queue.enqueue("peerB", p2, now=t0 + 1) is True

    # Third packet would exceed 300 bytes, triggers eviction of oldest
    assert queue.enqueue("peerC", p3, now=t0 + 2) is True
    assert queue.total_bytes <= 300
