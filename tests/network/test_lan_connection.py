"""Unit tests for LAN TCP connection, packet framing, send/receive, and EOF handling."""

from __future__ import annotations

import asyncio

import pytest

from bitchat.network.connection import LANConnection
from bitchat.network.server import LANServer
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket


@pytest.mark.asyncio
async def test_lan_connection_send_receive_packets() -> None:
    received_packets: list[tuple[BitchatPacket, str]] = []

    def on_server_packet(packet: BitchatPacket, addr: str) -> None:
        received_packets.append((packet, addr))

    def on_conn_accepted(conn: LANConnection) -> None:
        conn.on_packet_received = on_server_packet

    # Start LAN server on ephemeral port
    server = LANServer(
        host="127.0.0.1",
        port=0,
        on_connection_accepted=on_conn_accepted,
    )
    await server.start()
    server_port = server.bound_port
    assert server_port > 0

    try:
        # Create client connection
        client = LANConnection(
            peer_address=f"127.0.0.1:{server_port}",
            connect_timeout=5.0,
        )
        await client.connect()
        assert client.is_connected

        # Send test packet
        test_pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=bytes.fromhex("1122334455667788"),
            payload=b'{"nickname": "Alice"}',
            ttl=3,
        )
        await client.send_packet(test_pkt)

        # Allow event loop to process TCP stream
        for _ in range(20):
            if received_packets:
                break
            await asyncio.sleep(0.05)

        assert len(received_packets) == 1
        rx_pkt, rx_addr = received_packets[0]
        assert rx_pkt.message_type == MessageType.Announce
        assert rx_pkt.sender_id == bytes.fromhex("1122334455667788")
        assert rx_pkt.payload == b'{"nickname": "Alice"}'
        assert "127.0.0.1" in rx_addr

        await client.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_lan_connection_connect_timeout_failure() -> None:
    # Attempt connecting to a non-existent / unreachable port
    client = LANConnection(
        peer_address="127.0.0.1:59999",
        connect_timeout=0.2,
    )
    with pytest.raises((OSError, TimeoutError)):
        await client.connect()
    assert not client.is_connected


@pytest.mark.asyncio
async def test_lan_connection_disconnect_callback() -> None:
    disconnected_addrs: list[str] = []

    server = LANServer(
        host="127.0.0.1",
        port=0,
    )
    await server.start()
    server_port = server.bound_port

    try:
        client = LANConnection(
            peer_address=f"127.0.0.1:{server_port}",
            on_disconnected=lambda addr: disconnected_addrs.append(addr),
            connect_timeout=5.0,
        )
        await client.connect()
        assert client.is_connected

        await client.close()
        assert not client.is_connected
        assert f"127.0.0.1:{server_port}" in disconnected_addrs
    finally:
        await server.stop()
