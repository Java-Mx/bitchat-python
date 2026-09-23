"""BitChat mesh routing engine coordinating TTL, deduplication, and forwarding."""

from __future__ import annotations

import logging
import random
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from bitchat.mesh.dedup import PacketDeduplicator
from bitchat.mesh.store_forward import StoreAndForwardQueue
from bitchat.protocol.constants import BROADCAST_RECIPIENT

if TYPE_CHECKING:
    from bitchat.protocol.packet import BitchatPacket

logger = logging.getLogger(__name__)

DEFAULT_MAX_RELAY_TTL: int = 10
DEFAULT_RELAY_JITTER_MIN: float = 0.010  # 10 ms
DEFAULT_RELAY_JITTER_MAX: float = 0.050  # 50 ms
DEFAULT_PEER_RATE_LIMIT: int = 50  # Max packets per second per peer


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

        # Rate limiter state: peer_id_hex -> list of recent timestamps
        self._rate_limiter: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, sender_hex: str, now: float | None = None) -> bool:
        """Check if sender has exceeded allowed packet rate within the last second."""
        current_time = time.time() if now is None else now
        timestamps = self._rate_limiter[sender_hex]

        # Filter out timestamps older than 1 second
        valid = [t for t in timestamps if current_time - t <= 1.0]
        self._rate_limiter[sender_hex] = valid

        if len(valid) >= self.rate_limit_per_peer:
            return True

        valid.append(current_time)
        return False

    def get_relay_jitter(self) -> float:
        """Return random jitter delay in seconds to mitigate radio collision."""
        return random.uniform(self.relay_jitter_min, self.relay_jitter_max)

    def evaluate_incoming(
        self,
        packet: BitchatPacket,
        ingress_source: str | None = None,
        now: float | None = None,
    ) -> RoutingDecision:
        """Evaluate an incoming packet and determine local processing and relay actions.

        Enforces:
        1. Drop packets from local peer ID (loop prevention).
        2. Ingress rate-limiting per peer.
        3. TTL validation (drop TTL=0).
        4. Deduplication suppression.
        5. Forwarding with decremented TTL if TTL > 1.
        """
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

        # 4. Deduplication
        if self.deduplicator.check_and_record(packet, now=current_time):
            return RoutingDecision(
                should_process_locally=False,
                drop_reason="Duplicate packet suppressed",
            )

        # 5. Determine destination
        is_broadcast = (
            packet.recipient_id is None or packet.recipient_id == BROADCAST_RECIPIENT
        )
        is_for_us = is_broadcast or (packet.recipient_id == self.local_peer_id)

        # 6. Determine relay action
        packet_to_relay: BitchatPacket | None = None
        target_peer_id_hex: str | None = None

        if not is_for_us:
            # Unicast packet destined for another node
            target_peer_id_hex = (
                packet.recipient_id.hex() if packet.recipient_id else None
            )

        # Relay if TTL > 1 and this node is not the exclusive destination
        if packet.ttl > 1 and not (not is_broadcast and is_for_us):
            # Clamp TTL to safety ceiling and decrement by 1
            clamped_ttl = min(packet.ttl, self.max_relay_ttl)
            decremented_ttl = clamped_ttl - 1

            packet_to_relay = replace(packet, ttl=decremented_ttl)
            # Record the decremented packet in dedup cache as well
            self.deduplicator.record(packet_to_relay, now=current_time)

        return RoutingDecision(
            should_process_locally=is_for_us,
            packet_to_relay=packet_to_relay,
            target_peer_id_hex=target_peer_id_hex,
            exclude_ingress=ingress_source,
        )
