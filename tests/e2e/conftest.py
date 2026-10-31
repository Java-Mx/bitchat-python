"""Shared fixtures, mock networks, and test helpers for E2E tests."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner, MockBLEServerBackend

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.storage.config import InMemoryStorage

if TYPE_CHECKING:
    from collections.abc import Callable

    from bitchat.mesh.router import MeshRouter


def create_packet(
    sender_id: bytes,
    payload: bytes,
    message_type: MessageType = MessageType.Message,
    recipient_id: bytes | None = None,
    ttl: int = 5,
    timestamp: int | None = None,
    flags: int = 0,
) -> BitchatPacket:
    """Helper to create a validated BitchatPacket instance."""
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    actual_flags = flags
    if recipient_id is not None:
        actual_flags |= FLAG_HAS_RECIPIENT

    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=message_type,
        ttl=ttl,
        timestamp=timestamp,
        flags=actual_flags,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        signature=None,
    )


async def wait_until(
    predicate: Callable[[], bool],
    timeout: float = 3.0,
    interval: float = 0.02,
) -> None:
    """Poll predicate until True or timeout raises AssertionError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    if not predicate():
        raise AssertionError(f"Condition not met within {timeout}s timeout")


class E2ENode:
    """Represents an independent BitChat participant node in an E2E test."""

    def __init__(
        self,
        nickname: str,
        address: str,
        identity: LocalIdentity | None = None,
        mesh_router: MeshRouter | None = None,
    ) -> None:
        self.nickname = nickname
        self.address = address
        self.identity = identity or LocalIdentity.generate()
        self.storage = InMemoryStorage()
        self.storage.save_identity(self.identity)

        self.server_backend = MockBLEServerBackend()
        self.server = BLEServer(backend=self.server_backend)

        self.received_messages: list[tuple[str, str, bool]] = []
        self.peer_status_events: list[tuple[str, str]] = []
        self.completed_handshakes: list[tuple[str, str]] = []

        self.clients: dict[str, MockBleakClient] = {}

        def mock_scanner(**kw: Any) -> MockBleakScanner:
            return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

        def client_factory(addr: str, **kw: Any) -> MockBleakClient:
            if addr not in self.clients:
                self.clients[addr] = MockBleakClient(address=addr)
            return self.clients[addr]

        self.manager = BLEManager(
            sender_id=self.identity.peer_id,
            client_factory=client_factory,
            scanner_factory=mock_scanner,
        )

        self.coordinator = SessionCoordinator(
            local_identity=self.identity,
            ble_manager=self.manager,
            ble_server=self.server,
            storage=self.storage,
            nickname=self.nickname,
            on_message_received=self._on_message,
            on_peer_status_changed=self._on_peer_status,
            on_handshake_completed=self._on_handshake_done,
            inter_fragment_delay=0.001,
            mesh_router=mesh_router,
        )

    def _on_message(self, sender: str, msg: str, enc: bool) -> None:
        self.received_messages.append((sender, msg, enc))

    def _on_peer_status(self, peer: str, status: str) -> None:
        self.peer_status_events.append((peer, status))

    def _on_handshake_done(self, peer: str, fp: str) -> None:
        self.completed_handshakes.append((peer, fp))

    async def start(self) -> None:
        await self.coordinator.start()

    async def stop(self) -> None:
        await self.coordinator.stop()


async def link_nodes(node_a: E2ENode, node_b: E2ENode) -> None:
    """Wire bidirectional GATT communication between node_a and node_b and establish connection."""
    # A connects to B
    client_a_to_b = MockBleakClient(address=node_b.address)
    node_b.server_backend.attach_client(client_a_to_b)
    node_a.clients[node_b.address] = client_a_to_b

    orig_write_ab = client_a_to_b.write_gatt_char

    async def write_a_to_b(char: Any, data: bytes, response: bool = False) -> None:
        await orig_write_ab(char, data, response)
        node_b.server_backend.emit_write(data, client_id=node_a.address)

    client_a_to_b.write_gatt_char = write_a_to_b  # type: ignore[assignment]

    # B connects to A
    client_b_to_a = MockBleakClient(address=node_a.address)
    node_a.server_backend.attach_client(client_b_to_a)
    node_b.clients[node_a.address] = client_b_to_a

    orig_write_ba = client_b_to_a.write_gatt_char

    async def write_b_to_a(char: Any, data: bytes, response: bool = False) -> None:
        await orig_write_ba(char, data, response)
        node_a.server_backend.emit_write(data, client_id=node_b.address)

    client_b_to_a.write_gatt_char = write_b_to_a  # type: ignore[assignment]

    # Establish peer connection in both manager tables
    await node_a.manager.connect_peer(node_b.address)
    await node_b.manager.connect_peer(node_a.address)


@pytest.fixture
def node_factory() -> Callable[..., E2ENode]:
    """Fixture providing an E2ENode creation factory."""
    created_nodes: list[E2ENode] = []

    def _create(nickname: str, address: str, **kwargs: Any) -> E2ENode:
        node = E2ENode(nickname=nickname, address=address, **kwargs)
        created_nodes.append(node)
        return node

    return _create
