"""Tier 2: Boundary & Corner Cases — Fragmentation & Reassembly Boundaries."""

from __future__ import annotations

import os

import pytest

from bitchat.exceptions import (
    FragmentLimitExceededError,
    InvalidFragmentError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    MAX_FRAGMENTS_PER_ASSEMBLY,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    generate_fragment_id,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler


def test_reassembly_duplicate_fragment_index_handled() -> None:
    """Validate duplicate fragment index is handled idempotently without corrupting assembly."""
    sender_id = os.urandom(SENDER_ID_SIZE)
    frag_id = generate_fragment_id()
    reassembler = FragmentReassembler()

    p0 = create_fragment_payload(frag_id, 0, 2, MessageType.Message, b"Part 0")
    p1 = create_fragment_payload(frag_id, 1, 2, MessageType.Message, b"Part 1")

    pkt0 = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.FragmentStart,
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=p0,
        signature=None,
    )
    pkt1 = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.FragmentEnd,
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=p1,
        signature=None,
    )

    # Deliver pkt0, then pkt0 again (duplicate)
    assert reassembler.add_fragment_packet(pkt0) is None
    assert reassembler.add_fragment_packet(pkt0) is None

    # Deliver pkt1 -> reassembly completes
    result = reassembler.add_fragment_packet(pkt1)
    assert result == b"Part 0Part 1"


def test_reassembly_max_active_assemblies_eviction() -> None:
    """Validate that exceeding MAX_ACTIVE_ASSEMBLIES (100) evicts oldest assembly."""
    reassembler = FragmentReassembler(max_active_assemblies=5)
    sender_id = os.urandom(SENDER_ID_SIZE)

    # Inject 6 different fragment streams
    for i in range(6):
        frag_id = bytes([i]) * 8
        payload = create_fragment_payload(frag_id, 0, 3, MessageType.Message, b"chunk")
        pkt = BitchatPacket(
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
        reassembler.add_fragment_packet(pkt)

    # Count must be capped at 5
    assert reassembler.active_assembly_count <= 5


def test_fragment_total_exceeds_maximum_bound() -> None:
    """Validate fragment total > 1000 raises FragmentLimitExceededError."""
    frag_id = generate_fragment_id()
    with pytest.raises(FragmentLimitExceededError):
        create_fragment_payload(
            frag_id,
            index=0,
            total=MAX_FRAGMENTS_PER_ASSEMBLY + 1,
            original_message_type=MessageType.Message,
            chunk_data=b"test",
        )


def test_fragment_index_greater_or_equal_total() -> None:
    """Validate index >= total raises InvalidFragmentError."""
    frag_id = generate_fragment_id()
    with pytest.raises(InvalidFragmentError):
        create_fragment_payload(
            frag_id,
            index=5,
            total=5,  # index must be < total (0..4)
            original_message_type=MessageType.Message,
            chunk_data=b"test",
        )


def test_fragment_total_zero() -> None:
    """Validate total <= 0 raises InvalidFragmentError."""
    frag_id = generate_fragment_id()
    with pytest.raises(InvalidFragmentError):
        create_fragment_payload(
            frag_id,
            index=0,
            total=0,
            original_message_type=MessageType.Message,
            chunk_data=b"test",
        )


def test_reassembler_invalid_message_type_rejected() -> None:
    """Validate passing non-fragment packet to reassembler raises InvalidFragmentError."""
    reassembler = FragmentReassembler()
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,  # not FragmentStart/Continue/End
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=os.urandom(SENDER_ID_SIZE),
        recipient_id=None,
        payload=b"ordinary message",
        signature=None,
    )

    with pytest.raises(InvalidFragmentError):
        reassembler.add_fragment_packet(packet)
