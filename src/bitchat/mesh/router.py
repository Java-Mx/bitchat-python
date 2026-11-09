"""BitChat mesh routing engine coordinating TTL, deduplication, and forwarding."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass

from bitchat.mesh.dedup import PacketDeduplicator
from bitchat.mesh.store_forward import StoreAndForwardQueue
from bitchat.protocol.constants import BROADCAST_RECIPIENT
from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)

DEFAULT_MAX_RELAY_TTL: int = 10
DEFAULT_RELAY_JITTER_MIN: float = 0.010  # 10 ms
DEFAULT_RELAY_JITTER_MAX: float = 0.050  # 50 ms
DEFAULT_PEER_RATE_LIMIT: int = 50  # Max packets per second per peer
DEFAULT_MAX_ROUTES: int = 1000  # Max cached routing table entries
DEFAULT_ROUTE_TTL_SECONDS: float = 300.0  # 5 minutes


def _normalize_route_key(key: str | bytes) -> str:
    """Normalize binary or string peer ID/address into lowercase string."""
    if isinstance(key, (bytes, bytearray)):
        return bytes(key).hex().lower()
    return str(key).strip().lower()


@dataclass
class RouteEntry:
    """Mesh routing table entry mapping a destination to next hop and metric."""

    next_hop: str
    hop_count: int
    updated_at: float


@dataclass(frozen=True)
class RoutingDecision:
    """Actionable decision produced by MeshRouter for an incoming packet."""

    should_process_locally: bool
    packet_to_relay: BitchatPacket | None = None
    target_peer_id_hex: str | None = None
    exclude_ingress: str | None = None
    drop_reason: str | None = None


class MeshRouter:
    """Evaluates incoming packets against mesh rules, TTL, deduplication, and safety."""

    def __init__(
        self,
        local_peer_id: bytes,
        deduplicator: PacketDeduplicator | None = None,
        store_forward_queue: StoreAndForwardQueue | None = None,
        max_relay_ttl: int = DEFAULT_MAX_RELAY_TTL,
        relay_jitter_min: float = DEFAULT_RELAY_JITTER_MIN,
        relay_jitter_max: float = DEFAULT_RELAY_JITTER_MAX,
        rate_limit_per_peer: int = DEFAULT_PEER_RATE_LIMIT,
    ) -> None:
        self.local_peer_id = bytes(local_peer_id)
        self.deduplicator = deduplicator or PacketDeduplicator()
        self.store_forward_queue = store_forward_queue or StoreAndForwardQueue()
        self.max_relay_ttl = max_relay_ttl
        self.relay_jitter_min = relay_jitter_min
        self.relay_jitter_max = relay_jitter_max
        self.rate_limit_per_peer = rate_limit_per_peer
        self.max_routes = DEFAULT_MAX_ROUTES
        self.route_ttl_seconds = DEFAULT_ROUTE_TTL_SECONDS

        # Mesh routing table: destination_id_hex -> RouteEntry
        self._routes: dict[str, RouteEntry] = {}

        # Rate limiter state: peer_id_hex -> list of recent timestamps
        self._rate_limiter: dict[str, list[float]] = defaultdict(list)

    def prune_rate_limiter(self, max_age: float = 1.0, now: float | None = None) -> int:
        """Prune empty or expired peer entries from rate limiter dict."""
        current_time = time.time() if now is None else now
        cutoff = current_time - max_age
        to_delete = [
            peer
            for peer, timestamps in self._rate_limiter.items()
            if not timestamps or timestamps[-1] < cutoff
        ]
        for peer in to_delete:
            self._rate_limiter.pop(peer, None)
        return len(to_delete)

    def is_rate_limited(self, sender_hex: str, now: float | None = None) -> bool:
        """Check if sender has exceeded allowed packet rate within the last second."""
        current_time = time.time() if now is None else now
        if len(self._rate_limiter) > 1000:
            self.prune_rate_limiter(now=current_time)

        timestamps = self._rate_limiter.get(sender_hex)
        if not timestamps:
            self._rate_limiter[sender_hex] = [current_time]
            return False

        cutoff = current_time - 1.0
        if timestamps[-1] < cutoff:
            timestamps.clear()
            timestamps.append(current_time)
            return False

        if timestamps[0] < cutoff:
            # Drop expired prefix in-place
            idx = 0
            n = len(timestamps)
            while idx < n and timestamps[idx] < cutoff:
                idx += 1
            del timestamps[:idx]

        if len(timestamps) >= self.rate_limit_per_peer:
            return True

        timestamps.append(current_time)
        return False

    @property
    def routes(self) -> dict[str, RouteEntry]:
        """Return shallow copy of current routing table."""
        return self._routes.copy()

    def add_route(
        self,
        destination: str | bytes,
        next_hop: str | bytes,
        hop_count: int = 1,
        now: float | None = None,
    ) -> None:
        """Record or update a route to destination via next_hop."""
        dest_key = _normalize_route_key(destination)
        next_hop_str = _normalize_route_key(next_hop)
        current_time = time.time() if now is None else now

        existing = self._routes.get(dest_key)
        if existing is not None:
            if (
                current_time - existing.updated_at <= self.route_ttl_seconds
                and existing.hop_count < hop_count
            ):
                return
            existing.next_hop = next_hop_str
            existing.hop_count = hop_count
            existing.updated_at = current_time
            return

        if len(self._routes) >= self.max_routes:
            self.prune_routes(now=current_time)
            if len(self._routes) >= self.max_routes:
                oldest_dest = min(
                    self._routes.keys(), key=lambda k: self._routes[k].updated_at
                )
                self._routes.pop(oldest_dest, None)

        self._routes[dest_key] = RouteEntry(
            next_hop=next_hop_str,
            hop_count=hop_count,
            updated_at=current_time,
        )

    def get_next_hop(
        self, destination: str | bytes, now: float | None = None
    ) -> str | None:
        """Resolve the next hop address/peer_id for a given destination."""
        dest_key = _normalize_route_key(destination)
        current_time = time.time() if now is None else now
        entry = self._routes.get(dest_key)
        if entry is None:
            return None
        if current_time - entry.updated_at > self.route_ttl_seconds:
            self._routes.pop(dest_key, None)
            return None
        return entry.next_hop

    def remove_route(self, destination: str | bytes) -> None:
        """Remove a route from the routing table."""
        dest_key = _normalize_route_key(destination)
        self._routes.pop(dest_key, None)

    def prune_routes(
        self, max_age: float | None = None, now: float | None = None
    ) -> int:
        """Prune expired routes older than max_age (defaults to route_ttl_seconds)."""
        current_time = time.time() if now is None else now
        ttl = self.route_ttl_seconds if max_age is None else max_age
        expired = [
            k
            for k, entry in self._routes.items()
            if current_time - entry.updated_at > ttl
        ]
        for k in expired:
            self._routes.pop(k, None)
        return len(expired)

    def get_relay_jitter(self) -> float:
        """Return random jitter delay in seconds to mitigate radio collision."""
        return random.uniform(self.relay_jitter_min, self.relay_jitter_max)

    def evaluate_incoming(
        self,
        packet: BitchatPacket,
        ingress_source: str | None = None,
        now: float | None = None,
    ) -> RoutingDecision:
        """Evaluate an incoming packet and determine local and relay actions."""
        current_time = time.time() if now is None else now

        # 1. Loop prevention: ignore packets we originated
        if packet.sender_id == self.local_peer_id:
            return RoutingDecision(
                should_process_locally=False,
                drop_reason="Packet originated from local peer",
            )

        sender_hex = packet.sender_id.hex()

        # 2. Rate limiting per peer
        if self.is_rate_limited(sender_hex, now=current_time):
            logger.warning(
                "Packet dropped: rate limit exceeded for peer %s", sender_hex
            )
            return RoutingDecision(
                should_process_locally=False,
                drop_reason=f"Rate limit exceeded for {sender_hex}",
            )

        # 3. Basic TTL check
        if packet.ttl <= 0:
            return RoutingDecision(
                should_process_locally=False,
                drop_reason="Invalid or expired TTL (<= 0)",
            )

        # 4. Deduplication (TTL-invariant key covers original and decremented packet)
        if self.deduplicator.check_and_record(packet, now=current_time):
            return RoutingDecision(
                should_process_locally=False,
                drop_reason="Duplicate packet suppressed",
            )

        # 5. Route learning from valid incoming packet
        if ingress_source:
            hop_count = max(1, 7 - packet.ttl + 1) if packet.ttl <= 7 else 1
            self.add_route(
                destination=sender_hex,
                next_hop=ingress_source,
                hop_count=hop_count,
                now=current_time,
            )

        # 6. Determine destination
        rcpt = packet.recipient_id
        is_broadcast = rcpt is None or rcpt == BROADCAST_RECIPIENT
        is_for_us = is_broadcast or (rcpt == self.local_peer_id)

        # 7. Determine relay action
        packet_to_relay: BitchatPacket | None = None
        target_peer_id_hex: str | None = None

        if not is_for_us and rcpt is not None:
            target_peer_id_hex = rcpt.hex()

        # Relay if TTL > 1 and this node is not the exclusive destination
        if packet.ttl > 1 and (is_broadcast or not is_for_us):
            clamped_ttl = (
                packet.ttl if packet.ttl <= self.max_relay_ttl else self.max_relay_ttl
            )
            decremented_ttl = clamped_ttl - 1
            if decremented_ttl >= 1:
                packet_to_relay = BitchatPacket._from_trusted(
                    version=packet.version,
                    message_type=packet.message_type,
                    ttl=decremented_ttl,
                    timestamp=packet.timestamp,
                    flags=packet.flags,
                    sender_id=packet.sender_id,
                    recipient_id=rcpt,
                    payload=packet.payload,
                    signature=packet.signature,
                )

        return RoutingDecision(
            should_process_locally=is_for_us,
            packet_to_relay=packet_to_relay,
            target_peer_id_hex=target_peer_id_hex,
            exclude_ingress=ingress_source,
        )
