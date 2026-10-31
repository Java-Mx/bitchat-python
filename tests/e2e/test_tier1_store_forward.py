"""Tier 1: Feature Coverage — Store-and-Forward Queuing & Delivery."""

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


def _make_sample_packet(
    sender_id: bytes, recipient_id: bytes, text: str
) -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=text.encode("utf-8"),
        signature=None,
    )


def test_store_forward_enqueue_and_dequeue_fifo() -> None:
    """Validate enqueued packets are returned in strict FIFO order on dequeue."""
    queue = StoreAndForwardQueue()
    target_peer = "charlie_offline_1"
    sender = os.urandom(SENDER_ID_SIZE)
    recip = os.urandom(SENDER_ID_SIZE)

    p1 = _make_sample_packet(sender, recip, "First queued message")
    p2 = _make_sample_packet(sender, recip, "Second queued message")
    p3 = _make_sample_packet(sender, recip, "Third queued message")

    assert queue.enqueue(target_peer, p1) is True
    assert queue.enqueue(target_peer, p2) is True
    assert queue.enqueue(target_peer, p3) is True

    assert queue.total_packets == 3
    assert queue.has_pending(target_peer) is True

    dequeued = queue.dequeue_for_peer(target_peer)
    assert len(dequeued) == 3
    assert dequeued[0].payload == b"First queued message"
    assert dequeued[1].payload == b"Second queued message"
    assert dequeued[2].payload == b"Third queued message"

    assert queue.total_packets == 0
    assert queue.has_pending(target_peer) is False


def test_store_forward_peer_isolation() -> None:
    """Validate messages queued for different peers remain strictly isolated."""
    queue = StoreAndForwardQueue()
    sender = os.urandom(SENDER_ID_SIZE)
    peer_a = "peer_alpha"
    peer_b = "peer_bravo"

    p_a = _make_sample_packet(sender, os.urandom(8), "Payload for Alpha")
    p_b = _make_sample_packet(sender, os.urandom(8), "Payload for Bravo")

    queue.enqueue(peer_a, p_a)
    queue.enqueue(peer_b, p_b)

    assert queue.peer_count == 2
    assert queue.total_packets == 2

    # Dequeue for Alpha only
    dequeued_a = queue.dequeue_for_peer(peer_a)
    assert len(dequeued_a) == 1
    assert dequeued_a[0].payload == b"Payload for Alpha"

    # Bravo's queue still intact
    assert queue.has_pending(peer_b) is True
    assert queue.total_packets == 1

    dequeued_b = queue.dequeue_for_peer(peer_b)
    assert len(dequeued_b) == 1
    assert dequeued_b[0].payload == b"Payload for Bravo"
    assert queue.total_packets == 0


def test_store_forward_accounting_metrics() -> None:
    """Validate total_packets and total_bytes tracking across queue lifecycle."""
    queue = StoreAndForwardQueue()
    sender = os.urandom(SENDER_ID_SIZE)
    target = "metric_peer"

    assert queue.total_packets == 0
    assert queue.total_bytes == 0

    p1 = _make_sample_packet(sender, os.urandom(8), "1234567890")
    queue.enqueue(target, p1)

    assert queue.total_packets == 1
    bytes_after_one = queue.total_bytes
    assert bytes_after_one > 0

    p2 = _make_sample_packet(sender, os.urandom(8), "12345678901234567890")
    queue.enqueue(target, p2)

    assert queue.total_packets == 2
    assert queue.total_bytes > bytes_after_one

    queue.dequeue_for_peer(target)
    assert queue.total_packets == 0
    assert queue.total_bytes == 0


def test_store_forward_prune_expired_packets() -> None:
    """Validate pruning packets that exceed packet_ttl_seconds."""
    queue = StoreAndForwardQueue(packet_ttl_seconds=10.0)
    sender = os.urandom(SENDER_ID_SIZE)
    target = "stale_peer"

    t0 = 1000.0
    p1 = _make_sample_packet(sender, os.urandom(8), "Will expire soon")
    queue.enqueue(target, p1, now=t0)
    assert queue.total_packets == 1

    # Before expiration (t0 + 5s)
    pruned = queue.prune_expired(now=t0 + 5.0)
    assert pruned == 0
    assert queue.total_packets == 1

    # After expiration (t0 + 15s)
    pruned = queue.prune_expired(now=t0 + 15.0)
    assert pruned == 1
    assert queue.total_packets == 0
    assert queue.has_pending(target) is False


def test_store_forward_empty_dequeue_returns_empty() -> None:
    """Validate querying an unknown or empty peer queue returns an empty list."""
    queue = StoreAndForwardQueue()
    assert queue.dequeue_for_peer("nonexistent_peer") == []
    assert queue.has_pending("nonexistent_peer") is False
