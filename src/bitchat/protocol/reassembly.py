"""BitChat protocol packet reassembly."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from bitchat._native import HAS_NATIVE_CORE, _core, raise_mapped_error
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
    _native_ref: object = field(default=None, repr=False, compare=False)

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
        if name == "created_at" and getattr(self, "_native_ref", None) is not None:
            self._native_ref.set_created_at(  # type: ignore[attr-defined]
                self.sender_id,
                self.fragment_id,
                float(value),  # type: ignore[arg-type]
            )


class _NativeAssembliesView:
    """Compatibility view exposing `_AssemblyState` over `NativeFragmentReassembler`."""

    def __init__(self, native: object) -> None:
        self._native = native

    def __contains__(self, key: tuple[bytes, bytes]) -> bool:
        if not isinstance(key, tuple) or len(key) != 2:
            return False
        sender_id, fragment_id = key
        return (
            self._native.get_assembly_stats(sender_id, fragment_id) is not None  # type: ignore[attr-defined]
        )

    def __getitem__(self, key: tuple[bytes, bytes]) -> _AssemblyState:
        sender_id, fragment_id = key
        stats = self._native.get_assembly_stats(sender_id, fragment_id)  # type: ignore[attr-defined]
        if stats is None:
            raise KeyError(key)
        chunk_count, total_bytes, created_at, total, orig_type = stats
        return _AssemblyState(
            sender_id=sender_id,
            fragment_id=fragment_id,
            total=total,
            original_message_type=orig_type,
            chunks={i: b"" for i in range(chunk_count)},
            created_at=created_at,
            total_bytes=total_bytes,
            _native_ref=self._native,
        )


class PyFragmentReassembler:
    """Pure-Python reference implementation of FragmentReassembler."""

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

    def prune_stale(self, max_age_seconds: float = 60.0) -> int:
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
        if total <= 0:
            raise InvalidFragmentError(f"total must be > 0, got {total}")
        if not (0 <= index < total):
            raise InvalidFragmentError(
                f"index out of bounds: index={index}, total={total}"
            )
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
        if HAS_NATIVE_CORE:
            self._native = _core.NativeFragmentReassembler(
                max_active_assemblies=max_active_assemblies,
                max_fragments_per_assembly=max_fragments_per_assembly,
                max_reassembled_bytes=max_reassembled_bytes,
            )
            self._py: PyFragmentReassembler | None = None
        else:
            self._native = None
            self._py = PyFragmentReassembler(
                max_active_assemblies=max_active_assemblies,
                max_fragments_per_assembly=max_fragments_per_assembly,
                max_reassembled_bytes=max_reassembled_bytes,
            )

    @property
    def _assemblies(
        self,
    ) -> _NativeAssembliesView | OrderedDict[tuple[bytes, bytes], _AssemblyState]:
        if self._native is not None:
            return _NativeAssembliesView(self._native)
        assert self._py is not None
        return self._py._assemblies

    def _insert_chunk(
        self,
        sender_id: bytes,
        fragment_id: bytes,
        index: int,
        total: int,
        original_message_type: int,
        chunk_data: bytes,
    ) -> bytes | None:
        """Internal chunk insertion helper compatible with PyFragmentReassembler."""
        if self._native is not None:
            sender_b = sender_id if type(sender_id) is bytes else bytes(sender_id)
            fid_b = fragment_id if type(fragment_id) is bytes else bytes(fragment_id)
            chunk_b = chunk_data if type(chunk_data) is bytes else bytes(chunk_data)
            try:
                return self._native.insert_chunk_raw(
                    sender_b,
                    fid_b,
                    int(index),
                    int(total),
                    int(original_message_type) & 0xFF,
                    chunk_b,
                )
            except ValueError as exc:
                raise_mapped_error(exc)
        assert self._py is not None
        return self._py._insert_chunk(
            sender_id=sender_id,
            fragment_id=fragment_id,
            index=index,
            total=total,
            original_message_type=original_message_type,
            chunk_data=chunk_data,
        )

    @property
    def active_assembly_count(self) -> int:
        """Return number of currently active in-progress assemblies."""
        if self._native is not None:
            return self._native.active_assembly_count
        assert self._py is not None
        return self._py.active_assembly_count

    def clear(self) -> None:
        """Clear all in-flight assemblies."""
        if self._native is not None:
            self._native.clear()
            return
        assert self._py is not None
        self._py.clear()

    def prune_stale(self, max_age_seconds: float = 60.0) -> int:
        """Remove assemblies older than max_age_seconds, returning count removed."""
        if self._native is not None:
            return self._native.prune_stale(max_age_seconds=max_age_seconds)
        assert self._py is not None
        return self._py.prune_stale(max_age_seconds=max_age_seconds)

    def add_fragment_packet(self, packet: BitchatPacket) -> bytes | None:
        """Process a fragment packet and return reassembled bytes when complete."""
        if not isinstance(packet, BitchatPacket):
            raise InvalidFragmentError(
                f"Expected BitchatPacket, got {type(packet).__name__}"
            )
        if self._native is not None:
            try:
                return self._native.add_fragment_raw(
                    int(packet.message_type),
                    packet.sender_id,
                    packet.payload,
                )
            except ValueError as exc:
                raise_mapped_error(exc)
        assert self._py is not None
        return self._py.add_fragment_packet(packet)

    def add_fragment(self, sender_id: bytes, payload: bytes) -> bytes | None:
        """Process a raw fragment payload and return reassembled bytes when complete."""
        if not isinstance(sender_id, (bytes, bytearray)):
            raise InvalidFragmentError("sender_id must be bytes")
        if not isinstance(payload, (bytes, bytearray)):
            from bitchat.exceptions import FragmentPayloadError

            raise FragmentPayloadError(f"Expected bytes, got {type(payload).__name__}")
        if self._native is not None:
            sender_b = sender_id if type(sender_id) is bytes else bytes(sender_id)
            payload_b = payload if type(payload) is bytes else bytes(payload)
            try:
                return self._native.add_fragment(sender_b, payload_b)
            except ValueError as exc:
                raise_mapped_error(exc)
        assert self._py is not None
        return self._py.add_fragment(sender_id, payload)
