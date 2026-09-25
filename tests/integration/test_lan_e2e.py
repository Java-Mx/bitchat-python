"""Integration test for two BitChat nodes communicating over local TCP LAN
transport with Noise XX encryption.
"""

from __future__ import annotations

import asyncio

import pytest

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.network.transport import LANTransport


@pytest.mark.asyncio
async def test_two_node_lan_tcp_e2e_communication() -> None:
    # 1. Initialize Alice node
    alice_identity = LocalIdentity.generate()
    alice_router = MeshRouter(alice_identity.peer_id)
    alice_transport = LANTransport(
        local_peer_id=alice_identity.peer_id_hex,
        local_nickname="Alice",
        tcp_port=0,
    )
    alice_coord = SessionCoordinator(
        local_identity=alice_identity,
        mesh_router=alice_router,
        nickname="Alice",
        transport=alice_transport,
    )

    # 2. Initialize Bob node
    bob_identity = LocalIdentity.generate()
    bob_router = MeshRouter(bob_identity.peer_id)
    bob_transport = LANTransport(
        local_peer_id=bob_identity.peer_id_hex,
        local_nickname="Bob",
        tcp_port=0,
    )
    bob_coord = SessionCoordinator(
        local_identity=bob_identity,
        mesh_router=bob_router,
        nickname="Bob",
        transport=bob_transport,
    )

    # Message reception tracking
    alice_received_messages: list[tuple[str, str, bool]] = []
    bob_received_messages: list[tuple[str, str, bool]] = []

    def on_alice_msg(sender_id: str, text: str, is_encrypted: bool) -> None:
        alice_received_messages.append((sender_id, text, is_encrypted))

    def on_bob_msg(sender_id: str, text: str, is_encrypted: bool) -> None:
        bob_received_messages.append((sender_id, text, is_encrypted))

    alice_coord.on_message_received = on_alice_msg
    bob_coord.on_message_received = on_bob_msg

    try:
        # Start both coordinators and their LAN transports
        await alice_coord.start()
        await bob_coord.start()

        bob_port = bob_transport.server.bound_port
        assert bob_port > 0

        # Alice connects to Bob via TCP
        bob_endpoint = f"127.0.0.1:{bob_port}"
        await alice_coord.connect_peer(bob_endpoint, timeout=5.0)

        # Exchange announcements so they know each other's peer IDs
        await alice_coord.send_announce()
        await asyncio.sleep(0.1)
        await bob_coord.send_announce()
        await asyncio.sleep(0.1)

        # Verify peer address mappings
        assert bob_identity.peer_id_hex in alice_coord.peer_addresses

        # 3. Test public broadcast message
        public_text = "Hello everyone on the local network!"
        await alice_coord.send_broadcast_message(public_text)

        for _ in range(20):
            if bob_received_messages:
                break
            await asyncio.sleep(0.05)

        assert len(bob_received_messages) == 1
        sender, text, is_enc = bob_received_messages[0]
        assert sender == alice_identity.peer_id_hex
        assert text == public_text
        assert is_enc is False

        # 4. Test Noise XX encrypted direct message
        dm_text = "Super secret peer-to-peer message over TCP LAN"
        await alice_coord.send_direct_message(bob_identity.peer_id_hex, dm_text)

        # Wait for handshake completion and encrypted message delivery
        for _ in range(40):
            if any(m[1] == dm_text for m in bob_received_messages):
                break
            await asyncio.sleep(0.05)

        dm_received = [m for m in bob_received_messages if m[1] == dm_text]
        assert len(dm_received) == 1
        sender, text, is_enc = dm_received[0]
        assert sender == alice_identity.peer_id_hex
        assert text == dm_text
        assert is_enc is True

        # Verify bidirectional encryption: Bob replies securely to Alice
        reply_text = "Got your secure message, Alice!"
        await bob_coord.send_direct_message(alice_identity.peer_id_hex, reply_text)

        for _ in range(30):
            if alice_received_messages:
                break
            await asyncio.sleep(0.05)

        assert len(alice_received_messages) == 1
        sender, text, is_enc = alice_received_messages[0]
        assert sender == bob_identity.peer_id_hex
        assert text == reply_text
        assert is_enc is True

    finally:
        await alice_coord.stop()
        await bob_coord.stop()
