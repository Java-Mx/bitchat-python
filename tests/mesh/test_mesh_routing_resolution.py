"""Regression and unit tests for multi-hop mesh routing resolution and cache pruning."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from bitchat.app.session_coordinator import MAX_TTL, SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.mesh.store_forward import StoreAndForwardQueue
from bitchat.protocol.constants import MessageType
from bitchat.protocol.packet import BitchatPacket
from bitchat.storage.config import InMemoryStorage
from bitchat.transport.base import BaseTransport, TransportState, TransportType


class DummyTransport(BaseTransport):
    """Minimal transport for isolating SessionCoordinator mesh logic."""

    def __init__(self, address: str = "local_node") -> None:
        super().__init__()
        self.address = address
        self._connected: list[str] = []
        self._discovered: dict[str, Any] = {}
        self._state: TransportState = TransportState.READY
        self.sent_packets: list[tuple[str, BitchatPacket]] = []
        self.broadcast_packets: list[tuple[BitchatPacket, str | None]] = []

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
        return list(self._connected)

    @property
    def discovered_peers(self) -> dict[str, Any]:
        return self._discovered

    async def start(self) -> None:
        self._state = TransportState.CONNECTED

    async def stop(self) -> None:
        self._state = TransportState.OFFLINE

    async def start_discovery(self) -> None:
        pass

    async def stop_discovery(self) -> None:
        pass

    async def connect_peer(self, address: str, timeout: float = 10.0) -> Any:
        self._connected.append(address)

    async def disconnect_peer(self, address: str) -> None:
        if address in self._connected:
            self._connected.remove(address)

    async def send_to_peer(self, address: str, packet: BitchatPacket) -> None:
        self.sent_packets.append((address, packet))

    async def broadcast_packet(
        self, packet: BitchatPacket, exclude_address: str | None = None
    ) -> None:
        self.broadcast_packets.append((packet, exclude_address))

    def update_identity(self, peer_id_hex: str, nickname: str) -> None:
        pass

    def resolve_peer_id_to_address(self, target: str) -> str | None:
        return target if target in self._connected else None

    def get_telemetry(self) -> dict[str, Any]:
        return {"status": "Connected"}


def _make_coordinator(
    nickname: str = "TestNode",
) -> tuple[SessionCoordinator, DummyTransport]:
    identity = LocalIdentity.generate()
    storage = InMemoryStorage()
    transport = DummyTransport()
    coord = SessionCoordinator(
        local_identity=identity,
        transport=transport,
        storage=storage,
        nickname=nickname,
    )
    return coord, transport


@pytest.mark.asyncio
async def test_direct_neighbor_mapping_update() -> None:
    """Packets from 1-hop physical neighbor update address mapping tables."""
    coord, _ = _make_coordinator("NodeA")
    neighbor_id = LocalIdentity.generate()
    neighbor_hex = neighbor_id.peer_id_hex
    neighbor_addr = "PHYSICAL_NEIGHBOR_1"

    # Packet originating directly (ttl == MAX_TTL)
    direct_pkt = BitchatPacket.create(
        message_type=MessageType.Announce,
        sender_id=neighbor_id.peer_id,
        payload=b"Neighbor",
        ttl=MAX_TTL,
    )

    await coord._process_packet_async(direct_pkt, peer_address=neighbor_addr)

    # Physical neighbor mapping must be recorded
    assert coord.address_to_peer_id.get(neighbor_addr) == neighbor_hex
    assert coord.peer_addresses.get(neighbor_hex) == neighbor_addr

    # Mesh router must also record route
    assert coord.mesh_router.get_next_hop(neighbor_hex) == neighbor_hex


@pytest.mark.asyncio
async def test_relayed_multihop_packet_does_not_corrupt_physical_neighbor_mapping() -> (
    None
):
    """Relayed packets (ttl < MAX_TTL) MUST NOT overwrite neighbor mappings."""
    coord, _ = _make_coordinator("NodeA")

    # Relay node is the direct physical link
    relay_id = LocalIdentity.generate()
    relay_hex = relay_id.peer_id_hex
    relay_addr = "RELAY_PHYSICAL_ADDR"

    # Direct 1-hop announcement from Relay establishes its physical address
    relay_pkt = BitchatPacket.create(
        message_type=MessageType.Announce,
        sender_id=relay_id.peer_id,
        payload=b"Relay",
        ttl=MAX_TTL,
    )
    await coord._process_packet_async(relay_pkt, peer_address=relay_addr)
    assert coord.address_to_peer_id[relay_addr] == relay_hex
    assert coord.peer_addresses[relay_hex] == relay_addr

    # Distant node C (2 hops away) sends Announce via Relay (ttl < MAX_TTL)
    node_c_id = LocalIdentity.generate()
    node_c_hex = node_c_id.peer_id_hex

    relayed_pkt = BitchatPacket.create(
        message_type=MessageType.Announce,
        sender_id=node_c_id.peer_id,
        payload=b"NodeC",
        ttl=MAX_TTL - 1,  # Decremented by relay
    )
    await coord._process_packet_async(relayed_pkt, peer_address=relay_addr)

    # CRITICAL: Physical link address mapping MUST NOT be corrupted
    assert coord.address_to_peer_id[relay_addr] == relay_hex
    assert coord.address_to_peer_id[relay_addr] != node_c_hex
    assert node_c_hex not in coord.peer_addresses

    # MeshRouter route table should know that Node C is reachable via Relay
    assert coord.mesh_router.get_next_hop(node_c_hex) == relay_hex


def test_mesh_router_routing_table_resolution() -> None:
    """MeshRouter accurately adds, retrieves, prioritizes, and prunes routes."""
    router = MeshRouter(local_peer_id=b"\x01" * 8)

    # Add 2-hop route to node C via B
    router.add_route(destination="dest_c", next_hop="hop_b", hop_count=2)
    assert router.get_next_hop("dest_c") == "hop_b"

    # A worse route (3 hops) arriving later should NOT overwrite a better 2-hop route
    router.add_route(destination="dest_c", next_hop="hop_worse", hop_count=3)
    assert router.get_next_hop("dest_c") == "hop_b"

    # A better route (1 hop) SHOULD update the route
    router.add_route(destination="dest_c", next_hop="hop_direct", hop_count=1)
    assert router.get_next_hop("dest_c") == "hop_direct"

    # Removal of route
    router.remove_route("dest_c")
    assert router.get_next_hop("dest_c") is None


def test_mesh_router_route_expiration_and_capacity() -> None:
    """MeshRouter prunes expired routes and evicts oldest when capacity is reached."""
    router = MeshRouter(local_peer_id=b"\x01" * 8)
    router.route_ttl_seconds = 1.0

    t0 = 1000.0
    router.add_route("node_x", "hop_x", hop_count=1, now=t0)
    assert router.get_next_hop("node_x", now=t0 + 0.5) == "hop_x"
    assert router.get_next_hop("node_x", now=t0 + 1.5) is None

    # Capacity eviction
    router.route_ttl_seconds = 300.0
    router.max_routes = 3
    router.add_route("d1", "h1", now=100.0)
    router.add_route("d2", "h2", now=101.0)
    router.add_route("d3", "h3", now=102.0)
    assert len(router.routes) == 3

    # Adding 4th route evicts oldest (d1)
    router.add_route("d4", "h4", now=103.0)
    assert len(router.routes) == 3
    assert router.get_next_hop("d1", now=103.0) is None
    assert router.get_next_hop("d4", now=103.0) == "h4"


@pytest.mark.asyncio
async def test_multihop_unicast_forwarding_via_resolved_next_hop() -> None:
    """_send_packet routes unicast packets to direct neighbor via router."""
    coord, transport = _make_coordinator("SenderNode")

    relay_hex = "0102030405060708"
    relay_address = "RELAY_PHYSICAL_SOCKET"
    coord.peer_addresses[relay_hex] = relay_address
    transport._connected.append(relay_address)

    # Destination is multi-hop peer
    dest_hex = "aaaaaaaaaaaaaaaa"
    coord.mesh_router.add_route(destination=dest_hex, next_hop=relay_hex)

    pkt = BitchatPacket.create(
        message_type=MessageType.NoiseEncrypted,
        sender_id=coord.local_identity.peer_id,
        recipient_id=bytes.fromhex(dest_hex),
        payload=b"encrypted_secret",
    )

    await coord._send_packet(dest_hex, pkt)

    # Packet must be sent directly to Relay's physical socket, NOT broadcast
    assert len(transport.sent_packets) == 1
    target_addr, sent_pkt = transport.sent_packets[0]
    assert target_addr == relay_address
    assert sent_pkt.recipient_id == bytes.fromhex(dest_hex)
    assert len(transport.broadcast_packets) == 0


@pytest.mark.asyncio
async def test_periodic_cache_pruning_lifecycle() -> None:
    """Coordinator prune task cleans expired entries and cancels cleanly."""
    coord, _transport = _make_coordinator("NodeLifecycle")

    # Start coordinator
    await coord.start()
    assert coord._prune_task is not None
    assert not coord._prune_task.done()
    assert coord._prune_task in coord._background_tasks

    # Mock components to observe prune calls
    mock_reassembler = MagicMock()
    mock_dedup = MagicMock()
    mock_store_forward = MagicMock()

    coord.fragment_reassembler.prune_stale = mock_reassembler  # type: ignore[method-assign]
    coord.packet_deduplicator.prune_expired = mock_dedup  # type: ignore[method-assign]
    coord.store_forward.prune_expired = mock_store_forward  # type: ignore[method-assign]

    coord.prune_caches()
    mock_reassembler.assert_called_once()
    mock_dedup.assert_called_once()
    mock_store_forward.assert_called_once()

    # Stop coordinator and verify clean cancellation
    prune_task = coord._prune_task
    await coord.stop()
    assert prune_task.cancelled() or prune_task.done()
    assert coord._prune_task is None
    assert len(coord._background_tasks) == 0


def test_store_and_forward_capacity_and_bounds() -> None:
    """StoreAndForwardQueue enforces bounds and expires stale packets."""
    queue = StoreAndForwardQueue(
        max_total_packets=3,
        max_per_peer=2,
        max_total_bytes=1000,
        packet_ttl_seconds=5.0,
    )

    p1 = BitchatPacket.create(MessageType.Message, b"\x01" * 8, b"one")
    p2 = BitchatPacket.create(MessageType.Message, b"\x01" * 8, b"two")
    p3 = BitchatPacket.create(MessageType.Message, b"\x01" * 8, b"three")

    # Per-peer bound: max 2 packets per peer
    assert queue.enqueue("peer_a", p1, now=10.0) is True
    assert queue.enqueue("peer_a", p2, now=11.0) is True
    assert queue.enqueue("peer_a", p3, now=12.0) is True  # Evicts p1

    dequeued = queue.dequeue_for_peer("peer_a", now=13.0)
    assert len(dequeued) == 2
    assert dequeued[0].payload == b"two"
    assert dequeued[1].payload == b"three"

    # Rejection of oversized packet
    huge_pkt = BitchatPacket.create(MessageType.Message, b"\x01" * 8, b"X" * 1500)
    assert queue.enqueue("peer_b", huge_pkt) is False
