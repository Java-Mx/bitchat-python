"""Tier 1: Feature Coverage — Multi-Hop Mesh Routing & Deduplication."""

from __future__ import annotations

import os
import time

from bitchat.mesh.dedup import PacketDeduplicator
from bitchat.mesh.router import MeshRouter
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def test_mesh_router_broadcast_processed_locally_and_relayed() -> None:
    """Validate broadcast packet with TTL=5 is processed locally and relayed with TTL=4."""
    local_id = os.urandom(SENDER_ID_SIZE)
    remote_sender = os.urandom(SENDER_ID_SIZE)

    router = MeshRouter(local_peer_id=local_id)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=0,
        sender_id=remote_sender,
        recipient_id=None,
        payload=b"Public mesh announcement",
        signature=None,
    )

    decision = router.evaluate_incoming(packet, ingress_source="peer_1")

    assert decision.should_process_locally is True
    assert decision.packet_to_relay is not None
    assert decision.packet_to_relay.ttl == 4
    assert decision.packet_to_relay.payload == packet.payload
    assert decision.exclude_ingress == "peer_1"


def test_mesh_router_unicast_for_local_peer() -> None:
    """Validate packet addressed specifically to local peer is processed locally and not relayed."""
    local_id = os.urandom(SENDER_ID_SIZE)
    remote_sender = os.urandom(SENDER_ID_SIZE)

    router = MeshRouter(local_peer_id=local_id)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=4,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=remote_sender,
        recipient_id=local_id,
        payload=b"Direct message for local node",
        signature=None,
    )

    decision = router.evaluate_incoming(packet, ingress_source="peer_ingress")

    assert decision.should_process_locally is True
    # Destination reached: do not relay further
    assert decision.packet_to_relay is None


def test_mesh_router_unicast_for_other_peer_relayed() -> None:
    """Validate packet addressed to third party is relayed with decremented TTL and not processed locally."""
    local_id = os.urandom(SENDER_ID_SIZE)
    remote_sender = os.urandom(SENDER_ID_SIZE)
    remote_destination = os.urandom(SENDER_ID_SIZE)

    router = MeshRouter(local_peer_id=local_id)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=6,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=remote_sender,
        recipient_id=remote_destination,
        payload=b"Transit packet traversing mesh",
        signature=None,
    )

    decision = router.evaluate_incoming(packet, ingress_source="link_a")

    assert decision.should_process_locally is False
    assert decision.packet_to_relay is not None
    assert decision.packet_to_relay.ttl == 5
    assert decision.target_peer_id_hex == remote_destination.hex()


def test_mesh_router_drops_own_packet_loop_prevention() -> None:
    """Validate loop prevention: router immediately drops packets originated by itself."""
    local_id = os.urandom(SENDER_ID_SIZE)
    router = MeshRouter(local_peer_id=local_id)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=0,
        sender_id=local_id,  # Local node originated this
        recipient_id=None,
        payload=b"Echoed own broadcast",
        signature=None,
    )

    decision = router.evaluate_incoming(packet)
    assert decision.should_process_locally is False
    assert decision.packet_to_relay is None
    assert decision.drop_reason is not None
    assert "local peer" in decision.drop_reason.lower()


def test_packet_deduplicator_cache_and_suppression() -> None:
    """Validate deduplication cache suppresses retransmitted packets within TTL window."""
    dedup = PacketDeduplicator(max_entries=100, entry_ttl_seconds=60.0)

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=1000,
        flags=0,
        sender_id=b"\x01" * 8,
        recipient_id=None,
        payload=b"Unique message payload",
        signature=None,
    )

    # First arrival: not a duplicate
    assert dedup.is_duplicate(packet) is False
    assert dedup.check_and_record(packet) is False  # Recorded

    # Second arrival: recognized as duplicate
    assert dedup.is_duplicate(packet) is True
    assert dedup.check_and_record(packet) is True


def test_mesh_router_relay_jitter_bounds() -> None:
    """Validate random relay jitter stays within configured minimum and maximum bounds."""
    router = MeshRouter(
        local_peer_id=b"\x00" * 8,
        relay_jitter_min=0.015,
        relay_jitter_max=0.045,
    )

    for _ in range(50):
        jitter = router.get_relay_jitter()
        assert 0.015 <= jitter <= 0.045
