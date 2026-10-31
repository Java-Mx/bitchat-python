"""Defensive protocol bounds and limits unit tests."""

from __future__ import annotations

import pytest
from tests.mesh.test_mesh_routing_resolution import DummyTransport

from bitchat.app.session_coordinator import MAX_MESSAGE_SIZE, SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import InvalidFragmentError
from bitchat.protocol.constants import (
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import InMemoryStorage


@pytest.mark.asyncio
async def test_send_broadcast_message_oversized_payload_rejected() -> None:
    """send_broadcast_message rejects payload exceeding MAX_MESSAGE_SIZE."""
    coord = SessionCoordinator(
        local_identity=LocalIdentity.generate(),
        transport=DummyTransport(),
        storage=InMemoryStorage(),
    )
    oversized_text = "A" * (MAX_MESSAGE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_broadcast_message(oversized_text)


@pytest.mark.asyncio
async def test_send_direct_message_oversized_payload_rejected() -> None:
    """send_direct_message rejects payload exceeding MAX_MESSAGE_SIZE."""
    coord = SessionCoordinator(
        local_identity=LocalIdentity.generate(),
        transport=DummyTransport(),
        storage=InMemoryStorage(),
    )
    oversized_text = "B" * (MAX_MESSAGE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds maximum size"):
        await coord.send_direct_message("1234567890abcdef", oversized_text)


def test_fragment_reassembler_invalid_chunk_bounds() -> None:
    """FragmentReassembler rejects invalid total and out-of-bounds index."""
    reassembler = FragmentReassembler()
    sender = b"\x01" * 8
    frag_id = b"\x02" * 8

    # total <= 0
    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender_id=sender,
            fragment_id=frag_id,
            index=0,
            total=0,
            original_message_type=MessageType.Message,
            chunk_data=b"data",
        )

    # index >= total
    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender_id=sender,
            fragment_id=frag_id,
            index=3,
            total=3,
            original_message_type=MessageType.Message,
            chunk_data=b"data",
        )

    # index < 0
    with pytest.raises(InvalidFragmentError):
        reassembler._insert_chunk(
            sender_id=sender,
            fragment_id=frag_id,
            index=-1,
            total=3,
            original_message_type=MessageType.Message,
            chunk_data=b"data",
        )


def test_fragment_reassembler_prune_stale_default_arg() -> None:
    """prune_stale can be invoked without arguments, defaulting to 60.0s."""
    reassembler = FragmentReassembler()
    sender = b"\x01" * 8
    frag_id = b"\x02" * 8

    reassembler._insert_chunk(
        sender_id=sender,
        fragment_id=frag_id,
        index=0,
        total=2,
        original_message_type=MessageType.Message,
        chunk_data=b"part1",
    )
    assert reassembler.active_assembly_count == 1

    # prune with default argument when not stale
    removed = reassembler.prune_stale()
    assert removed == 0
    assert reassembler.active_assembly_count == 1

    # artificially age the assembly
    key = (sender, frag_id)
    reassembler._assemblies[key].created_at -= 65.0

    removed = reassembler.prune_stale()
    assert removed == 1
    assert reassembler.active_assembly_count == 0


def test_server_reassembler_error_handling() -> None:
    """Server packet handler handles malformed fragments without unhandled errors."""
    coord = SessionCoordinator(
        local_identity=LocalIdentity.generate(),
        transport=DummyTransport(),
        storage=InMemoryStorage(),
    )

    # Malformed fragment packet: payload too short
    malformed_pkt = BitchatPacket.create(
        message_type=MessageType.FragmentStart,
        sender_id=b"\x01" * 8,
        payload=b"short",
    )

    from bitchat.protocol.encoder import encode_packet

    raw = encode_packet(malformed_pkt, add_padding=False)
    # Processing malformed fragment must not raise uncaught exceptions
    coord._handle_server_data_received(raw, "client_1")
