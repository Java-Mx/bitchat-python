"""End-to-end TUI chat over real local UDP discovery and TCP sockets."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

import pytest
from textual.widgets import Label, ListItem, ListView

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.pilot import Pilot

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import NoiseSessionState
from bitchat.mesh.router import MeshRouter
from bitchat.network.adapter import get_local_ip
from bitchat.network.models import DiscoveryPacket
from bitchat.network.transport import LANTransport
from bitchat.tui.app import BitChatApp
from bitchat.tui.widgets.chat_view import ChatMessageRecord, ChatView
from bitchat.tui.widgets.message_input import MessageInput
from bitchat.tui.widgets.sidebar import PeerSidebar
from bitchat.tui.widgets.status_bar import StatusBar


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.bind(("0.0.0.0", 0))
        port = udp_socket.getsockname()[1]
    assert port > 1024
    return port


async def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("Condition was not met before timeout")
        await asyncio.sleep(0.02)


async def _send_input(pilot: Pilot, app: BitChatApp, text: str) -> None:
    msg_input = app.query_one(MessageInput)
    msg_input.value = text
    await msg_input.action_submit()
    await pilot.pause()


def _chat_records(app: BitChatApp, text: str) -> list[ChatMessageRecord]:
    return [
        record
        for record in app.query_one(ChatView)._message_history
        if record.kind == "chat" and record.text == text
    ]


def _connected_peer_labels(app: BitChatApp) -> list[str]:
    connected_peers = app.query_one(PeerSidebar).query_one(
        "#connected-peers-list", ListView
    )
    return [
        str(item.query_one(Label).render())
        for item in connected_peers.children
        if isinstance(item, ListItem)
    ]


@pytest.mark.asyncio
async def test_two_node_lan_tui_chat_over_real_network_and_reconnect() -> None:
    local_ip = get_local_ip()
    assert local_ip and not local_ip.startswith("127."), (
        "LAN integration test requires a non-loopback local IPv4 address"
    )

    alice_identity = LocalIdentity.generate()
    alice_discovery_port = _free_udp_port()
    alice_transport = LANTransport(
        local_peer_id=alice_identity.peer_id_hex,
        local_nickname="Alice",
        tcp_port=0,
        discovery_port=alice_discovery_port,
    )
    alice_transport.discovery.broadcast_interval = 60.0
    alice_coord = SessionCoordinator(
        local_identity=alice_identity,
        mesh_router=MeshRouter(alice_identity.peer_id),
        nickname="Alice",
        transport=alice_transport,
    )
    alice_app = BitChatApp(coordinator=alice_coord)

    bob_identity = LocalIdentity.generate()
    bob_transport = LANTransport(
        local_peer_id=bob_identity.peer_id_hex,
        local_nickname="Bob",
        tcp_port=0,
        discovery_port=_free_udp_port(),
    )
    bob_transport.discovery.broadcast_interval = 60.0
    bob_coord = SessionCoordinator(
        local_identity=bob_identity,
        mesh_router=MeshRouter(bob_identity.peer_id),
        nickname="Bob",
        transport=bob_transport,
    )
    bob_app = BitChatApp(coordinator=bob_coord)

    async def announce_bob_to_alice() -> None:
        beacon = DiscoveryPacket(
            peer_id=bob_identity.peer_id_hex,
            nickname="Bob",
            port=bob_transport.server.bound_port,
        ).to_bytes()
        loop = asyncio.get_running_loop()
        send_socket = bob_transport.discovery._send_sock
        assert send_socket is not None
        await loop.sock_sendto(send_socket, beacon, (local_ip, alice_discovery_port))

    try:
        async with (
            alice_app.run_test(size=(120, 45)) as alice_pilot,
            bob_app.run_test(size=(120, 45)) as bob_pilot,
        ):
            await _wait_until(
                lambda: (
                    alice_transport.server.is_listening
                    and bob_transport.server.is_listening
                    and alice_transport.discovery.is_listening
                    and bob_transport.discovery.is_listening
                )
            )
            assert alice_transport.server.bound_port > 0
            assert bob_transport.server.bound_port > 0

            await announce_bob_to_alice()
            await _wait_until(
                lambda: any(
                    peer.peer_id == bob_identity.peer_id_hex
                    for peer in alice_transport.discovered_peers.values()
                )
            )
            await _wait_until(
                lambda: (
                    bob_identity.peer_id_hex in alice_coord.peer_addresses
                    and alice_coord.peer_nicknames.get(bob_identity.peer_id_hex)
                    == "Bob"
                    and any(
                        "Bob" in label
                        for label in alice_app.query_one(
                            PeerSidebar
                        )._discovered_peers.values()
                    )
                )
            )
            discovered_endpoint = alice_coord.peer_addresses[bob_identity.peer_id_hex]
            assert discovered_endpoint == (
                f"{local_ip}:{bob_transport.server.bound_port}"
            )

            await _send_input(
                alice_pilot, alice_app, f"/connect {bob_identity.peer_id_hex}"
            )
            await _wait_until(
                lambda: (
                    bool(alice_transport.connected_peers)
                    and bool(bob_transport.connected_peers)
                )
            )

            alice_status = alice_app.query_one(StatusBar)
            assert "TCP active" in alice_status.mesh_status
            connected_display = alice_app.query_one(PeerSidebar)._connected_peers
            assert any("unverified" in label for label in connected_display.values())
            assert any(
                "TCP Connected" in label and "Noise session not established" in label
                for label in _connected_peer_labels(alice_app)
            )
            connected_session = alice_coord.get_session(bob_identity.peer_id_hex)
            assert connected_session is None or not connected_session.is_established

            public_text = "Alice public over real LAN TCP"
            await _send_input(alice_pilot, alice_app, public_text)
            await _wait_until(lambda: len(_chat_records(bob_app, public_text)) == 1)
            bob_public = _chat_records(bob_app, public_text)[0]
            assert bob_public.sender == "Alice"
            assert not bob_public.is_encrypted
            assert any(
                public_text in str(line)
                for line in bob_app.query_one(ChatView).rich_log.lines
            )

            reply_text = "Bob replies over real LAN TCP"
            await _send_input(bob_pilot, bob_app, reply_text)
            await _wait_until(lambda: len(_chat_records(alice_app, reply_text)) == 1)
            alice_reply = _chat_records(alice_app, reply_text)[0]
            assert alice_reply.sender == "Bob"
            assert not alice_reply.is_encrypted

            private_text = "Alice private over Noise"

            def both_sessions_established() -> bool:
                alice_session = alice_coord.get_session(bob_identity.peer_id_hex)
                bob_session = bob_coord.get_session(alice_identity.peer_id_hex)
                return (
                    alice_session is not None
                    and alice_session.is_established
                    and bob_session is not None
                    and bob_session.is_established
                )

            await _send_input(
                alice_pilot,
                alice_app,
                f"/dm {bob_identity.peer_id_hex} {private_text}",
            )
            await _wait_until(
                lambda: (
                    len(_chat_records(bob_app, private_text)) == 1
                    and both_sessions_established()
                )
            )
            assert _chat_records(bob_app, private_text)[0].is_encrypted
            assert any(
                record.kind == "security"
                and "Noise XX session established" in record.text
                for record in bob_app.query_one(ChatView)._message_history
            )
            assert any(
                private_text in str(line)
                for line in bob_app.query_one(ChatView).rich_log.lines
            )
            assert any(
                "authenticated" in label
                for label in alice_app.query_one(PeerSidebar)._connected_peers.values()
            )
            assert any(
                "TCP Connected" in label and "Noise XX authenticated" in label
                for label in _connected_peer_labels(alice_app)
            )

            alice_session = alice_coord.get_session(bob_identity.peer_id_hex)
            bob_session = bob_coord.get_session(alice_identity.peer_id_hex)
            assert alice_session is not None and alice_session.is_established
            assert bob_session is not None and bob_session.is_established

            await _send_input(
                alice_pilot,
                alice_app,
                f"/disconnect {bob_identity.peer_id_hex}",
            )
            await _wait_until(
                lambda: (
                    not alice_transport.connected_peers
                    and not bob_transport.connected_peers
                    and alice_coord.get_session(bob_identity.peer_id_hex) is None
                    and bob_coord.get_session(alice_identity.peer_id_hex) is None
                )
            )
            assert alice_session.state == NoiseSessionState.CLOSED
            assert bob_session.state == NoiseSessionState.CLOSED
            assert "TCP active" not in alice_app.query_one(StatusBar).mesh_status

            await _send_input(
                alice_pilot,
                alice_app,
                f"/connect {bob_identity.peer_id_hex}",
            )
            await _wait_until(
                lambda: (
                    bool(alice_transport.connected_peers)
                    and bool(bob_transport.connected_peers)
                )
            )
            reconnect_private = "Private message after reconnect"
            await _send_input(
                alice_pilot,
                alice_app,
                f"/dm {bob_identity.peer_id_hex} {reconnect_private}",
            )
            await _wait_until(
                lambda: len(_chat_records(bob_app, reconnect_private)) == 1
            )
            assert _chat_records(bob_app, reconnect_private)[0].is_encrypted
            assert both_sessions_established()
            assert (
                alice_coord.get_session(bob_identity.peer_id_hex) is not alice_session
            )
            assert bob_coord.get_session(alice_identity.peer_id_hex) is not bob_session
            assert "TCP active" in alice_app.query_one(StatusBar).mesh_status
            await alice_coord.stop()
            await bob_coord.stop()
    finally:
        await alice_coord.stop()
        await bob_coord.stop()
