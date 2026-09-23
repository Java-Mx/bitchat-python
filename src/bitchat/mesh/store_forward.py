"""Store-and-Forward queue for disconnected or transient mesh peers."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bitchat.protocol.packet import BitchatPacket

DEFAULT_MAX_TOTAL_PACKETS: int = 100
DEFAULT_MAX_PER_PEER: int = 20
DEFAULT_MAX_TOTAL_BYTES: int = 256 * 1024  # 256 KB
DEFAULT_PACKET_TTL_SECONDS: float = 300.0


def _normalize_peer_id(peer: str | bytes) -> str:
    """Normalize binary or hex peer ID into lowercase hex string."""
    if isinstance(peer, (bytes, bytearray)):
        return bytes(peer).hex().lower()
    return peer.strip().lower()


@dataclass(frozen=True)
class QueuedPacket:
    """Packet envelope within the Store-and-Forward queue."""

    packet: BitchatPacket
    enqueued_at: float
    byte_size: int


class StoreAndForwardQueue:
    """Bounded, memory-capped Store-and-Forward buffer."""

    def __init__(
        self,
        max_total_packets: int = DEFAULT_MAX_TOTAL_PACKETS,
        max_per_peer: int = DEFAULT_MAX_PER_PEER,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        packet_ttl_seconds: float = DEFAULT_PACKET_TTL_SECONDS,
    ) -> None:
        self.max_total_packets = max_total_packets
        self.max_per_peer = max_per_peer
        self.max_total_bytes = max_total_bytes
        self.packet_ttl_seconds = packet_ttl_seconds

        self._queues: dict[str, deque[QueuedPacket]] = {}
        self._current_total_packets: int = 0
        self._current_total_bytes: int = 0

    @property
    def total_packets(self) -> int:
        """Return total number of currently stored packets."""
        return self._current_total_packets

    @property
    def total_bytes(self) -> int:
        """Return current memory footprint in bytes."""
        return self._current_total_bytes

    @property
    def peer_count(self) -> int:
        """Return number of distinct peers with queued packets."""
        return len(self._queues)

    def enqueue(
        self,
        target_peer_id: str | bytes,
        packet: BitchatPacket,
        now: float | None = None,
    ) -> bool:
        """Enqueue packet for delivery to target peer once connected.

        Returns True if packet was accepted into queue, False if rejected
        due to memory limits or capacity constraints.
        """
        current_time = time.time() if now is None else now
        self.prune_expired(now=current_time)

        # Estimate packet wire/memory size
        pkt_size = len(packet.payload) + 32  # Header + payload overhead estimate

        # Reject if single packet exceeds total queue capacity
        if pkt_size > self.max_total_bytes:
            return False

        peer_key = _normalize_peer_id(target_peer_id)
        peer_queue = self._queues.setdefault(peer_key, deque())

        # Enforce per-peer limit: evict oldest packet for this peer if full
        if len(peer_queue) >= self.max_per_peer:
            evicted = peer_queue.popleft()
            self._current_total_packets -= 1
            self._current_total_bytes -= evicted.byte_size

        # Enforce global total packets limit: evict oldest from global queues
        while self._current_total_packets >= self.max_total_packets:
            self._evict_oldest()

        # Enforce global byte budget: evict oldest until room is available
        while (
            self._current_total_bytes + pkt_size > self.max_total_bytes
            and self._current_total_packets > 0
        ):
            self._evict_oldest()

        # If after eviction we still exceed, reject
        if self._current_total_bytes + pkt_size > self.max_total_bytes:
            return False

        queued = QueuedPacket(
            packet=packet,
            enqueued_at=current_time,
            byte_size=pkt_size,
        )
        peer_queue.append(queued)
        self._current_total_packets += 1
        self._current_total_bytes += pkt_size
        return True

    def _evict_oldest(self) -> None:
        """Evict the globally oldest queued packet."""
        oldest_peer: str | None = None
        oldest_time: float = float("inf")

        for peer_id, queue in self._queues.items():
            if queue and queue[0].enqueued_at < oldest_time:
                oldest_time = queue[0].enqueued_at
                oldest_peer = peer_id

        if oldest_peer is not None:
            queue = self._queues[oldest_peer]
            evicted = queue.popleft()
            self._current_total_packets -= 1
            self._current_total_bytes -= evicted.byte_size
            if not queue:
                del self._queues[oldest_peer]

    def dequeue_for_peer(
        self,
        target_peer_id: str | bytes,
        now: float | None = None,
    ) -> list[BitchatPacket]:
        """Retrieve and remove all valid queued packets for target peer."""
        current_time = time.time() if now is None else now
        peer_key = _normalize_peer_id(target_peer_id)
        queue = self._queues.pop(peer_key, None)
        if not queue:
            return []

        packets: list[BitchatPacket] = []
        for item in queue:
            self._current_total_packets -= 1
            self._current_total_bytes -= item.byte_size
            # Only deliver unexpired packets
            if current_time - item.enqueued_at <= self.packet_ttl_seconds:
                packets.append(item.packet)

        return packets

    def has_pending(self, target_peer_id: str | bytes) -> bool:
        """Return True if there are pending packets queued for peer."""
        peer_key = _normalize_peer_id(target_peer_id)
        return bool(self._queues.get(peer_key))

    def prune_expired(self, now: float | None = None) -> int:
        """Remove packets that have exceeded packet_ttl_seconds."""
        current_time = time.time() if now is None else now
        pruned_count = 0

        for peer_key in list(self._queues.keys()):
            queue = self._queues[peer_key]
            while queue and (
                current_time - queue[0].enqueued_at > self.packet_ttl_seconds
            ):
                expired = queue.popleft()
                self._current_total_packets -= 1
                self._current_total_bytes -= expired.byte_size
                pruned_count += 1
            if not queue:
                del self._queues[peer_key]

        return pruned_count

    def clear(self) -> None:
        """Clear all stored packets and reset counters."""
        self._queues.clear()
        self._current_total_packets = 0
        self._current_total_bytes = 0
