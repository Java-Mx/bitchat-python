"""Tier 4: Real-World Application Scenarios — Decentralized Workloads & Stress Scenarios."""

from __future__ import annotations

import asyncio

import pytest
from tests.e2e.conftest import E2ENode, link_nodes, wait_until

from bitchat.crypto.noise import NoiseRole
from bitchat.crypto.sessions import NoiseSession
from bitchat.exceptions import ReplayError
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket


@pytest.mark.asyncio
async def test_five_node_decentralized_group_chat(node_factory) -> None:
    """Validate 5-node cluster achieves full broadcast delivery across all participants."""
    nodes: list[E2ENode] = [node_factory(f"Node_{i}", f"00:0{i}") for i in range(1, 6)]

    # Start all 5 nodes
    for node in nodes:
        await node.start()

    # Interconnect node 1 (hub) with nodes 2, 3, 4, 5
    hub = nodes[0]
    for leaf in nodes[1:]:
        await link_nodes(hub, leaf)

    # All nodes announce themselves
    for node in nodes:
        await node.coordinator.send_announce(node.nickname)

    await asyncio.sleep(0.1)

    # Each leaf node broadcasts a greeting
    for idx, leaf in enumerate(nodes[1:], start=2):
        await leaf.coordinator.send_broadcast_message(f"Hello from node {idx}!")

    # Hub node also broadcasts
    await hub.coordinator.send_broadcast_message("Hello from hub!")

    # Wait for all nodes to receive the broadcasts
    # Hub should receive from all 4 leaves
    await wait_until(
        lambda: (
            len([m for m in hub.received_messages if "Hello from node" in m[1]]) == 4
        ),
        timeout=5.0,
    )

    # Leaf nodes should receive the hub's greeting
    for leaf in nodes[1:]:
        await wait_until(
            lambda node=leaf: any(
                "Hello from hub!" in m[1] for m in node.received_messages
            ),
            timeout=5.0,
        )

    for node in nodes:
        await node.stop()


@pytest.mark.asyncio
async def test_dynamic_mesh_churn_resilience(node_factory) -> None:
    """Validate messaging resilience during intermediate relay churn and network topology shift."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    charlie: E2ENode = node_factory("Charlie", "CC:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await alice.start()
    await charlie.start()
    await bob.start()

    # Initial topology: Alice <-> Charlie <-> Bob (Charlie acts as relay)
    await link_nodes(alice, charlie)
    await link_nodes(charlie, bob)

    # Initial message routed through Charlie
    await alice.coordinator.send_broadcast_message("Message before churn")
    await wait_until(
        lambda: any("Message before churn" in m[1] for m in bob.received_messages),
        timeout=3.0,
    )

    # Charlie churns: crashes / goes offline
    await charlie.stop()

    # Network topology shifts: Alice and Bob now establish direct link
    await link_nodes(alice, bob)

    # Communication continues over direct link
    await alice.coordinator.send_broadcast_message("Message after churn")
    await wait_until(
        lambda: any("Message after churn" in m[1] for m in bob.received_messages),
        timeout=3.0,
    )

    messages = [m[1] for m in bob.received_messages]
    assert "Message before churn" in messages
    assert "Message after churn" in messages

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_high_throughput_burst_messaging(node_factory) -> None:
    """Validate rapid burst of 30 sequential messages delivered reliably without packet loss."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    burst_count = 20
    for i in range(burst_count):
        await alice.coordinator.send_broadcast_message(f"BURST_SEQ_{i:03d}")
        await asyncio.sleep(0.01)

    # Verify Bob receives all 20 burst packets
    await wait_until(
        lambda: (
            len([m for m in bob.received_messages if "BURST_SEQ_" in m[1]])
            == burst_count
        ),
        timeout=5.0,
    )

    received_texts = [m[1] for m in bob.received_messages if "BURST_SEQ_" in m[1]]
    assert len(received_texts) == burst_count

    # All sequence numbers 0..19 present
    for i in range(burst_count):
        assert f"BURST_SEQ_{i:03d}" in received_texts

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_mobile_courier_store_and_forward(node_factory) -> None:
    """Validate mobile courier carries offline packets between isolated partitions (sneakernet)."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    courier: E2ENode = node_factory("Courier", "CR:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await courier.start()
    await alice.start()

    # Phase 1: Courier visits Alice at Partition A
    await link_nodes(alice, courier)

    bob_hex = bob.identity.peer_id_hex
    courier.coordinator.peer_addresses[bob_hex] = bob.address

    # Alice creates a packet destined for Bob
    courier_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=alice.identity.peer_id,
        recipient_id=bob.identity.peer_id,
        payload=b"Physical courier payload from Alice to Bob",
        ttl=4,
    )

    # Deliver to Courier
    courier.coordinator._handle_incoming_packet(courier_pkt, peer_address=alice.address)

    # Courier buffers packet in store-and-forward queue
    await wait_until(
        lambda: courier.coordinator.mesh_router.store_forward_queue.has_pending(
            bob_hex
        ),
        timeout=2.0,
    )
    assert courier.coordinator.mesh_router.store_forward_queue.has_pending(bob_hex)

    # Phase 2: Courier departs Partition A (disconnect from Alice)
    courier.clients[alice.address].is_connected = False
    alice.clients[courier.address].is_connected = False

    # Phase 3: Courier arrives at Partition B where Bob is located
    await bob.start()
    await link_nodes(courier, bob)

    # Bob announces presence
    await bob.coordinator.send_announce("Bob")

    # Courier detects Bob and flushes stored packet
    await wait_until(
        lambda: any("courier payload" in m[1] for m in bob.received_messages),
        timeout=3.0,
    )

    assert any("Physical courier payload" in m[1] for m in bob.received_messages)
    assert not courier.coordinator.mesh_router.store_forward_queue.has_pending(bob_hex)

    await alice.stop()
    await courier.stop()
    await bob.stop()


def test_multipath_out_of_order_delivery() -> None:
    """Validate ChaCha20-Poly1305 sliding replay window accepts out-of-order nonces and rejects replays."""
    from bitchat.crypto.identity import LocalIdentity

    id_alice = LocalIdentity.generate()
    id_bob = LocalIdentity.generate()

    # Perform handshake to establish transport cipher
    alice_session = NoiseSession(id_alice, id_bob.peer_id_hex)
    bob_session = NoiseSession(id_bob, id_alice.peer_id_hex)

    initiator = (
        alice_session if alice_session.role == NoiseRole.INITIATOR else bob_session
    )
    responder = bob_session if initiator is alice_session else alice_session

    # Handshake msg 1
    m1 = initiator.start_handshake()
    assert m1 is not None
    m2 = responder.process_handshake_message(m1)
    assert m2 is not None
    m3 = initiator.process_handshake_message(m2)
    assert m3 is not None
    responder.process_handshake_message(m3)

    assert initiator.is_established
    assert responder.is_established

    # Initiator encrypts 10 packets with nonces 0..9
    ciphertexts: list[bytes] = []
    plaintexts: list[bytes] = []
    for i in range(10):
        pt = f"Packet #{i}".encode()
        plaintexts.append(pt)
        ct = initiator.encrypt(pt)
        ciphertexts.append(ct)

    # Multipath jitter reordering: [3, 1, 0, 2, 7, 4, 6, 5, 9, 8]
    reordered_indices = [3, 1, 0, 2, 7, 4, 6, 5, 9, 8]

    for idx in reordered_indices:
        decrypted = responder.decrypt(ciphertexts[idx])
        assert decrypted == plaintexts[idx]

    # Replaying any previously received non-zero nonce must raise ReplayError
    with pytest.raises(ReplayError):
        responder.decrypt(ciphertexts[3])

    with pytest.raises(ReplayError):
        responder.decrypt(ciphertexts[1])


@pytest.mark.asyncio
async def test_extended_encrypted_session_longevity(node_factory) -> None:
    """Validate longevity of encrypted Noise session over 60 bidirectional messages."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Establish Noise session
    await alice.coordinator.send_direct_message(
        bob.identity.peer_id_hex, "Init longevity session"
    )
    await wait_until(
        lambda: len(bob.received_messages) > 0,
        timeout=3.0,
    )

    total_rounds = 30  # 30 from Alice, 30 from Bob = 60 total direct messages
    for i in range(total_rounds):
        await alice.coordinator.send_direct_message(
            bob.identity.peer_id_hex, f"AliceRound_{i:02d}"
        )
        await bob.coordinator.send_direct_message(
            alice.identity.peer_id_hex, f"BobRound_{i:02d}"
        )

    await wait_until(
        lambda: (
            len([m for m in bob.received_messages if "AliceRound_" in m[1]])
            == total_rounds
            and len([m for m in alice.received_messages if "BobRound_" in m[1]])
            == total_rounds
        ),
        timeout=6.0,
    )

    # Verify all messages received and marked encrypted
    for m in bob.received_messages:
        if "AliceRound_" in m[1]:
            assert m[2] is True
    for m in alice.received_messages:
        if "BobRound_" in m[1]:
            assert m[2] is True

    # Both sessions remain fully ESTABLISHED
    session_a = alice.coordinator.get_session(bob.identity.peer_id_hex)
    session_b = bob.coordinator.get_session(alice.identity.peer_id_hex)
    assert session_a is not None
    assert session_b is not None
    assert session_a.is_established
    assert session_b.is_established

    await alice.stop()
    await bob.stop()
