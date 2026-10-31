"""Tier 1: Feature Coverage — LAN TCP Transport & Connection Lifecycle."""

from __future__ import annotations

import asyncio
import os

import pytest

from bitchat.network.connection import LANConnection
from bitchat.network.framing import (
    StreamFramer,
    encode_frame,
)
from bitchat.network.server import LANServer
from bitchat.network.transport import LANTransport
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def test_stream_framer_single_and_split_chunks() -> None:
    """Validate StreamFramer processes single frames and frames split across chunks."""
    payload = b"Hello BitChat framing stream!"
    frame = encode_frame(payload)

    framer = StreamFramer()

    # Split frame into 3 slices
    slice1 = frame[:4]  # magic
    slice2 = frame[4:10]  # length + partial payload
    slice3 = frame[10:]  # rest of payload

    assert framer.feed(slice1) == []
    assert framer.feed(slice2) == []
    results = framer.feed(slice3)
    assert len(results) == 1
    assert results[0] == payload
    assert framer.buffered_bytes == 0


def test_stream_framer_multiple_concatenated_frames() -> None:
    """Validate StreamFramer extracts multiple frames sent in a single read."""
    payload1 = b"Frame number one"
    payload2 = b"Frame number two"
    payload3 = b"Frame number three"

    combined = encode_frame(payload1) + encode_frame(payload2) + encode_frame(payload3)
    framer = StreamFramer()
    results = framer.feed(combined)

    assert len(results) == 3
    assert results == [payload1, payload2, payload3]
    assert framer.buffered_bytes == 0


@pytest.mark.asyncio
async def test_lan_server_bind_and_accept_connection() -> None:
    """Validate LANServer binds on dynamic port and accepts client connections."""
    accepted_connections: list[LANConnection] = []

    def on_conn(conn: LANConnection) -> None:
        accepted_connections.append(conn)

    server = LANServer(
        host="127.0.0.1",
        port=0,
        on_connection_accepted=on_conn,
    )

    await server.start()
    assert server.is_listening
    assert server.bound_port > 0

    # Connect client
    _reader, writer = await asyncio.open_connection("127.0.0.1", server.bound_port)
    await asyncio.sleep(0.05)

    assert len(accepted_connections) == 1
    assert accepted_connections[0].is_connected

    writer.close()
    await writer.wait_closed()
    await server.stop()
    assert not server.is_listening


@pytest.mark.asyncio
async def test_lan_connection_loopback_bidirectional_packet() -> None:
    """Validate bidirectional packet transmission between connected LAN peers."""
    server_received: list[BitchatPacket] = []
    client_received: list[BitchatPacket] = []

    server_conn_future: asyncio.Future[LANConnection] = (
        asyncio.get_running_loop().create_future()
    )

    def on_accepted(conn: LANConnection) -> None:
        conn.on_packet_received = lambda pkt, addr: server_received.append(pkt)
        conn.start_reading()
        if not server_conn_future.done():
            server_conn_future.set_result(conn)

    server = LANServer(
        host="127.0.0.1",
        port=0,
        on_connection_accepted=on_accepted,
    )
    await server.start()

    # Outbound client connection
    client_conn = LANConnection(
        peer_address=f"127.0.0.1:{server.bound_port}",
        on_packet_received=lambda pkt, addr: client_received.append(pkt),
    )
    await client_conn.connect()
    server_conn = await asyncio.wait_for(server_conn_future, timeout=2.0)

    # 1. Send packet from client to server
    sender_c = os.urandom(SENDER_ID_SIZE)
    packet_c = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=1000,
        flags=0,
        sender_id=sender_c,
        recipient_id=None,
        payload=b"From client to server",
        signature=None,
    )
    await client_conn.send_packet(packet_c)

    # 2. Send packet from server to client
    sender_s = os.urandom(SENDER_ID_SIZE)
    packet_s = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=2000,
        flags=0,
        sender_id=sender_s,
        recipient_id=None,
        payload=b"From server to client",
        signature=None,
    )
    await server_conn.send_packet(packet_s)

    for _ in range(50):
        if len(server_received) >= 1 and len(client_received) >= 1:
            break
        await asyncio.sleep(0.02)

    assert len(server_received) == 1
    assert server_received[0].payload == b"From client to server"
    assert server_received[0].sender_id == sender_c

    assert len(client_received) == 1
    assert client_received[0].payload == b"From server to client"
    assert client_received[0].sender_id == sender_s

    await client_conn.close()
    await server_conn.close()
    await server.stop()


@pytest.mark.asyncio
async def test_lan_transport_connect_and_broadcast() -> None:
    """Validate LANTransport initializes and sends broadcast packets over TCP."""
    recv_alice: list[tuple[BitchatPacket, str]] = []
    recv_bob: list[tuple[BitchatPacket, str]] = []

    t_alice = LANTransport(
        local_peer_id="alice001",
        local_nickname="Alice",
        tcp_port=0,
        discovery_port=0,
    )
    t_alice.on_packet_received = lambda pkt, addr: recv_alice.append((pkt, addr))

    t_bob = LANTransport(
        local_peer_id="bob00002",
        local_nickname="Bob",
        tcp_port=0,
        discovery_port=0,
    )
    t_bob.on_packet_received = lambda pkt, addr: recv_bob.append((pkt, addr))

    # Disable UDP discovery loop to avoid network broadcast conflicts in tests
    t_alice.discovery.broadcast_interval = 9999.0
    t_bob.discovery.broadcast_interval = 9999.0

    await t_alice.start()
    await t_bob.start()

    bob_port = t_bob.server.bound_port
    assert bob_port > 0

    # Alice connects directly to Bob's TCP port
    bob_addr = f"127.0.0.1:{bob_port}"
    await t_alice.connect_peer(bob_addr)
    await asyncio.sleep(0.05)

    sender_id = os.urandom(SENDER_ID_SIZE)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=123,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=b"Alice broadcast to Bob",
        signature=None,
    )

    await t_alice.broadcast_packet(packet)

    for _ in range(50):
        if len(recv_bob) >= 1:
            break
        await asyncio.sleep(0.02)

    assert len(recv_bob) == 1
    assert recv_bob[0][0].payload == b"Alice broadcast to Bob"

    await t_alice.stop()
    await t_bob.stop()


@pytest.mark.asyncio
async def test_lan_connection_clean_teardown() -> None:
    """Validate closing LANConnection terminates reader tasks cleanly."""
    server = LANServer(host="127.0.0.1", port=0)
    await server.start()

    conn = LANConnection(peer_address=f"127.0.0.1:{server.bound_port}")
    await conn.connect()
    assert conn.is_connected
    assert conn._read_task is not None and not conn._read_task.done()

    await conn.close()
    assert not conn.is_connected
    assert conn._read_task is None

    await server.stop()
