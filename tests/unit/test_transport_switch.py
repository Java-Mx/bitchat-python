"""Unit tests for transport abstraction switching, fresh ephemeral identity
generation, and peer state teardown.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.crypto.identity import LocalIdentity
from bitchat.mesh.router import MeshRouter
from bitchat.network.models import LANDiscoveredPeer
from bitchat.network.transport import LANTransport
from bitchat.storage.config import AppConfig, FileConfigStorage
from bitchat.transport.base import TransportState


@pytest.fixture
def test_identity() -> LocalIdentity:
    return LocalIdentity.generate()


@pytest.fixture
def mock_storage(test_identity: LocalIdentity, tmp_path: Path) -> FileConfigStorage:
    storage = FileConfigStorage(
        config_path=tmp_path / "config.json",
        identity_path=tmp_path / "identity.json",
    )
    storage.save_config(AppConfig(nickname="AliceNode", transport="bluetooth"))
    storage.save_identity(test_identity)
    return storage


@pytest.mark.asyncio
async def test_transport_switching_lifecycle(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    original_peer_id = test_identity.peer_id_hex

    mesh_router = MeshRouter(test_identity.peer_id)
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=BLEManager(sender_id=test_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=mesh_router,
        nickname="AliceNode",
        storage=mock_storage,
    )
    start_counts = {"bluetooth": 0, "lan": 0}

    async def mock_bt_start() -> None:
        start_counts["bluetooth"] += 1
        bt: Any = coordinator._transports["bluetooth"]
        bt._is_running = True
        bt._state = TransportState.READY

    async def mock_bt_stop() -> None:
        bt: Any = coordinator._transports["bluetooth"]
        bt._is_running = False
        bt._state = TransportState.OFFLINE

    async def mock_lan_start() -> None:
        start_counts["lan"] += 1
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
        patch.object(coordinator, "_transport_is_operational", return_value=True),
    ):
        await coordinator.start()
        assert coordinator.active_transport_name == "bluetooth"
        assert coordinator.local_identity.peer_id_hex == original_peer_id

        # Setup dummy session state
        coordinator.peer_addresses["dummy_peer"] = "AA:BB:CC:DD:EE:FF"
        coordinator.address_to_peer_id["AA:BB:CC:DD:EE:FF"] = "dummy_peer"
        coordinator.peer_nicknames["dummy_peer"] = "Bob"
        session = coordinator.get_or_create_session("dummy_peer")
        session.start_handshake()
        coordinator._schedule_handshake_timeout("dummy_peer", session)
        lan_transport = coordinator._transports["lan"]
        assert isinstance(lan_transport, LANTransport)
        lan_transport.discovery._discovered_peers["192.168.1.20:41235"] = (
            LANDiscoveredPeer(
                address="192.168.1.20:41235",
                ip="192.168.1.20",
                port=41235,
                peer_id="aabbccddeeff0011",
                nickname="Stale",
            )
        )

        assert len(coordinator.peer_addresses) == 1
        assert len(coordinator.peer_nicknames) == 1

        # 1. Switch to LAN
        success, msg = await coordinator.switch_transport("lan")
        assert success is True
        assert "Switched transport" in msg
        assert coordinator.active_transport_name == "lan"
        assert coordinator.active_transport.is_running
        metrics = coordinator.get_detailed_status()["transport_switch_metrics"]
        assert metrics["result"] == "success"
        assert metrics["cleanup_seconds"] >= 0
        assert metrics["initialization_seconds"] >= 0
        assert metrics["total_seconds"] >= metrics["initialization_seconds"]
        coordinator.record_transport_indicator_update()
        assert (
            coordinator.last_transport_switch_metrics["indicator_update_seconds"]
            is not None
        )

        # Verify persistent device identity was preserved across interface switch
        assert coordinator.local_identity.peer_id_hex == original_peer_id
        assert lan_transport.local_peer_id == original_peer_id
        assert lan_transport.discovered_peers == {}

        # The BLE manager preserves the persistent identity's ID
        bt_transport: Any = coordinator._transports["bluetooth"]
        assert bt_transport.ble_manager.sender_id == coordinator.local_identity.peer_id
        assert bt_transport.ble_manager.sender_id.hex() == original_peer_id

        # Verify peer tables and sessions were cleared
        assert len(coordinator.peer_addresses) == 0
        assert len(coordinator.address_to_peer_id) == 0
        assert len(coordinator.peer_nicknames) == 0
        assert len(coordinator._sessions) == 0
        assert not coordinator._handshake_timeout_tasks

        # Verify permanent storage was NOT overwritten
        stored_id = mock_storage.load_identity()
        assert stored_id is not None
        assert stored_id.peer_id_hex == original_peer_id

        # 2. Switch to LAN again when already active
        success_dup, msg_dup = await coordinator.switch_transport("lan")
        assert success_dup is True
        assert "Already active" in msg_dup
        assert start_counts["lan"] == 1
        assert coordinator.last_transport_switch_metrics["initialization_seconds"] == 0
        assert coordinator.local_identity.peer_id_hex == original_peer_id

        # 3. Switch back to Bluetooth
        success_bt, msg_bt = await coordinator.switch_transport("bluetooth")
        assert success_bt is True
        assert "Switched transport" in msg_bt
        assert coordinator.active_transport_name == "bluetooth"

        # Verify device identity remains stable across the switch
        assert coordinator.local_identity.peer_id_hex == original_peer_id
        assert lan_transport.local_peer_id == original_peer_id
        assert lan_transport.discovered_peers == {}
        assert bt_transport.ble_manager.sender_id == coordinator.local_identity.peer_id

        # 4. Attempt switching to an invalid transport
        bad_success, bad_msg = await coordinator.switch_transport("carrier_pigeon")
        assert bad_success is False
        assert "Unknown transport" in bad_msg

        await coordinator.stop()


@pytest.mark.asyncio
async def test_cancelled_transport_start_releases_candidate_and_restores_previous(
    test_identity: LocalIdentity,
) -> None:
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=BLEManager(sender_id=test_identity.peer_id),
        ble_server=BLEServer(),
        nickname="AliceNode",
    )
    lan_starting = asyncio.Event()

    async def start_bluetooth(transport: Any) -> None:
        transport._is_running = True
        transport._state = TransportState.READY

    async def stop_bluetooth(transport: Any) -> None:
        transport._is_running = False
        transport._state = TransportState.OFFLINE

    async def start_lan(transport: Any) -> None:
        transport._is_running = True
        transport._state = TransportState.CHECKING
        lan_starting.set()
        await asyncio.Event().wait()

    async def stop_lan(transport: Any) -> None:
        transport._is_running = False
        transport._state = TransportState.OFFLINE

    with (
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.start",
            start_bluetooth,
        ),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.stop",
            stop_bluetooth,
        ),
        patch("bitchat.network.transport.LANTransport.start", start_lan),
        patch("bitchat.network.transport.LANTransport.stop", stop_lan),
        patch.object(coordinator, "send_announce", new=AsyncMock()),
        patch.object(coordinator, "_start_prune_task"),
        patch.object(coordinator, "_transport_is_operational", return_value=True),
    ):
        await coordinator.start()
        switching = asyncio.create_task(coordinator.switch_transport("lan"))
        await asyncio.wait_for(lan_starting.wait(), timeout=1)
        switching.cancel()
        with pytest.raises(asyncio.CancelledError):
            await switching

        assert coordinator.active_transport_name == "bluetooth"
        assert coordinator.active_transport.is_running
        assert not coordinator._transports["lan"].is_running
        assert coordinator.last_transport_switch_metrics["result"] == "cancelled"
        await coordinator.stop()


@pytest.mark.asyncio
async def test_failed_bluetooth_switch_restores_lan_transport(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=BLEManager(sender_id=test_identity.peer_id),
        ble_server=BLEServer(),
        nickname="AliceNode",
        storage=mock_storage,
    )
    fail_bluetooth = False

    async def mock_bluetooth_start(transport: Any) -> None:
        if fail_bluetooth:
            transport._is_running = False
            transport._state = TransportState.ERROR
            raise RuntimeError("BLE peripheral initialization failed")
        transport._is_running = True
        transport._state = TransportState.READY

    async def mock_bluetooth_stop(transport: Any) -> None:
        transport._is_running = False
        transport._state = TransportState.OFFLINE

    async def mock_lan_start(transport: Any) -> None:
        transport._is_running = True
        transport._state = TransportState.READY

    async def mock_lan_stop(transport: Any) -> None:
        transport._is_running = False
        transport._state = TransportState.OFFLINE

    with (
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.start",
            mock_bluetooth_start,
        ),
        patch(
            "bitchat.transport.bluetooth.BluetoothTransport.stop",
            mock_bluetooth_stop,
        ),
        patch("bitchat.network.transport.LANTransport.start", mock_lan_start),
        patch("bitchat.network.transport.LANTransport.stop", mock_lan_stop),
    ):
        await coordinator.start()
        assert (await coordinator.switch_transport("lan"))[0] is True
        fail_bluetooth = True

        success, message = await coordinator.switch_transport("bluetooth")

        assert success is False
        assert "BLE peripheral initialization failed" in message
        assert "lan transport restored" in message.lower()
        assert coordinator.active_transport_name == "lan"
        assert coordinator.active_transport.is_running is True
        assert coordinator.is_running is True
        assert coordinator.lan_error_message is None
        assert coordinator.ble_error_message == "BLE peripheral initialization failed"
        await coordinator.stop()


@pytest.mark.asyncio
async def test_switch_transport_stops_ble_and_lan_services_and_clears_peers(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend

    from bitchat.network.adapter import NetworkInfo

    server_backend = MockBLEServerBackend()
    ble_manager = BLEManager(
        sender_id=test_identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    ble_server = BLEServer(backend=server_backend)
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=ble_manager,
        ble_server=ble_server,
        mesh_router=MeshRouter(test_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="TestLAN",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        await coordinator.start()
        bt_transport: Any = coordinator._transports["bluetooth"]
        lan_transport: Any = coordinator._transports["lan"]
        assert bt_transport.is_scanning is True
        assert bt_transport.ble_server.is_advertising is True

        # Switch BLE -> LAN: BLE scanning and advertising must stop
        ok_lan, _ = await coordinator.switch_transport("lan")
        assert ok_lan is True
        assert bt_transport.is_scanning is False
        assert bt_transport.ble_server.is_advertising is False
        assert lan_transport.discovery.is_running is True
        assert lan_transport.server.is_listening is True

        # Populate LAN discovered peer and switch LAN -> BLE
        lan_transport.discovery._discovered_peers["192.168.1.99:41235"] = (
            LANDiscoveredPeer(
                address="192.168.1.99:41235",
                ip="192.168.1.99",
                port=41235,
                peer_id="fedcba9876543210",
                nickname="Bob",
            )
        )
        coordinator._handle_peer_discovered(
            lan_transport.discovery._discovered_peers["192.168.1.99:41235"]
        )
        assert "fedcba9876543210" in coordinator.peer_addresses

        ok_bt, _ = await coordinator.switch_transport("bluetooth")
        assert ok_bt is True
        assert lan_transport.discovery.is_running is False
        assert lan_transport.server.is_listening is False
        assert lan_transport.discovered_peers == {}
        assert coordinator.peer_addresses == {}
        assert bt_transport.is_scanning is True
        assert bt_transport.ble_server.is_advertising is True

        await coordinator.stop()


def test_coordinator_suppresses_duplicate_discovered_status_for_same_peer_id(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=BLEManager(sender_id=test_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(test_identity.peer_id),
        nickname="Local",
        storage=mock_storage,
    )
    events: list[tuple[str, str]] = []
    coordinator.on_peer_status_changed = lambda addr, status: events.append(
        (addr, status)
    )

    peer_port_1 = LANDiscoveredPeer(
        address="192.168.56.1:52616",
        ip="192.168.56.1",
        port=52616,
        peer_id="fedcba9876543210",
        nickname="Alice",
    )
    peer_port_2 = LANDiscoveredPeer(
        address="192.168.56.1:55250",
        ip="192.168.56.1",
        port=55250,
        peer_id="fedcba9876543210",
        nickname="Alice",
    )

    coordinator._handle_peer_discovered(peer_port_1)
    coordinator._handle_peer_discovered(peer_port_1)
    coordinator._handle_peer_discovered(peer_port_2)

    discovered_msgs = [s for _, s in events if s.startswith("Discovered:")]
    assert discovered_msgs == ["Discovered: Alice"]
    assert coordinator.peer_addresses["fedcba9876543210"] == "192.168.56.1:55250"
    assert "192.168.56.1:52616" not in coordinator.address_to_peer_id
    assert coordinator.address_to_peer_id["192.168.56.1:55250"] == "fedcba9876543210"


@pytest.mark.asyncio
async def test_rapid_concurrent_transport_switches_are_serialized_and_preserve_state(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    import asyncio

    from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend

    from bitchat.network.adapter import NetworkInfo
    from bitchat.transport.base import TransportState

    server_backend = MockBLEServerBackend()
    ble_manager = BLEManager(
        sender_id=test_identity.peer_id,
        scanner_factory=lambda **kw: MockBleakScanner(
            kw["detection_callback"], kw["service_uuids"]
        ),
    )
    ble_server = BLEServer(backend=server_backend)
    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=ble_manager,
        ble_server=ble_server,
        mesh_router=MeshRouter(test_identity.peer_id),
        nickname="AliceNode",
        storage=mock_storage,
    )

    wifi_info = NetworkInfo(
        status="Connected",
        interface="Wi-Fi",
        ssid="TestLAN",
        local_ip="192.168.1.50",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=wifi_info):
        await coordinator.start()
        results = await asyncio.gather(
            coordinator.switch_transport("lan"),
            coordinator.switch_transport("bluetooth"),
            coordinator.switch_transport("lan"),
        )
        assert all(ok for ok, _ in results)
        assert coordinator.active_transport_name == "lan"
        assert coordinator.active_transport.is_running is True
        await coordinator.stop()

    # Failed switch to LAN when disconnected preserves UNAVAILABLE state & error
    disc_info = NetworkInfo(
        status="Disconnected",
        interface="Unavailable",
        ssid="unavailable",
        local_ip="",
    )
    with patch("bitchat.network.adapter.detect_network_info", return_value=disc_info):
        ok, _ = await coordinator.switch_transport("lan")
        assert ok is False
        assert coordinator.active_transport.state == TransportState.UNAVAILABLE
        assert (
            coordinator.active_transport.get_telemetry()["error_message"]
            == "Local network is disconnected."
        )


def test_ble_scanner_cleared_and_mac_rotation_deduplicated_on_identity_and_scan(
    test_identity: LocalIdentity,
) -> None:
    import uuid

    from bitchat.ble.scanner import BLEScanner
    from bitchat.protocol.constants import BITCHAT_SERVICE_UUID

    scanner = BLEScanner()
    srv_bytes = uuid.UUID(BITCHAT_SERVICE_UUID).bytes

    class _Dev:
        def __init__(self, address: str) -> None:
            self.address = address
            self.name = "BitChat_Alice"

    class _Adv:
        def __init__(self) -> None:
            self.service_uuids = [BITCHAT_SERVICE_UUID]
            self.manufacturer_data = {
                0xFFFF: b"BC" + srv_bytes + b"fedcba9876543210|Alice"
            }
            self.local_name = "BitChat_Alice"
            self.rssi = -55

    dev1: Any = _Dev("AA:BB:CC:DD:EE:01")
    dev2: Any = _Dev("AA:BB:CC:DD:EE:02")
    adv: Any = _Adv()
    scanner._detection_callback(dev1, adv)
    scanner._detection_callback(dev2, adv)

    assert list(scanner.discovered_peers.keys()) == ["AA:BB:CC:DD:EE:02"]
    assert scanner.discovered_peers["AA:BB:CC:DD:EE:02"].peer_id == "fedcba9876543210"
    assert scanner.discovered_peers["AA:BB:CC:DD:EE:02"].nickname == "Alice"

    ble_manager = BLEManager(sender_id=test_identity.peer_id)
    ble_manager.scanner._discovered_peers.update(scanner.discovered_peers)
    new_identity = LocalIdentity.generate()
    ble_manager.update_sender_id(new_identity.peer_id)
    assert ble_manager.scanner.discovered_peers == {}


@pytest.mark.asyncio
async def test_inbound_lan_unicast_and_disconnect_preserves_discovered_endpoint(
    test_identity: LocalIdentity, mock_storage: FileConfigStorage
) -> None:
    from bitchat.protocol.constants import MessageType
    from bitchat.protocol.packet import BitchatPacket

    coordinator = SessionCoordinator(
        local_identity=test_identity,
        ble_manager=BLEManager(sender_id=test_identity.peer_id),
        ble_server=BLEServer(),
        mesh_router=MeshRouter(test_identity.peer_id),
        nickname="Local",
        storage=mock_storage,
        initial_transport="lan",
    )
    lan_transport: Any = coordinator.active_transport
    disc_peer = LANDiscoveredPeer(
        address="192.168.1.99:41235",
        ip="192.168.1.99",
        port=41235,
        peer_id="fedcba9876543210",
        nickname="Bob",
    )
    lan_transport.discovery._discovered_peers["192.168.1.99:41235"] = disc_peer
    coordinator._handle_peer_discovered(disc_peer)

    sent_to: list[tuple[str, BitchatPacket]] = []

    class _InboundConn:
        is_ready = True
        is_inbound = True

        async def send_packet(self, pkt: BitchatPacket) -> None:
            sent_to.append(("192.168.1.99:61234", pkt))

    lan_transport._connections["192.168.1.99:61234"] = _InboundConn()
    coordinator.address_to_peer_id["192.168.1.99:61234"] = "fedcba9876543210"

    pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=test_identity.peer_id,
        payload=b"hello inbound",
    )
    await coordinator._send_packet("fedcba9876543210", pkt)
    assert len(sent_to) == 1
    assert sent_to[0][0] == "192.168.1.99:61234"

    # Disconnect inbound socket while peer is still in discovered_peers
    lan_transport._connections.pop("192.168.1.99:61234", None)
    coordinator._handle_peer_disconnected("192.168.1.99:61234")
    assert coordinator.peer_addresses.get("fedcba9876543210") == "192.168.1.99:41235"
    assert (
        coordinator.address_to_peer_id.get("192.168.1.99:41235") == "fedcba9876543210"
    )
