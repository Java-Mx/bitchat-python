"""Packet deduplication subsystem for BitChat mesh routing."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bitchat.protocol.packet import BitchatPacket

DEFAULT_MAX_ENTRIES: int = 2000
DEFAULT_ENTRY_TTL_SECONDS: float = 300.0


def compute_packet_id(packet: BitchatPacket) -> str:
    """Compute deterministic, TTL-invariant identifier for a BitChat packet.

    Because packets decrement their TTL byte hop-by-hop as they traverse the mesh,
    the deduplication key is calculated over immutable packet identity fields:
    (sender_id, timestamp, message_type, recipient_id, payload).
    """
    hasher = hashlib.sha256()
    hasher.update(packet.sender_id)
    hasher.update(packet.timestamp.to_bytes(8, byteorder="big"))
    hasher.update(bytes([int(packet.message_type)]))
    if packet.recipient_id is not None:
        hasher.update(packet.recipient_id)
    hasher.update(packet.payload)
    return hasher.digest()[:16].hex()


class PacketDeduplicator:
    """Bounded, time-aware LRU cache for packet deduplication."""

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
        """Check whether packet has already been observed within the TTL window."""
        packet_id = compute_packet_id(packet)
        return self.is_id_duplicate(packet_id, now=now)

    def is_id_duplicate(self, packet_id: str, now: float | None = None) -> bool:
        """Check if packet identifier is currently in the deduplication cache."""
        current_time = time.time() if now is None else now
        if packet_id not in self._entries:
            return False

        recorded_time = self._entries[packet_id]
        if current_time - recorded_time > self.entry_ttl_seconds:
            # Expired entry
            del self._entries[packet_id]
            return False

        return True

    def record(self, packet: BitchatPacket, now: float | None = None) -> None:
        """Record packet identifier in the deduplication cache."""
        packet_id = compute_packet_id(packet)
        self.record_id(packet_id, now=now)

    def record_id(self, packet_id: str, now: float | None = None) -> None:
        """Record packet ID with the current timestamp and maintain capacity bound."""
        current_time = time.time() if now is None else now

        # Update position in LRU order
        if packet_id in self._entries:
            del self._entries[packet_id]
        elif len(self._entries) >= self.max_entries:
            # Evict oldest entry (FIFO / least recently inserted)
            self._entries.popitem(last=False)

        self._entries[packet_id] = current_time

    def check_and_record(self, packet: BitchatPacket, now: float | None = None) -> bool:
        """Check if duplicate, recording it if new.

        Returns True if the packet is a duplicate (already seen and valid).
        Returns False if the packet is new and was recorded.
        """
        packet_id = compute_packet_id(packet)
        if self.is_id_duplicate(packet_id, now=now):
            return True

        self.record_id(packet_id, now=now)
        return False

    def prune_expired(self, now: float | None = None) -> int:
        """Evict all entries that have exceeded entry_ttl_seconds."""
        current_time = time.time() if now is None else now
        pruned_count = 0

        # Since insertion order is chronological, scan from oldest to newest
        for key in list(self._entries.keys()):
            if current_time - self._entries[key] > self.entry_ttl_seconds:
                del self._entries[key]
                pruned_count += 1
            else:
                # Subsequent entries are newer and thus also not expired
                break

        return pruned_count

    def clear(self) -> None:
        """Clear all recorded entries."""
        self._entries.clear()

    def __len__(self) -> int:
        """Return number of recorded packet IDs currently tracked."""
        return len(self._entries)
