"""BitChat protocol packet reassembly."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from bitchat.exceptions import (
    FragmentLimitExceededError,
    InvalidFragmentError,
)
from bitchat.protocol.constants import (
    MAX_ACTIVE_ASSEMBLIES,
    MAX_FRAGMENTS_PER_ASSEMBLY,
    MAX_REASSEMBLED_BYTES,
    MessageType,
)
from bitchat.protocol.fragmentation import parse_fragment_payload
from bitchat.protocol.packet import BitchatPacket


@dataclass
class _AssemblyState:
    sender_id: bytes
    fragment_id: bytes
    total: int
    original_message_type: int
    chunks: dict[int, bytes] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    total_bytes: int = 0


class FragmentReassembler:
    """Bounded, out-of-order fragment collector with sender isolation."""

    def __init__(
        self,
        max_active_assemblies: int = MAX_ACTIVE_ASSEMBLIES,
        max_fragments_per_assembly: int = MAX_FRAGMENTS_PER_ASSEMBLY,
        max_reassembled_bytes: int = MAX_REASSEMBLED_BYTES,
    ) -> None:
        self._max_active_assemblies = max_active_assemblies
        self._max_fragments_per_assembly = max_fragments_per_assembly
        self._max_reassembled_bytes = max_reassembled_bytes
        self._assemblies: OrderedDict[tuple[bytes, bytes], _AssemblyState] = (
            OrderedDict()
        )

    @property
    def active_assembly_count(self) -> int:
        """Return number of currently active in-progress assemblies."""
        return len(self._assemblies)

    def clear(self) -> None:
        """Clear all in-flight assemblies."""
        self._assemblies.clear()

    def prune_stale(self, max_age_seconds: float) -> int:
        """Remove assemblies older than max_age_seconds, returning count removed."""
        now = time.monotonic()
        stale_keys = [
            key
            for key, state in self._assemblies.items()
            if now - state.created_at > max_age_seconds
        ]
        for key in stale_keys:
            del self._assemblies[key]
        return len(stale_keys)

    def add_fragment_packet(self, packet: BitchatPacket) -> bytes | None:
        """Process a fragment packet and return reassembled bytes when complete."""
        if not isinstance(packet, BitchatPacket):
            raise InvalidFragmentError(
                f"Expected BitchatPacket, got {type(packet).__name__}"
            )

        if packet.message_type not in (
            MessageType.FragmentStart,
            MessageType.FragmentContinue,
            MessageType.FragmentEnd,
        ):
            raise InvalidFragmentError(
                f"Packet message type {packet.message_type} is not a fragment type"
            )

        frag_id, index, total, orig_type, data = parse_fragment_payload(packet.payload)

        if index == 0 and packet.message_type != MessageType.FragmentStart:
            msg = (
                f"Index 0 fragment must be FragmentStart, "
                f"got {packet.message_type.name}"
            )
            raise InvalidFragmentError(msg)
        if index == total - 1 and packet.message_type != MessageType.FragmentEnd:
            msg = (
                f"Final fragment (index {index}) must be FragmentEnd, "
                f"got {packet.message_type.name}"
            )
            raise InvalidFragmentError(msg)
        if (
            0 < index < total - 1
            and packet.message_type != MessageType.FragmentContinue
        ):
            msg = (
                f"Intermediate fragment (index {index}) must be "
                f"FragmentContinue, got {packet.message_type.name}"
            )
            raise InvalidFragmentError(msg)

        return self._insert_chunk(
            sender_id=packet.sender_id,
            fragment_id=frag_id,
            index=index,
            total=total,
            original_message_type=orig_type,
            chunk_data=data,
        )

    def add_fragment(self, sender_id: bytes, payload: bytes) -> bytes | None:
        """Process a raw fragment payload and return reassembled bytes when complete."""
        if not isinstance(sender_id, (bytes, bytearray)):
            raise InvalidFragmentError("sender_id must be bytes")
        frag_id, index, total, orig_type, data = parse_fragment_payload(payload)
        return self._insert_chunk(
            sender_id=bytes(sender_id),
            fragment_id=frag_id,
            index=index,
            total=total,
            original_message_type=orig_type,
            chunk_data=data,
        )

    def _insert_chunk(
        self,
        sender_id: bytes,
        fragment_id: bytes,
        index: int,
        total: int,
        original_message_type: int,
        chunk_data: bytes,
    ) -> bytes | None:
        """Store chunk, validate metadata, and return reassembled bytes if finished."""
        if total > self._max_fragments_per_assembly:
            raise FragmentLimitExceededError(
                f"Total {total} exceeds maximum {self._max_fragments_per_assembly}"
            )

        key = (sender_id, fragment_id)

        if key in self._assemblies:
            state = self._assemblies[key]
            self._assemblies.move_to_end(key)

            if state.total != total:
                del self._assemblies[key]
                raise InvalidFragmentError(
                    f"Inconsistent fragment total: expected {state.total}, got {total}"
                )
            if state.original_message_type != original_message_type:
                del self._assemblies[key]
                msg = (
                    f"Inconsistent original_message_type: "
                    f"expected {state.original_message_type}, "
                    f"got {original_message_type}"
                )
                raise InvalidFragmentError(msg)

            if index in state.chunks:
                if state.chunks[index] == chunk_data:
                    return None
                del self._assemblies[key]
                raise InvalidFragmentError(
                    f"Conflicting chunk data received for index {index}"
                )
        else:
            if len(self._assemblies) >= self._max_active_assemblies:
                self._assemblies.popitem(last=False)

            state = _AssemblyState(
                sender_id=sender_id,
                fragment_id=fragment_id,
                total=total,
                original_message_type=original_message_type,
            )
            self._assemblies[key] = state

        if state.total_bytes + len(chunk_data) > self._max_reassembled_bytes:
            del self._assemblies[key]
            raise FragmentLimitExceededError(
                f"Reassembled size exceeds limit {self._max_reassembled_bytes}"
            )

        state.chunks[index] = chunk_data
        state.total_bytes += len(chunk_data)

        if len(state.chunks) == state.total:
            for i in range(state.total):
                if i not in state.chunks:
                    return None

            assembled_data = b"".join(state.chunks[i] for i in range(state.total))
            del self._assemblies[key]
            return assembled_data

        return None
