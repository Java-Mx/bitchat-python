"""Defensive protocol bounds and limits unit tests."""

from __future__ import annotations

from typing import Any

import pytest

from bitchat.app.session_coordinator import MAX_MESSAGE_SIZE, SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.exceptions import InvalidFragmentError
from bitchat.protocol.constants import (
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.base import BaseTransport, TransportState, TransportType


class _DummyTransport(BaseTransport):
    """Minimal transport for isolating SessionCoordinator message bounds testing."""

    def __init__(self) -> None:
        super().__init__()
        self._state: TransportState = TransportState.READY

    @property
    def transport_type(self) -> TransportType:
        return TransportType.BLUETOOTH

    @property
    def state(self) -> TransportState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == TransportState.CONNECTED

    @property
    def connected_peers(self) -> list[str]:
        return []

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return {}

    async def start(self) -> None:
        self._state = TransportState.CONNECTED

    async def stop(self) -> None:
        self._state = TransportState.OFFLINE

    async def start_discovery(self) -> None:
        pass

    async def stop_discovery(self) -> None:
        pass

    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        pass

    async def disconnect_peer(self, address: str) -> None:
        pass

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        pass

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        pass

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        pass

    def resolve_peer_id_to_address(self, target: str) -> str | None:
        return None

    def get_telemetry(self) -> dict[str, Any]:
        return {}


@pytest.mark.asyncio
async def test_send_broadcast_message_oversized_payload_rejected() -> None:
    """send_broadcast_message rejects payload exceeding MAX_MESSAGE_SIZE."""
    coord = SessionCoordinator(
        local_identity=LocalIdentity.generate(),
        transport=_DummyTransport(),
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
        transport=_DummyTransport(),
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
        transport=_DummyTransport(),
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
