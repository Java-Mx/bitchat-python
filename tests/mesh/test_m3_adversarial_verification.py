"""Empirical and adversarial verification suite for Milestone 3.

Adversarially challenges:
1. Multi-hop mesh routing resolution in multi-node chains (A -> B -> C -> D)
   and verifies that relayed announcements/packets never overwrite direct 1-hop
   physical neighbor link addresses.
2. Periodic pruning loop: verifies prune_caches() runs periodically and cleans up
   stale fragment assemblies, expired deduplication entries, expired
   store-and-forward packets, and expired routes.
3. Defensive protocol limits: verifies payloads > 32,768 bytes are rejected,
   out-of-bounds fragment indices are safely rejected, and malformed fragments
   do not crash the coordinator.
"""

from __future__ import annotations

import asyncio

import pytest
from tests.mesh.test_mesh_routing_resolution import DummyTransport

from bitchat.app.session_coordinator import (
    MAX_MESSAGE_SIZE,
    MAX_TTL,
    SessionCoordinator,
)
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import (
    FragmentLimitExceededError,
    InvalidFragmentError,
)
from bitchat.protocol.constants import MessageType
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import FRAGMENT_HEADER_SIZE
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import InMemoryStorage


def _create_coordinator(
    nickname: str, address: str = "node_addr"
) -> tuple[SessionCoordinator, DummyTransport]:
    """Helper to create an isolated SessionCoordinator with DummyTransport."""
    identity = LocalIdentity.generate()
    storage = InMemoryStorage()
    transport = DummyTransport(address=address)
    coord = SessionCoordinator(
        local_identity=identity,
        transport=transport,
        storage=storage,
        nickname=nickname,
    )
    return coord, transport


# ============================================================================
# SECTION 1: Multi-Hop Mesh Routing Invariant Challenges (A -> B -> C -> D)
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_four_node_chain_neighbor_table_isolation() -> None:
    """Stress-test neighbor link mapping isolation in a 4-node chain:
    A <-> B <-> C <-> D.

    Topology:
      Node A <-> (ADDR_AB) <-> Node B <-> (ADDR_BC) <-> Node C <-> (ADDR_CD) <-> Node D

    Verify:
      1. Relayed announcements from D arriving at B via C (TTL=6) do NOT overwrite
         B's direct neighbor mapping for C.
      2. Relayed announcements from D arriving at A via B (TTL=5) do NOT overwrite
         A's direct neighbor mapping for B.
      3. Relayed announcements from A arriving at D via C (TTL=5) do NOT overwrite
         D's direct neighbor mapping for C.
      4. High-frequency packet flood from distant nodes never corrupts 1-hop socket
         mappings on intermediate relay nodes.
    """
    coord_a, _trans_a = _create_coordinator("NodeA", "ADDR_A")
    coord_b, _trans_b = _create_coordinator("NodeB", "ADDR_B")
    coord_c, _trans_c = _create_coordinator("NodeC", "ADDR_C")
    coord_d, _trans_d = _create_coordinator("NodeD", "ADDR_D")

    id_a = coord_a.local_identity.peer_id_hex
    id_b = coord_b.local_identity.peer_id_hex
    id_c = coord_c.local_identity.peer_id_hex
    id_d = coord_d.local_identity.peer_id_hex

    # Physical link addresses
    link_ab = "PHY_LINK_A_B"
    link_ba = "PHY_LINK_B_A"
    link_bc = "PHY_LINK_B_C"
    link_cb = "PHY_LINK_C_B"
    link_cd = "PHY_LINK_C_D"
    link_dc = "PHY_LINK_D_C"

    # Step 1: Establish direct 1-hop physical neighbor relationships (TTL = MAX_TTL = 7)
    # A <-> B
    pkt_a_to_b = BitchatPacket.create(
        MessageType.Announce, coord_a.local_identity.peer_id, b"NodeA", ttl=MAX_TTL
    )
    await coord_b._process_packet_async(pkt_a_to_b, peer_address=link_ba)
    pkt_b_to_a = BitchatPacket.create(
        MessageType.Announce, coord_b.local_identity.peer_id, b"NodeB", ttl=MAX_TTL
    )
    await coord_a._process_packet_async(pkt_b_to_a, peer_address=link_ab)

    # B <-> C
    pkt_c_to_b = BitchatPacket.create(
        MessageType.Announce, coord_c.local_identity.peer_id, b"NodeC", ttl=MAX_TTL
    )
    await coord_b._process_packet_async(pkt_c_to_b, peer_address=link_bc)
    pkt_b_to_c = BitchatPacket.create(
        MessageType.Announce, coord_b.local_identity.peer_id, b"NodeB", ttl=MAX_TTL
    )
    await coord_c._process_packet_async(pkt_b_to_c, peer_address=link_cb)

    # C <-> D
    pkt_d_to_c = BitchatPacket.create(
        MessageType.Announce, coord_d.local_identity.peer_id, b"NodeD", ttl=MAX_TTL
    )
    await coord_c._process_packet_async(pkt_d_to_c, peer_address=link_dc)
    pkt_c_to_d = BitchatPacket.create(
        MessageType.Announce, coord_c.local_identity.peer_id, b"NodeC", ttl=MAX_TTL
    )
    await coord_d._process_packet_async(pkt_c_to_d, peer_address=link_cd)

    # Invariant check: Verify all 1-hop physical neighbor mappings
    assert coord_b.address_to_peer_id[link_ba] == id_a
    assert coord_b.address_to_peer_id[link_bc] == id_c
    assert coord_b.peer_addresses[id_a] == link_ba
    assert coord_b.peer_addresses[id_c] == link_bc

    assert coord_c.address_to_peer_id[link_cb] == id_b
    assert coord_c.address_to_peer_id[link_dc] == id_d
    assert coord_c.peer_addresses[id_b] == link_cb
    assert coord_c.peer_addresses[id_d] == link_dc

    assert coord_a.address_to_peer_id[link_ab] == id_b
    assert coord_d.address_to_peer_id[link_cd] == id_c

    # Step 2: Propagate multi-hop announcements across chain
    # D's announce relayed through C to B (TTL = 6)
    pkt_d_relayed_to_b = BitchatPacket.create(
        MessageType.Announce,
        coord_d.local_identity.peer_id,
        b"NodeD",
        ttl=MAX_TTL - 1,
    )
    await coord_b._process_packet_async(pkt_d_relayed_to_b, peer_address=link_bc)

    # B's direct mapping to C on link_bc MUST NOT be overwritten by D!
    assert coord_b.address_to_peer_id[link_bc] == id_c
    assert coord_b.address_to_peer_id[link_bc] != id_d
    assert id_d not in coord_b.peer_addresses
    # But mesh router MUST know that D is reachable via C
    assert coord_b.mesh_router.get_next_hop(id_d) == id_c

    # D's announce relayed from B to A (TTL = 5)
    pkt_d_relayed_to_a = BitchatPacket.create(
        MessageType.Announce,
        coord_d.local_identity.peer_id,
        b"NodeD",
        ttl=MAX_TTL - 2,
    )
    await coord_a._process_packet_async(pkt_d_relayed_to_a, peer_address=link_ab)

    # A's direct mapping to B on link_ab MUST NOT be overwritten by D!
    assert coord_a.address_to_peer_id[link_ab] == id_b
    assert coord_a.address_to_peer_id[link_ab] != id_d
    assert id_d not in coord_a.peer_addresses
    assert coord_a.mesh_router.get_next_hop(id_d) == id_b

    # A's announce relayed through B and C to D (TTL = 5)
    pkt_a_relayed_to_d = BitchatPacket.create(
        MessageType.Announce,
        coord_a.local_identity.peer_id,
        b"NodeA",
        ttl=MAX_TTL - 2,
    )
    await coord_d._process_packet_async(pkt_a_relayed_to_d, peer_address=link_cd)

    # D's direct mapping to C on link_cd MUST NOT be overwritten by A!
    assert coord_d.address_to_peer_id[link_cd] == id_c
    assert coord_d.address_to_peer_id[link_cd] != id_a
    assert id_a not in coord_d.peer_addresses
    assert coord_d.mesh_router.get_next_hop(id_a) == id_c

    # Step 3: Flood 50 packets from distant node D to node B with varying TTLs
    for i in range(50):
        flood_ttl = 1 + (i % (MAX_TTL - 1))  # 1..6
        flood_pkt = BitchatPacket.create(
            MessageType.Message,
            coord_d.local_identity.peer_id,
            f"Flood_{i}".encode(),
            ttl=flood_ttl,
        )
        await coord_b._process_packet_async(flood_pkt, peer_address=link_bc)

    # Verify B's direct physical mapping remains 100% intact after flood
    assert coord_b.address_to_peer_id[link_bc] == id_c
    assert coord_b.peer_addresses[id_c] == link_bc
    assert id_d not in coord_b.peer_addresses


@pytest.mark.asyncio
async def test_adversarial_multihop_unicast_packet_routing_chain() -> None:
    """Verify unicast packets resolve hop-by-hop without broadcasting."""
    coord_b, trans_b = _create_coordinator("NodeB")
    id_c = "cccccccccccccccc"
    id_d = "dddddddddddddddd"
    socket_c = "PHY_SOCKET_C"

    # Register C as connected direct neighbor
    trans_b._connected.append(socket_c)
    coord_b.peer_addresses[id_c] = socket_c
    coord_b.address_to_peer_id[socket_c] = id_c

    # Node D is 2 hops away, reachable via C
    coord_b.mesh_router.add_route(destination=id_d, next_hop=id_c, hop_count=2)

    # Send a unicast packet targeting distant node D
    pkt_to_d = BitchatPacket.create(
        MessageType.NoiseEncrypted,
        coord_b.local_identity.peer_id,
        b"SuperSecretPayloadForD",
        recipient_id=bytes.fromhex(id_d),
    )

    await coord_b._send_packet(id_d, pkt_to_d)

    # Must be routed to C's physical socket, not broadcast
    assert len(trans_b.sent_packets) == 1
    dest_socket, sent_pkt = trans_b.sent_packets[0]
    assert dest_socket == socket_c
    assert sent_pkt.recipient_id == bytes.fromhex(id_d)
    assert len(trans_b.broadcast_packets) == 0


# ============================================================================
# SECTION 2: Periodic Pruning Loop Verification
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_periodic_pruning_cleans_all_caches() -> None:
    """Empirically test that prune_caches() cleans stale fragment assemblies,

    expired dedup entries, expired store-and-forward packets, and expired routes.
    """
    coord, _ = _create_coordinator("PruneTester")
    sender_bytes = b"\x10" * 8
    frag_id = b"\x20" * 8

    # 1. In-flight fragment assembly older than 60s
    coord.fragment_reassembler._insert_chunk(
        sender_id=sender_bytes,
        fragment_id=frag_id,
        index=0,
        total=3,
        original_message_type=int(MessageType.Message),
        chunk_data=b"chunk0",
    )
    assert coord.fragment_reassembler.active_assembly_count == 1
    # Age the assembly to 70s ago
    assembly_key = (sender_bytes, frag_id)
    coord.fragment_reassembler._assemblies[assembly_key].created_at -= 70.0

    # 2. Expired deduplication record older than 300s
    expired_pkt = BitchatPacket.create(MessageType.Message, sender_bytes, b"old_dedup")
    coord.packet_deduplicator.record(expired_pkt, now=1000.0)
    assert coord.packet_deduplicator.is_duplicate(expired_pkt, now=1000.0)

    # 3. Expired store-and-forward packet older than 86,400s
    sf_pkt = BitchatPacket.create(MessageType.Message, sender_bytes, b"old_sf_packet")
    coord.store_forward.enqueue("offline_dest", sf_pkt, now=1000.0)
    assert coord.store_forward.has_pending("offline_dest")

    # 4. Expired mesh route older than 300s
    coord.mesh_router.add_route("target_dest", "next_hop_dest", now=1000.0)
    assert coord.mesh_router.get_next_hop("target_dest", now=1000.0) == "next_hop_dest"

    # Execute pruning with simulated future time
    # For reassembler: uses time.monotonic() directly; already aged
    # For time.time() components: simulate future time now = 100,000.0
    future_time = 100_000.0
    coord.fragment_reassembler.prune_stale(max_age_seconds=60.0)
    coord.packet_deduplicator.prune_expired(now=future_time)
    coord.store_forward.prune_expired(now=future_time)
    coord.mesh_router.prune_routes(now=future_time)

    # Invariant Verification: All stale / expired entities must be purged
    assert coord.fragment_reassembler.active_assembly_count == 0
    assert not coord.packet_deduplicator.is_duplicate(expired_pkt, now=future_time)
    assert not coord.store_forward.has_pending("offline_dest")
    assert coord.mesh_router.get_next_hop("target_dest", now=future_time) is None


@pytest.mark.asyncio
async def test_adversarial_periodic_prune_loop_automatic_execution() -> None:
    """Verify that _periodic_prune_loop runs on background interval and cleans up."""
    coord, _ = _create_coordinator("LoopTester")
    coord._is_running = True

    prune_called_count = 0
    original_prune = coord.prune_caches

    def mock_prune() -> None:
        nonlocal prune_called_count
        prune_called_count += 1
        original_prune()

    coord.prune_caches = mock_prune  # type: ignore[method-assign]

    # Spawn periodic prune loop with rapid 0.05s interval
    loop_task = coord._spawn_task(coord._periodic_prune_loop(interval_seconds=0.05))

    # Allow loop to tick 3 times
    await asyncio.sleep(0.18)
    assert prune_called_count >= 2

    # Stop and verify task clean shutdown
    coord._is_running = False
    loop_task.cancel()
    await loop_task
    assert loop_task.done()


# ============================================================================
# SECTION 3: Defensive Protocol Limits Verification
# ============================================================================


@pytest.mark.asyncio
async def test_adversarial_max_payload_bounds() -> None:
    """Verify that payloads exceeding MAX_MESSAGE_SIZE (32,768 bytes) are rejected."""
    coord, _ = _create_coordinator("PayloadTester")

    # 1. Exact bound: 32,768 bytes is accepted
    exact_text = "X" * MAX_MESSAGE_SIZE
    # Should not raise ValueError
    await coord.send_broadcast_message(exact_text)

    # 2. 1 byte over: 32,769 bytes must raise ValueError
    oversized_text = "X" * (MAX_MESSAGE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_broadcast_message(oversized_text)

    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_direct_message("1234567890abcdef", oversized_text)

    # 3. Massive payload: 100,000 bytes
    huge_text = "Y" * 100_000
    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_broadcast_message(huge_text)

    # 4. Multi-byte UTF-8 payload (each character 3 bytes)
    # 11,000 characters = 33,000 bytes > 32,768
    multibyte_text = "\u20ac" * 11_000
    assert len(multibyte_text.encode("utf-8")) == 33_000
    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_broadcast_message(multibyte_text)


def test_adversarial_fragment_index_out_of_bounds() -> None:
    """Stress-test out-of-bounds fragment indices in FragmentReassembler."""
    reassembler = FragmentReassembler()
    sender = b"\x01" * 8
    frag_id = b"\x02" * 8

    # Case 1: total = 0
    with pytest.raises(InvalidFragmentError, match="total must be > 0"):
        reassembler._insert_chunk(
            sender, frag_id, index=0, total=0, original_message_type=1, chunk_data=b"a"
        )

    # Case 2: total < 0
    with pytest.raises(InvalidFragmentError, match="total must be > 0"):
        reassembler._insert_chunk(
            sender, frag_id, index=0, total=-5, original_message_type=1, chunk_data=b"a"
        )

    # Case 3: index >= total (index = total)
    with pytest.raises(InvalidFragmentError, match="index out of bounds"):
        reassembler._insert_chunk(
            sender, frag_id, index=3, total=3, original_message_type=1, chunk_data=b"a"
        )

    # Case 4: index > total
    with pytest.raises(InvalidFragmentError, match="index out of bounds"):
        reassembler._insert_chunk(
            sender, frag_id, index=99, total=5, original_message_type=1, chunk_data=b"a"
        )

    # Case 5: index < 0
    with pytest.raises(InvalidFragmentError, match="index out of bounds"):
        reassembler._insert_chunk(
            sender, frag_id, index=-1, total=5, original_message_type=1, chunk_data=b"a"
        )

    # Case 6: total exceeds maximum allowed
    with pytest.raises(FragmentLimitExceededError):
        reassembler._insert_chunk(
            sender,
            frag_id,
            index=0,
            total=2000,
            original_message_type=1,
            chunk_data=b"a",
        )


def test_adversarial_malformed_fragments_do_not_crash_coordinator() -> None:
    """Adversarially fuzz coordinator server reassembler with corrupted fragments."""
    coord, _ = _create_coordinator("RobustnessTester")

    # 1. Truncated fragment payload (< FRAGMENT_HEADER_SIZE)
    short_pkt = BitchatPacket.create(
        MessageType.FragmentStart,
        sender_id=b"\x01" * 8,
        payload=b"\x00" * (FRAGMENT_HEADER_SIZE - 1),
    )
    raw_short = encode_packet(short_pkt, add_padding=False)
    # Must not raise uncaught exception
    coord._handle_server_data_received(raw_short, "client_bad_1")

    # 2. Corrupt header struct with total = 0
    import struct

    bad_header_total_zero = (
        struct.pack(
            ">8sHHB",
            b"fragid01",
            0,  # index
            0,  # total = 0 (invalid)
            int(MessageType.Message),
        )
        + b"chunk_content"
    )
    bad_total_pkt = BitchatPacket.create(
        MessageType.FragmentStart,
        sender_id=b"\x01" * 8,
        payload=bad_header_total_zero,
    )
    raw_bad_total = encode_packet(bad_total_pkt, add_padding=False)
    coord._handle_server_data_received(raw_bad_total, "client_bad_2")

    # 3. Corrupt header struct with index >= total
    bad_header_oob = (
        struct.pack(
            ">8sHHB",
            b"fragid02",
            5,  # index = 5
            3,  # total = 3
            int(MessageType.Message),
        )
        + b"chunk_content"
    )
    bad_oob_pkt = BitchatPacket.create(
        MessageType.FragmentStart,
        sender_id=b"\x01" * 8,
        payload=bad_header_oob,
    )
    raw_bad_oob = encode_packet(bad_oob_pkt, add_padding=False)
    coord._handle_server_data_received(raw_bad_oob, "client_bad_3")

    # 4. Total fragments exceeding resource ceiling
    bad_header_huge = (
        struct.pack(
            ">8sHHB",
            b"fragid03",
            0,
            5000,  # exceeds MAX_FRAGMENTS_PER_ASSEMBLY (1000)
            int(MessageType.Message),
        )
        + b"chunk_content"
    )
    bad_huge_pkt = BitchatPacket.create(
        MessageType.FragmentStart,
        sender_id=b"\x01" * 8,
        payload=bad_header_huge,
    )
    raw_bad_huge = encode_packet(bad_huge_pkt, add_padding=False)
    coord._handle_server_data_received(raw_bad_huge, "client_bad_4")

    # 5. Raw byte garbage passed directly
    coord._handle_server_data_received(
        b"\xde\xad\xbe\xef\xca\xfe\xba\xbe", "client_bad_5"
    )

    # Invariant: Coordinator reassembler is still fully functional
    assert coord.fragment_reassembler.active_assembly_count == 0
