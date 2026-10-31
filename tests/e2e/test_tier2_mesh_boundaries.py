"""Tier 2: Boundary & Corner Cases — Mesh Routing Boundaries."""

from __future__ import annotations

import os
import time

from bitchat.mesh.dedup import PacketDeduplicator
from bitchat.mesh.router import MeshRouter
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def test_mesh_packet_ttl_zero_dropped() -> None:
    """Validate packet with TTL=0 is dropped immediately."""
    router = MeshRouter(local_peer_id=b"\x00" * 8)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=0,
        timestamp=int(time.time()),
        flags=0,
        sender_id=b"\x01" * 8,
        recipient_id=None,
        payload=b"Zero TTL message",
        signature=None,
    )

    decision = router.evaluate_incoming(packet)
    assert decision.should_process_locally is False
    assert decision.packet_to_relay is None
    assert decision.drop_reason is not None
    assert "TTL" in decision.drop_reason


def test_mesh_packet_ttl_one_not_relayed() -> None:
    """Validate packet with TTL=1 is processed locally for broadcast but not relayed further."""
    router = MeshRouter(local_peer_id=b"\x00" * 8)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=1,
        timestamp=int(time.time()),
        flags=0,
        sender_id=b"\x01" * 8,
        recipient_id=None,
        payload=b"Final hop broadcast",
        signature=None,
    )

    decision = router.evaluate_incoming(packet)
    assert decision.should_process_locally is True
    assert decision.packet_to_relay is None  # Hop count exhausted


def test_mesh_router_peer_rate_limit_exceeded() -> None:
    """Validate peer exceeding rate_limit_per_peer (50 pkts/sec) is dropped."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    router = MeshRouter(local_peer_id=b"\x00" * 8, rate_limit_per_peer=5)

    now = 1000.0
    for i in range(5):
        pkt = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.Message,
            ttl=5,
            timestamp=int(now * 1000) + i,
            flags=0,
            sender_id=sender_id,
            recipient_id=None,
            payload=f"Burst {i}".encode(),
            signature=None,
        )
        dec = router.evaluate_incoming(pkt, now=now)
        assert dec.drop_reason is None

    # 6th packet exceeds rate limit
    pkt6 = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(now * 1000) + 6,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=b"Exceeding packet",
        signature=None,
    )
    dec6 = router.evaluate_incoming(pkt6, now=now)
    assert dec6.should_process_locally is False
    assert dec6.packet_to_relay is None
    assert dec6.drop_reason is not None
    assert "Rate limit" in dec6.drop_reason


def test_mesh_deduplicator_capacity_lru_eviction() -> None:
    """Validate deduplicator LRU capacity bounds: exceeding max_entries evicts oldest."""
    dedup = PacketDeduplicator(max_entries=3, entry_ttl_seconds=300.0)

    sender = b"\x01" * 8

    def make_pkt(payload: bytes, ts: int) -> BitchatPacket:
        return BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.Message,
            ttl=5,
            timestamp=ts,
            flags=0,
            sender_id=sender,
            recipient_id=None,
            payload=payload,
            signature=None,
        )

    p1 = make_pkt(b"msg1", 1)
    p2 = make_pkt(b"msg2", 2)
    p3 = make_pkt(b"msg3", 3)
    p4 = make_pkt(b"msg4", 4)

    dedup.record(p1)
    dedup.record(p2)
    dedup.record(p3)
    assert len(dedup._entries) == 3

    # Recording 4th should evict p1
    dedup.record(p4)
    assert len(dedup._entries) == 3

    # p1 is no longer in cache
    assert dedup.is_duplicate(p1) is False
    # p4 is in cache
    assert dedup.is_duplicate(p4) is True


def test_mesh_deduplicator_expired_entry_allowed() -> None:
    """Validate expired deduplication entries allow packet retransmission."""
    dedup = PacketDeduplicator(max_entries=100, entry_ttl_seconds=5.0)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=b"\x01" * 8,
        recipient_id=None,
        payload=b"Retransmit test",
        signature=None,
    )

    t0 = 1000.0
    dedup.record(packet, now=t0)
    assert dedup.is_duplicate(packet, now=t0 + 2.0) is True

    # 6 seconds later (> 5.0s TTL)
    assert dedup.is_duplicate(packet, now=t0 + 6.0) is False


def test_mesh_router_max_relay_ttl_clamping() -> None:
    """Validate TTL exceeding max_relay_ttl is clamped before decrementing."""
    router = MeshRouter(local_peer_id=b"\x00" * 8, max_relay_ttl=10)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=50,  # Ridiculously high TTL
        timestamp=1000,
        flags=0,
        sender_id=b"\x01" * 8,
        recipient_id=None,
        payload=b"High TTL packet",
        signature=None,
    )

    decision = router.evaluate_incoming(packet)
    assert decision.packet_to_relay is not None
    # Clamped to max_relay_ttl (10) - 1 = 9
    assert decision.packet_to_relay.ttl == 9
