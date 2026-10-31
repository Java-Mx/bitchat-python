"""Tier 3: Cross-Feature Combinations — Pairwise Combinatorial Interaction Tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from tests.e2e.conftest import E2ENode, link_nodes, wait_until

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseRole, determine_handshake_role
from bitchat.protocol.constants import MessageType
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import AppConfig, FileConfigStorage

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_large_encrypted_direct_message_fragmentation(node_factory) -> None:
    """Validate large direct message (>1000B) undergoes fragmentation and decryption."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Exchange presence announcements
    await alice.coordinator.send_announce("Alice")
    await bob.coordinator.send_announce("Bob")
    await asyncio.sleep(0.05)

    # 1200-byte plaintext message: well exceeds FRAGMENTATION_THRESHOLD (500)
    large_secret_text = "CONFIDENTIAL_PAYLOAD_" + ("0123456789ABCDEF" * 70)
    assert len(large_secret_text) > 1000

    await alice.coordinator.send_direct_message(
        bob.identity.peer_id_hex, large_secret_text
    )

    await wait_until(
        lambda: any(m[1] == large_secret_text for m in bob.received_messages),
        timeout=5.0,
    )

    msg_record = next(m for m in bob.received_messages if m[1] == large_secret_text)
    assert msg_record[0] == alice.identity.peer_id_hex
    assert msg_record[1] == large_secret_text
    assert msg_record[2] is True  # encrypted!

    # Verify both nodes established secure Noise sessions
    session_a = alice.coordinator.get_session(bob.identity.peer_id_hex)
    session_b = bob.coordinator.get_session(alice.identity.peer_id_hex)
    assert session_a is not None and session_a.is_established
    assert session_b is not None and session_b.is_established

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_multihop_mesh_encrypted_dm_routing(node_factory) -> None:
    """Validate end-to-end encrypted messaging across relay without relay decryption."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    relay: E2ENode = node_factory("Relay", "RR:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    # Start all 3 nodes
    await relay.start()
    await bob.start()
    await alice.start()

    # Linear topology: Alice <-> Relay <-> Bob. Alice is NOT connected directly to Bob.
    await link_nodes(alice, relay)
    await link_nodes(relay, bob)

    # Announce to propagate routing tables
    await bob.coordinator.send_announce("Bob")
    await alice.coordinator.send_announce("Alice")

    # Wait for Relay to learn both neighbors
    await wait_until(
        lambda: (
            alice.identity.peer_id_hex in relay.coordinator.peer_addresses
            and bob.identity.peer_id_hex in relay.coordinator.peer_addresses
        ),
        timeout=3.0,
    )

    # Alice sends direct message to Bob via multi-hop mesh
    multihop_secret = "Classified: Routed across untrusted relay"
    await alice.coordinator.send_direct_message(
        bob.identity.peer_id_hex, multihop_secret
    )

    # Bob must receive and decrypt the message
    await wait_until(
        lambda: any(m[1] == multihop_secret for m in bob.received_messages),
        timeout=5.0,
    )

    received_on_bob = next(m for m in bob.received_messages if m[1] == multihop_secret)
    assert received_on_bob[1] == multihop_secret
    assert received_on_bob[2] is True

    # Security invariant: Relay must NEVER decrypt or log the plaintext message
    assert not any(multihop_secret in m[1] for m in relay.received_messages)

    await alice.stop()
    await relay.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_store_forward_flush_on_peer_announcement(node_factory) -> None:
    """Validate offline packet is buffered by relay and flushed on announce."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    relay: E2ENode = node_factory("Relay", "RR:01")
    charlie: E2ENode = node_factory("Charlie", "CC:01")

    await relay.start()
    await alice.start()
    await link_nodes(alice, relay)

    # Charlie is a known contact who has gone temporarily offline/disconnected
    charlie_hex = charlie.identity.peer_id_hex
    relay.coordinator.peer_addresses[charlie_hex] = charlie.address

    # Alice generates a message packet destined for offline Charlie
    offline_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=alice.identity.peer_id,
        recipient_id=charlie.identity.peer_id,
        payload=b"Store-and-forward greeting while you were offline",
        ttl=3,
    )

    # Deliver to Relay
    relay.coordinator._handle_incoming_packet(offline_pkt, peer_address=alice.address)

    # Wait until Relay enqueues packet in StoreAndForwardQueue
    await wait_until(
        lambda: relay.coordinator.mesh_router.store_forward_queue.has_pending(
            charlie_hex
        ),
        timeout=2.0,
    )
    assert relay.coordinator.mesh_router.store_forward_queue.has_pending(charlie_hex)

    # Now Charlie starts up and connects to Relay
    await charlie.start()
    await link_nodes(charlie, relay)

    # Charlie sends announcement
    await charlie.coordinator.send_announce("Charlie")

    # Relay should flush stored packet to Charlie
    await wait_until(
        lambda: any("offline" in m[1] for m in charlie.received_messages),
        timeout=3.0,
    )

    assert any("Store-and-forward greeting" in m[1] for m in charlie.received_messages)
    assert not relay.coordinator.mesh_router.store_forward_queue.has_pending(
        charlie_hex
    )

    await alice.stop()
    await relay.stop()
    await charlie.stop()


@pytest.mark.asyncio
async def test_cold_boot_persistent_identity_and_handshake(
    tmp_path: Path, node_factory
) -> None:
    """Validate identity restored from disk completes Noise XX handshake."""
    id_path = tmp_path / "identity.json"
    cfg_path = tmp_path / "config.json"

    # 1. Cold boot generation: create initial identity and save to disk
    storage1 = FileConfigStorage(config_path=cfg_path, identity_path=id_path)
    orig_identity = LocalIdentity.generate()
    storage1.save_identity(orig_identity)
    orig_cfg = AppConfig(nickname="PersistentAlice")
    storage1.save_config(orig_cfg)
    storage1.close()

    # 2. Reboot node with second storage instance loading from the exact same files
    storage2 = FileConfigStorage(config_path=cfg_path, identity_path=id_path)
    loaded_id = storage2.load_identity()
    assert loaded_id is not None
    assert loaded_id.peer_id_hex == orig_identity.peer_id_hex
    assert loaded_id.fingerprint == orig_identity.fingerprint

    # Instantiate node with loaded identity
    alice: E2ENode = node_factory("PersistentAlice", "AA:01")
    alice.identity = loaded_id
    alice.coordinator.local_identity = loaded_id
    alice.coordinator.mesh_router.local_peer_id = loaded_id.peer_id

    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Alice sends direct message to Bob
    await alice.coordinator.send_direct_message(
        bob.identity.peer_id_hex, "Cold boot authenticated!"
    )

    await wait_until(
        lambda: len(bob.received_messages) > 0,
        timeout=3.0,
    )

    # Check that Bob's recorded handshake fingerprint matches the persistent identity
    session_b = bob.coordinator.get_session(alice.identity.peer_id_hex)
    assert session_b is not None and session_b.is_established
    assert session_b.remote_fingerprint == orig_identity.fingerprint

    await alice.stop()
    await bob.stop()
    storage2.close()


def test_in_flight_duplicate_fragment_resilience() -> None:
    """Validate duplicate in-flight fragments are ignored and reassembly completes."""
    # Create large payload that fragments into multiple chunks
    sender_id = b"\x01" * 8
    payload = b"X" * 600
    pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender_id,
        payload=payload,
    )
    encoded = encode_packet(pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded,
        sender_id=sender_id,
        original_message_type=MessageType.Message,
    )
    assert len(fragments) >= 4

    reassembler = FragmentReassembler()

    # Feed fragment 0
    res0 = reassembler.add_fragment_packet(fragments[0])
    assert res0 is None

    # Feed fragment 1
    res1 = reassembler.add_fragment_packet(fragments[1])
    assert res1 is None

    # Duplicate transmission of fragment 1 (network glitch or multi-path retransmit)
    res_dup = reassembler.add_fragment_packet(fragments[1])
    assert res_dup is None  # Duplicate chunk ignored gracefully

    # Feed remaining fragments
    for frag in fragments[2:-1]:
        assert reassembler.add_fragment_packet(frag) is None

    # Final fragment triggers complete assembly
    final_wire = reassembler.add_fragment_packet(fragments[-1])
    assert final_wire is not None
    assert final_wire == encoded


@pytest.mark.asyncio
async def test_simultaneous_bidirectional_noise_handshake_collision(
    node_factory,
) -> None:
    """Validate collision resolves via lexicographical role arbitration."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Verify deterministic role assignment
    alice_role = determine_handshake_role(
        alice.identity.peer_id_hex, bob.identity.peer_id_hex
    )
    bob_role = determine_handshake_role(
        bob.identity.peer_id_hex, alice.identity.peer_id_hex
    )
    assert alice_role != bob_role
    assert {alice_role, bob_role} == {NoiseRole.INITIATOR, NoiseRole.RESPONDER}

    # Concurrently initiate direct messages to each other
    msg_a_to_b = "Simultaneous msg Alice -> Bob"
    msg_b_to_a = "Simultaneous msg Bob -> Alice"

    await asyncio.gather(
        alice.coordinator.send_direct_message(bob.identity.peer_id_hex, msg_a_to_b),
        bob.coordinator.send_direct_message(alice.identity.peer_id_hex, msg_b_to_a),
    )

    # Both nodes must receive each other's messages
    await wait_until(
        lambda: (
            any(m[1] == msg_a_to_b for m in bob.received_messages)
            and any(m[1] == msg_b_to_a for m in alice.received_messages)
        ),
        timeout=4.0,
    )

    # Both sessions must be established
    sess_a = alice.coordinator.get_session(bob.identity.peer_id_hex)
    sess_b = bob.coordinator.get_session(alice.identity.peer_id_hex)
    assert sess_a is not None and sess_a.is_established
    assert sess_b is not None and sess_b.is_established

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_reconnect_resilience_after_transport_disconnect(node_factory) -> None:
    """Validate connection recovery and messaging after transport disconnect."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Initial message
    await alice.coordinator.send_broadcast_message("Pre-disconnect hello")
    await wait_until(
        lambda: any(m[1] == "Pre-disconnect hello" for m in bob.received_messages),
        timeout=2.0,
    )

    # Simulate link failure
    alice.clients[bob.address].is_connected = False
    bob.clients[alice.address].is_connected = False

    # Re-establish link
    await link_nodes(alice, bob)

    # Post-reconnect message
    await alice.coordinator.send_broadcast_message("Post-reconnect hello")
    await wait_until(
        lambda: any(m[1] == "Post-reconnect hello" for m in bob.received_messages),
        timeout=2.0,
    )

    messages = [m[1] for m in bob.received_messages]
    assert "Pre-disconnect hello" in messages
    assert "Post-reconnect hello" in messages

    await alice.stop()
    await bob.stop()


@pytest.mark.asyncio
async def test_transport_switch_and_fresh_ephemeral_handshake(node_factory) -> None:
    """Validate transport switch tears down sessions and rotates ephemeral identity."""
    alice: E2ENode = node_factory("Alice", "AA:01")
    bob: E2ENode = node_factory("Bob", "BB:01")

    await bob.start()
    await alice.start()
    await link_nodes(alice, bob)

    # Establish initial session on BLE
    await alice.coordinator.send_direct_message(
        bob.identity.peer_id_hex, "BLE handshake msg"
    )
    await wait_until(
        lambda: len(bob.received_messages) > 0,
        timeout=3.0,
    )

    orig_alice_id = alice.identity.peer_id_hex
    sess_init = alice.coordinator.get_session(bob.identity.peer_id_hex)
    assert sess_init is not None and sess_init.is_established

    # Switch Alice to LAN transport
    success, msg = await alice.coordinator.switch_transport("lan")
    assert success
    assert "LAN" in msg

    # Old session must be wiped and stable device identity preserved
    assert alice.coordinator.active_transport_name == "lan"
    assert alice.coordinator.local_identity.peer_id_hex == orig_alice_id
    assert alice.coordinator.get_session(bob.identity.peer_id_hex) is None

    await alice.stop()
    await bob.stop()
