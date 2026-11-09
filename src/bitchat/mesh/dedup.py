"""Packet deduplication subsystem for BitChat mesh routing."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

from bitchat._native import HAS_NATIVE_CORE, _core

if TYPE_CHECKING:
    from bitchat.protocol.packet import BitchatPacket

DEFAULT_MAX_ENTRIES: int = 2000
DEFAULT_ENTRY_TTL_SECONDS: float = 300.0


def py_compute_packet_id(packet: BitchatPacket) -> str:
    """Pure-Python reference implementation of compute_packet_id."""
    hasher = hashlib.sha256()
    hasher.update(packet.sender_id)
    hasher.update(packet.timestamp.to_bytes(8, byteorder="big"))
    hasher.update(bytes([int(packet.message_type)]))
    if packet.recipient_id is not None:
        hasher.update(packet.recipient_id)
    hasher.update(packet.payload)
    return hasher.digest()[:16].hex()


def compute_packet_id(packet: BitchatPacket) -> str:
    """Compute deterministic, TTL-invariant identifier for a BitChat packet.

    Because packets decrement their TTL byte hop-by-hop as they traverse the mesh,
    the deduplication key is calculated over immutable packet identity fields:
    (sender_id, timestamp, message_type, recipient_id, payload).
    """
    if HAS_NATIVE_CORE:
        return _core.compute_packet_id_raw(
            packet.sender_id,
            packet.timestamp,
            int(packet.message_type),
            packet.recipient_id,
            packet.payload,
        )
    return py_compute_packet_id(packet)


class PyPacketDeduplicator:
    """Pure-Python reference implementation of PacketDeduplicator."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        entry_ttl_seconds: float = DEFAULT_ENTRY_TTL_SECONDS,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")
        if entry_ttl_seconds <= 0:
            raise ValueError("entry_ttl_seconds must be greater than zero")

        self.max_entries = max_entries
        self.entry_ttl_seconds = entry_ttl_seconds
        self._entries: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, packet: BitchatPacket, now: float | None = None) -> bool:
        packet_id = py_compute_packet_id(packet)
        return self.is_id_duplicate(packet_id, now=now)

    def is_id_duplicate(self, packet_id: str, now: float | None = None) -> bool:
        current_time = time.time() if now is None else now
        if packet_id not in self._entries:
            return False

        recorded_time = self._entries[packet_id]
        if current_time - recorded_time > self.entry_ttl_seconds:
            del self._entries[packet_id]
            return False

        return True

    def record(self, packet: BitchatPacket, now: float | None = None) -> None:
        packet_id = py_compute_packet_id(packet)
        self.record_id(packet_id, now=now)

    def record_id(self, packet_id: str, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        if packet_id in self._entries:
            del self._entries[packet_id]
        elif len(self._entries) >= self.max_entries:
            self._entries.popitem(last=False)
        self._entries[packet_id] = current_time

    def check_and_record(self, packet: BitchatPacket, now: float | None = None) -> bool:
        packet_id = py_compute_packet_id(packet)
        if self.is_id_duplicate(packet_id, now=now):
            return True
        self.record_id(packet_id, now=now)
        return False

    def prune_expired(self, now: float | None = None) -> int:
        current_time = time.time() if now is None else now
        pruned_count = 0
        for key in list(self._entries.keys()):
            if current_time - self._entries[key] > self.entry_ttl_seconds:
                del self._entries[key]
                pruned_count += 1
            else:
                break
        return pruned_count

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class _NativeEntriesView:
    """Compatibility view exposing `len(dedup._entries)` over Rust core."""

    def __init__(self, native: object) -> None:
        self._native = native

    def __len__(self) -> int:
        return int(self._native.size())  # type: ignore[attr-defined]


class PacketDeduplicator:
    """Bounded, time-aware LRU cache for packet deduplication (Rust-accelerated)."""

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        entry_ttl_seconds: float = DEFAULT_ENTRY_TTL_SECONDS,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than zero")
        if entry_ttl_seconds <= 0:
            raise ValueError("entry_ttl_seconds must be greater than zero")

        self.max_entries = max_entries
        self.entry_ttl_seconds = float(entry_ttl_seconds)
        if HAS_NATIVE_CORE:
            self._native = _core.NativePacketDeduplicator(
                max_entries=max_entries,
                entry_ttl_seconds=float(entry_ttl_seconds),
            )
            self._py: PyPacketDeduplicator | None = None
        else:
            self._native = None
            self._py = PyPacketDeduplicator(
                max_entries=max_entries,
                entry_ttl_seconds=float(entry_ttl_seconds),
            )

    def is_duplicate(self, packet: BitchatPacket, now: float | None = None) -> bool:
        """Check whether packet has already been observed within the TTL window."""
        packet_id = compute_packet_id(packet)
        return self.is_id_duplicate(packet_id, now=now)

    def is_id_duplicate(self, packet_id: str, now: float | None = None) -> bool:
        """Check if packet identifier is currently in the deduplication cache."""
        current_time = time.time() if now is None else float(now)
        if self._native is not None:
            return self._native.is_id_duplicate(packet_id, current_time)
        assert self._py is not None
        return self._py.is_id_duplicate(packet_id, now=current_time)

    def record(self, packet: BitchatPacket, now: float | None = None) -> None:
        """Record packet identifier in the deduplication cache."""
        packet_id = compute_packet_id(packet)
        self.record_id(packet_id, now=now)

    def record_id(self, packet_id: str, now: float | None = None) -> None:
        """Record packet ID with the current timestamp and maintain capacity bound."""
        current_time = time.time() if now is None else float(now)
        if self._native is not None:
            self._native.record_id(packet_id, current_time)
            return
        assert self._py is not None
        self._py.record_id(packet_id, now=current_time)

    def check_and_record(self, packet: BitchatPacket, now: float | None = None) -> bool:
        """Check if duplicate, recording it if new.

        Returns True if the packet is a duplicate (already seen and valid).
        Returns False if the packet is new and was recorded.
        """
        current_time = time.time() if now is None else float(now)
        if self._native is not None:
            return self._native.check_and_record_raw(
                packet.sender_id,
                packet.timestamp,
                int(packet.message_type),
                packet.recipient_id,
                packet.payload,
                current_time,
            )
        assert self._py is not None
        return self._py.check_and_record(packet, now=current_time)

    def prune_expired(self, now: float | None = None) -> int:
        """Evict all entries that have exceeded entry_ttl_seconds."""
        current_time = time.time() if now is None else float(now)
        if self._native is not None:
            return self._native.prune_expired(current_time)
        assert self._py is not None
        return self._py.prune_expired(now=current_time)

    def clear(self) -> None:
        """Clear all recorded entries."""
        if self._native is not None:
            self._native.clear()
            return
        assert self._py is not None
        self._py.clear()

    def __len__(self) -> int:
        """Return number of recorded packet IDs currently tracked."""
        if self._native is not None:
            return self._native.size()
        assert self._py is not None
        return len(self._py)

    @property
    def _entries(self) -> _NativeEntriesView | OrderedDict[str, float]:
        if self._native is not None:
            return _NativeEntriesView(self._native)
        assert self._py is not None
        return self._py._entries
