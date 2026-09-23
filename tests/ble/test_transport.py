"""Tests for BLETransport verifying transmission, pacing, reception."""

from __future__ import annotations

import asyncio
import time

import pytest
from tests.ble.mocks import MockBleakClient

from bitchat.ble.connection import BLEConnection
from bitchat.ble.transport import BLETransport
from bitchat.exceptions import BLETransportError
from bitchat.protocol.constants import (
    BITCHAT_CHARACTERISTIC_UUID,
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet
from bitchat.protocol.packet import BitchatPacket


def _make_ready_connection() -> tuple[BLEConnection, MockBleakClient]:
    mock_client = MockBleakClient(address="AA:BB:CC:DD:EE:01")
    conn = BLEConnection(
        peer_address="AA:BB:CC:DD:EE:01",
        client_factory=lambda *args, **kwargs: mock_client,
    )
    return conn, mock_client


def _create_packet(
    message_type: MessageType = MessageType.Message,
    sender_id: bytes = b"\x01" * 8,
    recipient_id: bytes | None = None,
    payload: bytes = b"",
) -> BitchatPacket:
    flags = FLAG_HAS_RECIPIENT if recipient_id is not None else 0
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=message_type,
        ttl=7,
        timestamp=int(time.time() * 1000),
        flags=flags,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        signature=None,
    )


@pytest.mark.asyncio
async def test_transport_send_small_packet() -> None:
    conn, mock_client = _make_ready_connection()
    sender_id = b"\x01" * 8
    transport = BLETransport(connection=conn, sender_id=sender_id)

    await transport.start()
    assert conn.is_ready

    pkt = _create_packet(
        message_type=MessageType.Announce,
        sender_id=sender_id,
        payload=b"node_announce",
    )

    await transport.send_packet(pkt)

    assert len(mock_client.written_chunks) == 1
    char_uuid, data, response = mock_client.written_chunks[0]
    assert char_uuid.lower() == BITCHAT_CHARACTERISTIC_UUID.lower()
    assert response is False

    decoded = decode_packet(data)
    assert decoded.message_type == MessageType.Announce
    assert decoded.sender_id == sender_id
    assert decoded.payload == b"node_announce"

    await transport.stop()


@pytest.mark.asyncio
async def test_transport_send_large_packet_fragmented_with_pacing() -> None:
    conn, mock_client = _make_ready_connection()
    sender_id = b"\x02" * 8
    delay = 0.02
    transport = BLETransport(
        connection=conn,
        sender_id=sender_id,
        inter_fragment_delay=delay,
    )

    await transport.start()

    # Create a packet exceeding FRAGMENTATION_THRESHOLD (500B)
    large_payload = b"X" * 900
    pkt = _create_packet(
        message_type=MessageType.Message,
        sender_id=sender_id,
        payload=large_payload,
    )

    start_time = time.monotonic()
    await transport.send_packet(pkt)
    elapsed = time.monotonic() - start_time

    assert len(mock_client.written_chunks) > 1
    for _, _, response in mock_client.written_chunks:
        assert response is False

    expected_min_delay = (len(mock_client.written_chunks) - 1) * delay * 0.8
    assert elapsed >= expected_min_delay

    await transport.stop()


@pytest.mark.asyncio
async def test_transport_receive_and_dispatch() -> None:
    conn, mock_client = _make_ready_connection()
    sender_id = b"\x03" * 8
    received_packets: list[tuple[BitchatPacket, str]] = []

    def on_recv(pkt: BitchatPacket, peer_addr: str) -> None:
        received_packets.append((pkt, peer_addr))

    transport = BLETransport(
        connection=conn,
        sender_id=sender_id,
        on_packet_received=on_recv,
    )

    await transport.start()

    test_pkt = _create_packet(
        message_type=MessageType.Message,
        sender_id=b"\x04" * 8,
        payload=b"hello",
    )
    raw_wire = encode_packet(test_pkt, add_padding=True)

    mock_client.emit_notification(raw_wire)
    await asyncio.sleep(0.05)

    assert len(received_packets) == 1
    pkt, addr = received_packets[0]
    assert addr == "AA:BB:CC:DD:EE:01"
    assert pkt.message_type == MessageType.Message
    assert pkt.payload == b"hello"

    await transport.stop()


@pytest.mark.asyncio
async def test_transport_receive_queue_backpressure() -> None:
    conn, _mock_client = _make_ready_connection()
    sender_id = b"\x05" * 8

    transport = BLETransport(
        connection=conn,
        sender_id=sender_id,
        queue_max_size=2,
    )

    conn.notification_callback = transport._handle_incoming_notification

    for i in range(5):
        transport._handle_incoming_notification(f"data_{i}".encode())

    assert transport._receive_queue.qsize() == 2


@pytest.mark.asyncio
async def test_transport_malformed_packet_isolation() -> None:
    conn, mock_client = _make_ready_connection()
    sender_id = b"\x06" * 8
    received_packets: list[BitchatPacket] = []

    def on_recv(pkt: BitchatPacket, addr: str) -> None:
        received_packets.append(pkt)

    transport = BLETransport(
        connection=conn,
        sender_id=sender_id,
        on_packet_received=on_recv,
    )
    await transport.start()

    mock_client.emit_notification(b"\x00\x01garbage_packet")
    await asyncio.sleep(0.05)
    assert len(received_packets) == 0

    valid_pkt = _create_packet(
        message_type=MessageType.Message,
        sender_id=b"\x07" * 8,
        payload=b"valid payload",
    )
    mock_client.emit_notification(encode_packet(valid_pkt))
    await asyncio.sleep(0.05)

    assert len(received_packets) == 1
    assert received_packets[0].sender_id == b"\x07" * 8
    assert received_packets[0].payload == b"valid payload"

    await transport.stop()


@pytest.mark.asyncio
async def test_transport_in_order_and_out_of_order_reassembly() -> None:
    conn, mock_client = _make_ready_connection()
    sender_id = b"\x08" * 8
    received_packets: list[BitchatPacket] = []

    def on_recv(pkt: BitchatPacket, addr: str) -> None:
        received_packets.append(pkt)

    transport = BLETransport(
        connection=conn,
        sender_id=sender_id,
        on_packet_received=on_recv,
    )
    await transport.start()

    original_pkt = _create_packet(
        message_type=MessageType.Message,
        sender_id=b"\x09" * 8,
        payload=b"Reassembly test payload content" * 25,
    )
    encoded_original = encode_packet(original_pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded_original,
        sender_id=b"\x09" * 8,
        original_message_type=MessageType.Message,
    )
    assert len(fragments) >= 3

    out_of_order = [fragments[-1], fragments[0], *fragments[1:-1]]
    for frag in out_of_order:
        mock_client.emit_notification(encode_packet(frag, add_padding=True))
        await asyncio.sleep(0.02)

    await asyncio.sleep(0.05)
    assert len(received_packets) == 1
    reassembled = received_packets[0]
    assert reassembled.message_type == MessageType.Message
    assert reassembled.payload == original_pkt.payload
    assert reassembled.sender_id == original_pkt.sender_id

    await transport.stop()


@pytest.mark.asyncio
async def test_transport_send_when_not_ready_raises() -> None:
    conn, _ = _make_ready_connection()
    sender_id = b"\x0a" * 8
    transport = BLETransport(connection=conn, sender_id=sender_id)

    pkt = _create_packet(
        message_type=MessageType.Announce,
        sender_id=sender_id,
    )

    with pytest.raises(BLETransportError, match="not ready"):
        await transport.send_packet(pkt)

    with pytest.raises(BLETransportError, match="not ready"):
        await transport.send_bytes(b"raw")
