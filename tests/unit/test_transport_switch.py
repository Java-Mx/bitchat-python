"""Unit tests for transport abstraction switching, fresh ephemeral identity
generation, and peer state teardown.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.storage.config import AppConfig, InMemoryStorage
from bitchat.transport.base import TransportState


@pytest.fixture
def test_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def mock_storage(test_identity: LocalIdentity) -> InMemoryStorage:
    storage = InMemoryStorage(
        initial_config=AppConfig(nickname="AliceNode", transport="bluetooth"),
        initial_identity=test_identity,
    )
    return storage


@pytest.mark.asyncio
async def test_transport_switching_lifecycle(
    test_identity: LocalIdentity, mock_storage: InMemoryStorage
) -> None:
    original_peer_id = test_identity.peer_id_hex

    mesh_router = MeshRouter(test_identity.peer_id)
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        mesh_router=mesh_router,
        nickname="AliceNode",
    )

    async def mock_bt_start() -> None:
        bt: Any = coordinator._transports["bluetooth"]
        bt._is_running = True
        bt._state = TransportState.READY

    async def mock_bt_stop() -> None:
        bt: Any = coordinator._transports["bluetooth"]
        bt._is_running = False
        bt._state = TransportState.OFFLINE

    async def mock_lan_start() -> None:
        lan: Any = coordinator._transports["lan"]
        lan._is_running = True
        lan._state = TransportState.READY

    async def mock_lan_stop() -> None:
        lan: Any = coordinator._transports["lan"]
        lan._is_running = False
        lan._state = TransportState.OFFLINE

    with (
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.start",
            side_effect=mock_bt_start,
        ),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.stop",
            side_effect=mock_bt_stop,
        ),
        patch(
            "bitchat.network.transport.LANTransport.start", side_effect=mock_lan_start
        ),
        patch("bitchat.network.transport.LANTransport.stop", side_effect=mock_lan_stop),
    ):
        await coordinator.start()
        assert coordinator.active_transport_name == "bluetooth"
        assert coordinator.local_identity.peer_id_hex == original_peer_id

        # Setup dummy session state
        coordinator.peer_addresses["dummy_peer"] = "AA:BB:CC:DD:EE:FF"
        coordinator.address_to_peer_id["AA:BB:CC:DD:EE:FF"] = "dummy_peer"
        coordinator.peer_nicknames["dummy_peer"] = "Bob"
        coordinator.get_or_create_session("dummy_peer")

        assert len(coordinator.peer_addresses) == 1
        assert len(coordinator.peer_nicknames) == 1

        # 1. Switch to LAN
        success, msg = await coordinator.switch_transport("lan")
        assert success is True
        assert "Switched transport" in msg
        assert coordinator.active_transport_name == "lan"
        assert coordinator.active_transport.is_running

        # Verify fresh transport-scoped identity was generated
        new_lan_peer_id = coordinator.local_identity.peer_id_hex
        assert new_lan_peer_id != original_peer_id

        # Verify peer tables and sessions were cleared
        assert len(coordinator.peer_addresses) == 0
        assert len(coordinator.address_to_peer_id) == 0
        assert len(coordinator.peer_nicknames) == 0
        assert len(coordinator._sessions) == 0

        # Verify permanent storage was NOT overwritten
        stored_id = mock_storage.load_identity()
        assert stored_id is not None
        assert stored_id.peer_id_hex == original_peer_id

        # 2. Switch to LAN again when already active
        success_dup, msg_dup = await coordinator.switch_transport("lan")
        assert success_dup is True
        assert "Already active" in msg_dup
        assert coordinator.local_identity.peer_id_hex == new_lan_peer_id

        # 3. Switch back to Bluetooth
        success_bt, msg_bt = await coordinator.switch_transport("bluetooth")
        assert success_bt is True
        assert "Switched transport" in msg_bt
        assert coordinator.active_transport_name == "bluetooth"

        # Verify another fresh transport-scoped identity was generated
        new_bt_peer_id = coordinator.local_identity.peer_id_hex
        assert new_bt_peer_id != new_lan_peer_id
        assert new_bt_peer_id != original_peer_id

        # 4. Attempt switching to an invalid transport
        bad_success, bad_msg = await coordinator.switch_transport("carrier_pigeon")
        assert bad_success is False
        assert "Unknown transport" in bad_msg

        await coordinator.stop()
