"""End-to-End two-node integration test for BitChat.

Validates complete vertical slice:
1. Two distinct nodes initialized with LocalIdentity & persistent storage.
2. Link establishment over BLE GATT (client/server).
3. Announce presence exchange and nickname resolution.
4. Unencrypted broadcast chat exchange.
5. End-to-end Noise XX handshake establishment.
6. Bidirectional encrypted direct messaging (DM).
7. Large fragmented message (>1000B) paced transmission and reassembly.
8. Disconnect and reconnection lifecycle.
9. Clean teardown without resource leaks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner, MockBLEServerBackend

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.storage.config import InMemoryStorage


def _setup_two_node_network() -> tuple[
    SessionCoordinator,
    SessionCoordinator,
    list[tuple[str, str, bool]],
    list[tuple[str, str, bool]],
]:
    id_a = LocalIdentity.generate()
    id_b = LocalIdentity.generate()

    storage_a = InMemoryStorage()
    storage_b = InMemoryStorage()
    storage_a.save_identity(id_a)
    storage_b.save_identity(id_b)

    backend_a = MockBLEServerBackend()
    server_a = BLEServer(backend=backend_a)

    backend_b = MockBLEServerBackend()
    server_b = BLEServer(backend=backend_b)

    client_a = MockBleakClient(address="BB:01")
    backend_b.attach_client(client_a)

    orig_write = client_a.write_gatt_char

    async def hooked_write(char: Any, data: bytes, response: bool = False) -> None:
        await orig_write(char, data, response)
        backend_b.emit_write(data, client_id="client_a")

    client_a.write_gatt_char = hooked_write  # type: ignore[assignment]

    def mock_scanner(**kw: Any) -> MockBleakScanner:
        return MockBleakScanner(kw["detection_callback"], kw["service_uuids"])

    manager_a = BLEManager(
        sender_id=id_a.peer_id,
        client_factory=lambda *args, **kwargs: client_a,
        scanner_factory=mock_scanner,
    )
    manager_b = BLEManager(
        sender_id=id_b.peer_id,
        scanner_factory=mock_scanner,
    )

    received_a: list[tuple[str, str, bool]] = []
    received_b: list[tuple[str, str, bool]] = []

    coord_a = SessionCoordinator(
        local_identity=id_a,
        ble_manager=manager_a,
        ble_server=server_a,
        storage=storage_a,
        nickname="Node-A",
        on_message_received=lambda s, m, enc: received_a.append((s, m, enc)),
        inter_fragment_delay=0.001,
    )

    coord_b = SessionCoordinator(
        local_identity=id_b,
        ble_manager=manager_b,
        ble_server=server_b,
        storage=storage_b,
        nickname="Node-B",
        on_message_received=lambda s, m, enc: received_b.append((s, m, enc)),
        inter_fragment_delay=0.001,
    )

    return coord_a, coord_b, received_a, received_b


@pytest.mark.asyncio
async def test_end_to_end_two_node_communication() -> None:
    coord_a, coord_b, msgs_a, msgs_b = _setup_two_node_network()

    # Step 1: Start both nodes
    await coord_b.start()
    await coord_a.start()

    # Step 2: Node A connects to Node B
    await coord_a.ble_manager.connect_peer("BB:01")
    await asyncio.sleep(0.05)

    assert "BB:01" in coord_a.ble_manager.connected_peers

    # Step 3: Presence and announce exchange
    await coord_a.send_announce("Node-A")
    await asyncio.sleep(0.05)
    assert coord_b.peer_nicknames.get(coord_a.local_identity.peer_id_hex) == "Node-A"

    # Step 4: Unencrypted broadcast message from A to B
    await coord_a.send_broadcast_message("Public broadcast from Node A")
    await asyncio.sleep(0.05)
    assert len(msgs_b) == 1
    assert msgs_b[0][1] == "Public broadcast from Node A"
    assert msgs_b[0][2] is False  # unencrypted

    # Step 5: Direct encrypted message from A to B (triggers Noise XX handshake)
    secret_text_1 = "Top secret message from Node A"
    await coord_a.send_direct_message(coord_b.local_identity.peer_id_hex, secret_text_1)

    for _ in range(50):
        if len(msgs_b) >= 2:
            break
        await asyncio.sleep(0.02)

    assert len(msgs_b) == 2
    assert msgs_b[1][1] == secret_text_1
    assert msgs_b[1][2] is True  # encrypted!

    # Verify both sessions are established
    session_a = coord_a.get_or_create_session(coord_b.local_identity.peer_id_hex)
    session_b = coord_b.get_or_create_session(coord_a.local_identity.peer_id_hex)
    assert session_a.is_established
    assert session_b.is_established
    assert session_a.remote_fingerprint == coord_b.local_identity.fingerprint
    assert session_b.remote_fingerprint == coord_a.local_identity.fingerprint

    # Step 6: Reply from B to A (using established Noise XX session)
    secret_text_2 = "Encrypted reply from Node B"
    await coord_b.send_direct_message(coord_a.local_identity.peer_id_hex, secret_text_2)

    for _ in range(50):
        if len(msgs_a) >= 1:
            break
        await asyncio.sleep(0.02)

    assert len(msgs_a) == 1
    assert msgs_a[0][1] == secret_text_2
    assert msgs_a[0][2] is True  # encrypted!

    # Step 7: Large fragmented message (>1000 bytes) from A to B
    large_text = "LARGE-INTEGRATION-TEST-" + ("X" * 1500)
    await coord_a.send_direct_message(coord_b.local_identity.peer_id_hex, large_text)

    for _ in range(50):
        if len(msgs_b) >= 3:
            break
        await asyncio.sleep(0.02)

    assert len(msgs_b) == 3
    assert msgs_b[2][1] == large_text
    assert msgs_b[2][2] is True

    # Step 8: Disconnect and Reconnection
    await coord_a.ble_manager.disconnect_peer("BB:01")
    assert "BB:01" not in coord_a.ble_manager.connected_peers

    # Reconnect
    await coord_a.ble_manager.connect_peer("BB:01")
    assert "BB:01" in coord_a.ble_manager.connected_peers

    # Send message after reconnection
    reconnect_msg = "Hello again after reconnect"
    await coord_a.send_broadcast_message(reconnect_msg)
    await asyncio.sleep(0.05)

    assert any(m[1] == reconnect_msg for m in msgs_b)

    # Step 9: Clean teardown
    await coord_a.stop()
    await coord_b.stop()
    assert not coord_a.is_running
    assert not coord_b.is_running
