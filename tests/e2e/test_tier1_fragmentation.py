"""Tier 1: Feature Coverage — Packet Fragmentation & Reassembly."""

from __future__ import annotations

import os
import random
import time

from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    fragment_encoded_packet,
    generate_fragment_id,
    should_fragment,
    split_chunks,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler


def test_should_fragment_threshold_check() -> None:
    """Verify threshold detection accurately identifies messages exceeding 500 bytes."""
    sender = os.urandom(SENDER_ID_SIZE)

    # Below threshold (e.g. 100 bytes payload)
    small_packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=b"A" * 100,
        signature=None,
    )
    assert not should_fragment(small_packet)

    # Strictly above threshold (600 bytes payload)
    large_packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=b"B" * 600,
        signature=None,
    )
    assert should_fragment(large_packet)


def test_split_chunks_and_reassembly_in_order() -> None:
    """Validate splitting large data into 150-byte chunks and sequential reassembly."""
    data = os.urandom(1200)
    chunks = split_chunks(data, chunk_size=150)
    assert len(chunks) == 8

    frag_id = generate_fragment_id()
    sender_id = os.urandom(SENDER_ID_SIZE)
    reassembler = FragmentReassembler()

    for idx, chunk in enumerate(chunks):
        if idx == 0:
            mtype = MessageType.FragmentStart
        elif idx == len(chunks) - 1:
            mtype = MessageType.FragmentEnd
        else:
            mtype = MessageType.FragmentContinue

        payload = create_fragment_payload(
            frag_id, idx, len(chunks), MessageType.Message, chunk
        )
        packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=mtype,
            ttl=5,
            timestamp=12345,
            flags=0,
            sender_id=sender_id,
            recipient_id=None,
            payload=payload,
            signature=None,
        )

        result = reassembler.add_fragment_packet(packet)
        if idx == len(chunks) - 1:
            assert result == data
        else:
            assert result is None

    assert reassembler.active_assembly_count == 0


def test_out_of_order_fragment_reassembly() -> None:
    """Validate reassembly when fragments arrive reversed or out of order."""
    original_data = b"OUT-OF-ORDER-TEST-PAYLOAD-" * 40
    chunks = split_chunks(original_data, chunk_size=120)
    total = len(chunks)
    frag_id = generate_fragment_id()
    sender_id = os.urandom(SENDER_ID_SIZE)

    packets: list[BitchatPacket] = []
    for idx, chunk in enumerate(chunks):
        if idx == 0:
            mtype = MessageType.FragmentStart
        elif idx == total - 1:
            mtype = MessageType.FragmentEnd
        else:
            mtype = MessageType.FragmentContinue

        payload = create_fragment_payload(
            frag_id, idx, total, MessageType.Message, chunk
        )
        packets.append(
            BitchatPacket(
                version=CURRENT_PROTOCOL_VERSION,
                message_type=mtype,
                ttl=5,
                timestamp=12345,
                flags=0,
                sender_id=sender_id,
                recipient_id=None,
                payload=payload,
                signature=None,
            )
        )

    # Shuffle the delivery order
    shuffled_packets = list(packets)
    random.Random(42).shuffle(shuffled_packets)

    reassembler = FragmentReassembler()
    final_data: bytes | None = None
    for p in shuffled_packets:
        res = reassembler.add_fragment_packet(p)
        if res is not None:
            final_data = res

    assert final_data == original_data
    assert reassembler.active_assembly_count == 0


def test_multiple_concurrent_assemblies() -> None:
    """Validate that fragments from different senders and IDs assemble concurrently."""
    sender_a = os.urandom(SENDER_ID_SIZE)
    sender_b = os.urandom(SENDER_ID_SIZE)
    data_a = b"DATA-STREAM-A-" * 30
    data_b = b"DATA-STREAM-B-" * 30

    chunks_a = split_chunks(data_a, chunk_size=100)
    chunks_b = split_chunks(data_b, chunk_size=100)

    frag_id_a = generate_fragment_id()
    frag_id_b = generate_fragment_id()

    reassembler = FragmentReassembler()

    def make_packet(s_id: bytes, f_id: bytes, idx: int, total: int, chunk: bytes):
        if idx == 0:
            mtype = MessageType.FragmentStart
        elif idx == total - 1:
            mtype = MessageType.FragmentEnd
        else:
            mtype = MessageType.FragmentContinue
        payload = create_fragment_payload(f_id, idx, total, MessageType.Message, chunk)
        return BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=mtype,
            ttl=5,
            timestamp=100,
            flags=0,
            sender_id=s_id,
            recipient_id=None,
            payload=payload,
            signature=None,
        )

    # Interleave packets from A and B
    max_len = max(len(chunks_a), len(chunks_b))
    result_a: bytes | None = None
    result_b: bytes | None = None

    for i in range(max_len):
        if i < len(chunks_a):
            pa = make_packet(sender_a, frag_id_a, i, len(chunks_a), chunks_a[i])
            ra = reassembler.add_fragment_packet(pa)
            if ra:
                result_a = ra
        if i < len(chunks_b):
            pb = make_packet(sender_b, frag_id_b, i, len(chunks_b), chunks_b[i])
            rb = reassembler.add_fragment_packet(pb)
            if rb:
                result_b = rb

    assert result_a == data_a
    assert result_b == data_b
    assert reassembler.active_assembly_count == 0


def test_fragment_packet_end_to_end_flow() -> None:
    """Validate full flow: encode large packet -> fragment -> reassemble -> decode packet."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    large_payload = b"LONG-TEXT-" * 100  # 1000 bytes

    original_packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=1700000000000,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=large_payload,
        signature=None,
    )

    encoded_original = encode_packet(original_packet, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded_original,
        sender_id=sender_id,
        original_message_type=MessageType.Message,
    )
    assert len(fragments) > 1

    reassembler = FragmentReassembler()
    assembled_bytes: bytes | None = None
    for frag in fragments:
        res = reassembler.add_fragment_packet(frag)
        if res is not None:
            assembled_bytes = res

    assert assembled_bytes is not None
    assert assembled_bytes == encoded_original
    decoded_packet = decode_packet(assembled_bytes)
    assert decoded_packet.payload == large_payload
    assert decoded_packet.sender_id == sender_id


def test_reassembler_prune_stale() -> None:
    """Validate pruning incomplete assemblies that exceed max age."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    frag_id = generate_fragment_id()
    reassembler = FragmentReassembler()

    payload = create_fragment_payload(
        frag_id, 0, 5, MessageType.Message, b"First chunk only"
    )
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.FragmentStart,
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=payload,
        signature=None,
    )

    reassembler.add_fragment_packet(packet)
    assert reassembler.active_assembly_count == 1

    # Pruning with age < 0 (simulates elapsed time)
    removed = reassembler.prune_stale(max_age_seconds=-1.0)
    assert removed == 1
    assert reassembler.active_assembly_count == 0
