"""Unit tests for the BitChat mesh routing, deduplication,
and store-and-forward subsystem.
"""

from __future__ import annotations

from dataclasses import replace

from bitchat.mesh.dedup import PacketDeduplicator, compute_packet_id
from bitchat.mesh.router import MeshRouter
from bitchat.mesh.store_forward import StoreAndForwardQueue
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket


def _make_packet(
    sender_id: bytes = b"\x01" * 8,
    recipient_id: bytes | None = None,
    payload: bytes = b"test message",
    ttl: int = 7,
    timestamp: int = 100000,
    message_type: MessageType = MessageType.Message,
) -> BitchatPacket:
    return BitchatPacket.create(
        message_type=message_type,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        ttl=ttl,
        timestamp=timestamp,
    )


class TestPacketDeduplication:
    """Tests for packet identifier computation and deduplication LRU cache."""

    def test_packet_id_ttl_invariance(self) -> None:
        """Packet ID must remain identical even when TTL is decremented across hops."""
        pkt1 = _make_packet(ttl=7)
        pkt2 = replace(pkt1, ttl=6)
        pkt3 = replace(pkt1, ttl=1)

        id1 = compute_packet_id(pkt1)
        id2 = compute_packet_id(pkt2)
        id3 = compute_packet_id(pkt3)

        assert id1 == id2 == id3
        assert len(id1) == 32  # 16 bytes hex

    def test_packet_id_distinguishes_different_packets(self) -> None:
        """Different payloads, senders, or timestamps must yield different IDs."""
        pkt_base = _make_packet()
        pkt_diff_sender = _make_packet(sender_id=b"\x02" * 8)
        pkt_diff_time = _make_packet(timestamp=200000)
        pkt_diff_payload = _make_packet(payload=b"different")

        id_base = compute_packet_id(pkt_base)
        assert compute_packet_id(pkt_diff_sender) != id_base
        assert compute_packet_id(pkt_diff_time) != id_base
        assert compute_packet_id(pkt_diff_payload) != id_base

    def test_deduplicator_check_and_record(self) -> None:
        """First observation records packet; second observation reports duplicate."""
        dedup = PacketDeduplicator(max_entries=10, entry_ttl_seconds=60.0)
        pkt = _make_packet()

        # First time: not a duplicate, recorded
        assert dedup.check_and_record(pkt) is False
        assert len(dedup) == 1

        # Second time: duplicate detected
        assert dedup.check_and_record(pkt) is True
        assert dedup.is_duplicate(pkt) is True

    def test_deduplicator_capacity_bound(self) -> None:
        """Exceeding max_entries evicts oldest entries (FIFO/LRU)."""
        dedup = PacketDeduplicator(max_entries=3, entry_ttl_seconds=60.0)

        pkt1 = _make_packet(timestamp=1)
        pkt2 = _make_packet(timestamp=2)
        pkt3 = _make_packet(timestamp=3)
        pkt4 = _make_packet(timestamp=4)

        dedup.check_and_record(pkt1)
        dedup.check_and_record(pkt2)
        dedup.check_and_record(pkt3)
        assert len(dedup) == 3

        # Adding pkt4 should evict pkt1
        dedup.check_and_record(pkt4)
        assert len(dedup) == 3
        assert dedup.is_duplicate(pkt1) is False
        assert dedup.is_duplicate(pkt2) is True
        assert dedup.is_duplicate(pkt3) is True
        assert dedup.is_duplicate(pkt4) is True

    def test_deduplicator_expiration(self) -> None:
        """Entries older than entry_ttl_seconds expire and can be pruned."""
        dedup = PacketDeduplicator(max_entries=10, entry_ttl_seconds=5.0)
        pkt = _make_packet()

        dedup.record(pkt, now=100.0)
        assert dedup.is_duplicate(pkt, now=104.0) is True

        # Expired at now=106.0
        assert dedup.is_duplicate(pkt, now=106.0) is False

        # Prune
        dedup.record(pkt, now=100.0)
        pruned = dedup.prune_expired(now=106.0)
        assert pruned == 1
        assert len(dedup) == 0


class TestStoreAndForwardQueue:
    """Tests for offline message buffering and delivery."""

    def test_enqueue_and_dequeue(self) -> None:
        """Queued packets for a peer can be retrieved and cleared upon arrival."""
        queue = StoreAndForwardQueue(max_total_packets=10, packet_ttl_seconds=60.0)
        target = b"\xbb" * 8
        pkt1 = _make_packet(recipient_id=target, payload=b"msg1")
        pkt2 = _make_packet(recipient_id=target, payload=b"msg2")

        assert queue.enqueue(target, pkt1, now=100.0) is True
        assert queue.enqueue(target, pkt2, now=101.0) is True
        assert queue.has_pending(target) is True
        assert queue.total_packets == 2

        # Dequeue
        dequeued = queue.dequeue_for_peer(target, now=102.0)
        assert len(dequeued) == 2
        assert dequeued[0].payload == b"msg1"
        assert dequeued[1].payload == b"msg2"
        assert queue.has_pending(target) is False
        assert queue.total_packets == 0

    def test_per_peer_limit(self) -> None:
        """Queuing beyond max_per_peer evicts oldest packets for that peer."""
        queue = StoreAndForwardQueue(
            max_total_packets=10, max_per_peer=2, packet_ttl_seconds=60.0
        )
        target = "peer-alpha"
        p1 = _make_packet(payload=b"1")
        p2 = _make_packet(payload=b"2")
        p3 = _make_packet(payload=b"3")

        queue.enqueue(target, p1, now=1.0)
        queue.enqueue(target, p2, now=2.0)
        queue.enqueue(target, p3, now=3.0)

        dequeued = queue.dequeue_for_peer(target, now=4.0)
        assert len(dequeued) == 2
        assert dequeued[0].payload == b"2"
        assert dequeued[1].payload == b"3"

    def test_global_capacity_limit(self) -> None:
        """Exceeding max_total_packets evicts oldest globally."""
        queue = StoreAndForwardQueue(
            max_total_packets=2, max_per_peer=2, packet_ttl_seconds=60.0
        )
        p1 = _make_packet(payload=b"p1")
        p2 = _make_packet(payload=b"p2")
        p3 = _make_packet(payload=b"p3")

        queue.enqueue("peerA", p1, now=1.0)
        queue.enqueue("peerB", p2, now=2.0)
        queue.enqueue("peerC", p3, now=3.0)

        assert queue.total_packets == 2
        assert queue.has_pending("peerA") is False
        assert queue.has_pending("peerB") is True
        assert queue.has_pending("peerC") is True

    def test_byte_budget_enforcement(self) -> None:
        """Packets exceeding total byte budget are rejected."""
        queue = StoreAndForwardQueue(max_total_bytes=100)
        giant_pkt = _make_packet(payload=b"X" * 200)

        assert queue.enqueue("peerA", giant_pkt) is False
        assert queue.total_packets == 0


class TestMeshRouter:
    """Tests for MeshRouter routing decisions, TTL, and security boundaries."""

    def test_drop_packets_from_self(self) -> None:
        """Packets originated by local peer are dropped to avoid echo loops."""
        my_id = b"\xaa" * 8
        router = MeshRouter(local_peer_id=my_id)
        pkt = _make_packet(sender_id=my_id)

        decision = router.evaluate_incoming(pkt)
        assert decision.should_process_locally is False
        assert decision.packet_to_relay is None
        assert "originated from local" in (decision.drop_reason or "")

    def test_drop_expired_ttl(self) -> None:
        """Packets with TTL <= 0 are immediately dropped."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8)
        pkt = _make_packet(ttl=0)

        decision = router.evaluate_incoming(pkt)
        assert decision.should_process_locally is False
        assert decision.packet_to_relay is None

    def test_ttl_1_processed_locally_but_not_relayed(self) -> None:
        """Broadcast packet with TTL=1 is consumed locally but dropped from relaying."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8)
        pkt = _make_packet(ttl=1)

        decision = router.evaluate_incoming(pkt)
        assert decision.should_process_locally is True
        assert decision.packet_to_relay is None  # Cannot relay with TTL=1

    def test_ttl_decremented_on_relay(self) -> None:
        """Incoming broadcast with TTL=5 produces relay packet with TTL=4."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8)
        pkt = _make_packet(ttl=5)

        decision = router.evaluate_incoming(pkt, ingress_source="peer_b")
        assert decision.should_process_locally is True
        assert decision.packet_to_relay is not None
        assert decision.packet_to_relay.ttl == 4
        assert decision.exclude_ingress == "peer_b"

    def test_ttl_clamping_to_safety_maximum(self) -> None:
        """Abusively large TTLs (e.g. 50) are clamped to max_relay_ttl."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8, max_relay_ttl=8)
        pkt = _make_packet(ttl=50)

        decision = router.evaluate_incoming(pkt)
        assert decision.packet_to_relay is not None
        assert decision.packet_to_relay.ttl == 7  # min(50, 8) - 1

    def test_duplicate_suppression(self) -> None:
        """Identical packets arriving via different paths are suppressed."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8)
        pkt = _make_packet(ttl=5)

        decision1 = router.evaluate_incoming(pkt, ingress_source="peer_b")
        assert decision1.should_process_locally is True
        assert decision1.packet_to_relay is not None

        # Arrives from another peer with decremented TTL
        pkt_hop = replace(pkt, ttl=4)
        decision2 = router.evaluate_incoming(pkt_hop, ingress_source="peer_c")
        assert decision2.should_process_locally is False
        assert decision2.packet_to_relay is None
        assert "Duplicate" in (decision2.drop_reason or "")

    def test_rate_limiting_defense(self) -> None:
        """Excessive packet flooding from a single peer triggers rate-limit drop."""
        router = MeshRouter(local_peer_id=b"\xaa" * 8, rate_limit_per_peer=5)
        sender = b"\x03" * 8

        # Send 5 packets in the same second
        for i in range(5):
            pkt = _make_packet(sender_id=sender, timestamp=i, payload=bytes([i]))
            decision = router.evaluate_incoming(pkt, now=100.0)
            assert decision.drop_reason is None

        # 6th packet must be dropped
        overflow_pkt = _make_packet(sender_id=sender, timestamp=99, payload=b"flood")
        decision = router.evaluate_incoming(overflow_pkt, now=100.0)
        assert decision.should_process_locally is False
        assert decision.packet_to_relay is None
        assert "Rate limit exceeded" in (decision.drop_reason or "")

    def test_unicast_for_local_node_is_not_relayed(self) -> None:
        """Unicast packet addressed to our node is processed locally and not relayed."""
        my_id = b"\xaa" * 8
        router = MeshRouter(local_peer_id=my_id)
        pkt = _make_packet(recipient_id=my_id, ttl=5)

        decision = router.evaluate_incoming(pkt)
        assert decision.should_process_locally is True
        assert decision.packet_to_relay is None

    def test_unicast_for_remote_node_is_relayed(self) -> None:
        """Unicast packet addressed to another node is NOT processed locally,
        but relayed.
        """
        my_id = b"\xaa" * 8
        target_id = b"\xcc" * 8
        router = MeshRouter(local_peer_id=my_id)
        pkt = _make_packet(recipient_id=target_id, ttl=5)

        decision = router.evaluate_incoming(pkt)
        assert decision.should_process_locally is False
        assert decision.packet_to_relay is not None
        assert decision.packet_to_relay.ttl == 4
        assert decision.target_peer_id_hex == target_id.hex()
