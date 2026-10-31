"""Empirical Adversarial Challenge Test Suite for Milestone 3.

Stress-tests:
1. Multi-hop 4-node linear chain routing (A <-> R1 <-> R2 <-> B)
2. Ring topology loop prevention and deduplication storm suppression (A-B-C-A)
3. Routing table capacity thrashing and shortest-path preference
4. Adversarial fragment injection (zero total, out-of-bounds index, limit breach)
5. Strict TTL boundary evaluation (TTL 0, 1, 2, clamped large TTL)
6. Periodic cache pruning concurrency and clean cancellation under load
"""

from __future__ import annotations

import asyncio
import time

import pytest
from tests.mesh.test_mesh_routing_resolution import DummyTransport

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import (
    FragmentLimitExceededError,
    InvalidFragmentError,
)
from bitchat.mesh.router import MeshRouter
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import InMemoryStorage


def make_coord(name: str = "TestNode") -> tuple[SessionCoordinator, DummyTransport]:
    identity = LocalIdentity.generate()
    transport = DummyTransport(address=f"{name}_ADDR")
    storage = InMemoryStorage()
    coord = SessionCoordinator(
        local_identity=identity,
        transport=transport,
        storage=storage,
        nickname=name,
    )
    return coord, transport


def link_pair(
    coord_a: SessionCoordinator,
    trans_a: DummyTransport,
    coord_b: SessionCoordinator,
    trans_b: DummyTransport,
) -> None:
    """Wire two dummy transports together bi-directionally."""
    addr_a = trans_a.address
    addr_b = trans_b.address

    if addr_b not in trans_a._connected:
        trans_a._connected.append(addr_b)
    if addr_a not in trans_b._connected:
        trans_b._connected.append(addr_a)

    orig_send_a = trans_a.send_to_peer
    orig_bcast_a = trans_a.broadcast_packet

    async def send_a(target_addr: str, packet: BitchatPacket) -> None:
        await orig_send_a(target_addr, packet)
        if target_addr == addr_b:
            coord_b._handle_incoming_packet(packet, peer_address=addr_a)

    async def bcast_a(
        packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        await orig_bcast_a(packet, exclude_address)
        if exclude_address != addr_b:
            coord_b._handle_incoming_packet(packet, peer_address=addr_a)

    trans_a.send_to_peer = send_a  # type: ignore[method-assign]
    trans_a.broadcast_packet = bcast_a  # type: ignore[method-assign]

    orig_send_b = trans_b.send_to_peer
    orig_bcast_b = trans_b.broadcast_packet

    async def send_b(target_addr: str, packet: BitchatPacket) -> None:
        await orig_send_b(target_addr, packet)
        if target_addr == addr_a:
            coord_a._handle_incoming_packet(packet, peer_address=addr_b)

    async def bcast_b(
        packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        await orig_bcast_b(packet, exclude_address)
        if exclude_address != addr_a:
            coord_a._handle_incoming_packet(packet, peer_address=addr_b)

    trans_b.send_to_peer = send_b  # type: ignore[method-assign]
    trans_b.broadcast_packet = bcast_b  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_challenge_four_node_multihop_chain() -> None:
    """Stress test: 4 nodes A <-> R1 <-> R2 <-> B.

    Alice must establish an encrypted session and deliver direct messages to Bob
    across two intermediate relays without direct connection.
    """
    node_a, trans_a = make_coord("Alice")
    node_r1, trans_r1 = make_coord("Relay1")
    node_r2, trans_r2 = make_coord("Relay2")
    node_b, trans_b = make_coord("Bob")

    # Linear links
    link_pair(node_a, trans_a, node_r1, trans_r1)
    link_pair(node_r1, trans_r1, node_r2, trans_r2)
    link_pair(node_r2, trans_r2, node_b, trans_b)

    await node_a.start()
    await node_r1.start()
    await node_r2.start()
    await node_b.start()

    # Announce from Bob to propagate across R2 -> R1 -> A
    await node_b.send_announce("Bob")
    await node_a.send_announce("Alice")

    # Give mesh routing propagation a brief moment
    await asyncio.sleep(0.3)

    bob_hex = node_b.local_identity.peer_id_hex
    alice_hex = node_a.local_identity.peer_id_hex

    # Verify routing table resolution on Alice
    next_hop_for_bob = node_a.mesh_router.get_next_hop(bob_hex)
    assert next_hop_for_bob is not None, "Alice should have a learned route to Bob"

    # Verify routing table resolution on Bob
    next_hop_for_alice = node_b.mesh_router.get_next_hop(alice_hex)
    assert next_hop_for_alice is not None, "Bob should have a learned route to Alice"

    # Bob should receive direct message from Alice
    received_msgs: list[tuple[str, str, bool]] = []
    node_b.on_message_received = lambda s, m, enc: received_msgs.append((s, m, enc))

    secret = "SuperSecret: 3 hops over 2 intermediate relays"
    await node_a.send_direct_message(bob_hex, secret)

    # Wait for handshake and encrypted message delivery across 3 hops
    for _ in range(50):
        if any(m[1] == secret for m in received_msgs):
            break
        await asyncio.sleep(0.05)

    assert any(m[1] == secret and m[2] is True for m in received_msgs), (
        f"Bob did not receive encrypted secret across 4-node chain: {received_msgs}"
    )

    await node_a.stop()
    await node_r1.stop()
    await node_r2.stop()
    await node_b.stop()


@pytest.mark.asyncio
async def test_challenge_ring_topology_loop_prevention() -> None:
    """Stress test: Ring topology A <-> B <-> C <-> A.

    Broadcasting a message in a loop must be stopped by deduplication and TTL,
    preventing infinite broadcast storms.
    """
    node_a, trans_a = make_coord("NodeA")
    node_b, trans_b = make_coord("NodeB")
    node_c, trans_c = make_coord("NodeC")

    # Ring connections
    link_pair(node_a, trans_a, node_b, trans_b)
    link_pair(node_b, trans_b, node_c, trans_c)
    link_pair(node_c, trans_c, node_a, trans_a)

    await node_a.start()
    await node_b.start()
    await node_c.start()

    b_received: list[str] = []
    c_received: list[str] = []
    node_b.on_message_received = lambda s, m, enc: b_received.append(m)
    node_c.on_message_received = lambda s, m, enc: c_received.append(m)

    # Broadcast message from A
    msg_text = "Ring broadcast test message"
    await node_a.send_broadcast_message(msg_text)

    # Wait for propagation around the ring
    await asyncio.sleep(0.5)

    # Each node should have received the message exactly once!
    assert b_received.count(msg_text) == 1, (
        f"Node B received message {b_received.count(msg_text)} times"
    )
    assert c_received.count(msg_text) == 1, (
        f"Node C received message {c_received.count(msg_text)} times"
    )

    await node_a.stop()
    await node_b.stop()
    await node_c.stop()


def test_challenge_routing_table_shortest_path_and_thrash() -> None:
    """Stress test: Route table prioritizes shorter hop count and handles thrashing."""
    router = MeshRouter(local_peer_id=b"\x00" * 8)
    router.max_routes = 50

    dest = "target_dest_node"
    t0 = 1000.0
    # Route via 4 hops
    router.add_route(dest, "relay_far", hop_count=4, now=t0)
    assert router.get_next_hop(dest, now=t0) == "relay_far"

    # Route via 2 hops replaces it
    router.add_route(dest, "relay_closer", hop_count=2, now=t0 + 1.0)
    assert router.get_next_hop(dest, now=t0 + 1.0) == "relay_closer"

    # Route via 3 hops (worse) does NOT replace it
    router.add_route(dest, "relay_worse", hop_count=3, now=t0 + 2.0)
    assert router.get_next_hop(dest, now=t0 + 2.0) == "relay_closer"

    # Massive thrashing: add 1000 distinct routes rapidly
    for i in range(1000):
        router.add_route(
            f"dest_{i}", f"hop_{i % 5}", hop_count=(i % 4) + 1, now=t0 + 10.0 + i
        )

    # Capacity bound strictly enforced
    assert len(router.routes) <= 50


def test_challenge_adversarial_fragment_injection() -> None:
    """Stress test: FragmentReassembler handles malicious and corrupted inputs."""
    reassembler = FragmentReassembler(
        max_active_assemblies=5, max_fragments_per_assembly=10
    )
    sender = b"\xaa" * 8
    frag_id = b"\xbb" * 8

    # 1. Total <= 0
    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=0,
            total=0,
            original_message_type=MessageType.Message,
            chunk_data=b"x",
        )

    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=0,
            total=-5,
            original_message_type=MessageType.Message,
            chunk_data=b"x",
        )

    # 2. Index out of bounds
    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=5,
            total=5,
            original_message_type=MessageType.Message,
            chunk_data=b"x",
        )

    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=-1,
            total=5,
            original_message_type=MessageType.Message,
            chunk_data=b"x",
        )

    # 3. Exceed max fragments per assembly
    with pytest.raises(FragmentLimitExceededError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=0,
            total=11,
            original_message_type=MessageType.Message,
            chunk_data=b"x",
        )

    # 4. Fill up max assemblies capacity
    for i in range(5):
        reassembler._insert_chunk(
            sender_id=bytes([i] * 8),
            fragment_id=frag_id,
            index=0,
            total=2,
            original_message_type=MessageType.Message,
            chunk_data=b"part0",
        )
    assert reassembler.active_assembly_count == 5

    # 6th distinct assembly triggers LRU eviction of oldest assembly (sender 0)
    reassembler._insert_chunk(
        sender_id=b"\xff" * 8,
        fragment_id=frag_id,
        index=0,
        total=2,
        original_message_type=MessageType.Message,
        chunk_data=b"part0",
    )
    assert reassembler.active_assembly_count == 5
    # The oldest assembly (sender 0) must have been evicted
    assert (bytes([0] * 8), frag_id) not in reassembler._assemblies
    # The newest assembly (sender 0xff) must be present
    assert (b"\xff" * 8, frag_id) in reassembler._assemblies


def test_challenge_strict_ttl_boundaries() -> None:
    """Stress test: MeshRouter handles boundary TTL values correctly."""
    router = MeshRouter(local_peer_id=b"\x01" * 8, max_relay_ttl=5)
    dest_id = b"\x02" * 8

    # Case 1: TTL = 0 -> Must drop, neither process locally nor relay
    p0 = BitchatPacket.create(
        MessageType.Message, b"\x03" * 8, b"data0", recipient_id=dest_id, ttl=0
    )
    dec0 = router.evaluate_incoming(p0)
    assert dec0.should_process_locally is False
    assert dec0.packet_to_relay is None
    assert dec0.drop_reason is not None

    # Case 2: TTL = 1 destined for someone else -> Do not relay
    p1 = BitchatPacket.create(
        MessageType.Message, b"\x03" * 8, b"data1", recipient_id=dest_id, ttl=1
    )
    dec1 = router.evaluate_incoming(p1)
    assert dec1.should_process_locally is False
    assert dec1.packet_to_relay is None

    # Case 3: TTL = 2 destined for someone else -> Relayed with TTL = 1
    p2 = BitchatPacket.create(
        MessageType.Message, b"\x03" * 8, b"data2", recipient_id=dest_id, ttl=2
    )
    dec2 = router.evaluate_incoming(p2)
    assert dec2.packet_to_relay is not None
    assert dec2.packet_to_relay.ttl == 1

    # Case 4: Oversized TTL = 255 -> Clamped to max_relay_ttl (5) and decremented to 4
    p_large = BitchatPacket.create(
        MessageType.Message, b"\x03" * 8, b"data3", recipient_id=dest_id, ttl=255
    )
    dec_large = router.evaluate_incoming(p_large)
    assert dec_large.packet_to_relay is not None
    assert dec_large.packet_to_relay.ttl == 4


@pytest.mark.asyncio
async def test_challenge_cache_prune_task_stress() -> None:
    """Stress test: Periodic prune task runs concurrently without deadlocks."""
    coord, _ = make_coord("PruneStressNode")
    await coord.start()

    # Fill components with items
    now = time.time()
    for i in range(100):
        coord.mesh_router.add_route(f"dest_{i}", f"hop_{i}", now=now - 400.0)
        pkt = BitchatPacket.create(
            MessageType.Message, bytes([i % 250] * 8), b"payload", ttl=3
        )
        coord.packet_deduplicator.record(pkt, now=now - 400.0)

    # Run prune_caches multiple times concurrently
    await asyncio.gather(
        asyncio.to_thread(coord.prune_caches),
        asyncio.to_thread(coord.prune_caches),
        asyncio.to_thread(coord.prune_caches),
    )

    # Routes older than 300s should be pruned
    assert len(coord.mesh_router.routes) == 0

    await coord.stop()
    assert coord._prune_task is None
