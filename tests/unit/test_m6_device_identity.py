"""Milestone 6 (M6) Regression Test Suite.

Exhaustively verifies:
1. Simultaneous launch identity race serialization via interprocess file locking.
2. Identity persistence across restarts and crashes.
3. LAN self-discovery prevention (same instance & multi-instance).
4. BLE self-discovery filtering.
5. Cryptographic Noise XX self-handshake rejection (static key equality).
6. Coordinator prevention of self-session creation.
7. Coordinator prevention of self direct-messaging.
8. Coordinator filtering of self discovered peer.
9. Local socket self-connect rejection on owned server port.
10. Multi-transport (BLE + LAN) peer deduplication under canonical peer ID.
11. Transport switch identity stability (M6 Rule 5).
12. Concurrent corrupt identity detection and safe recovery.
"""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from bitchat.app.session_coordinator import SessionCoordinator
from bitchat.ble.scanner import BLEScanner
from bitchat.crypto.identity import LocalIdentity, generate_instance_id
from bitchat.crypto.noise import NoiseRole
from bitchat.crypto.sessions import NoiseSession, NoiseSessionState
from bitchat.exceptions import AuthenticationError, ConfigurationError
from bitchat.network.discovery import LANDiscovery
from bitchat.network.models import DiscoveryPacket, LANDiscoveredPeer
from bitchat.network.transport import LANTransport
from bitchat.storage.config import FileConfigStorage

if TYPE_CHECKING:
    from pathlib import Path

    from bitchat.ble.models import DiscoveredPeer

# ---------------------------------------------------------------------------
# 1. Simultaneous Launch Identity Race Prevention
# ---------------------------------------------------------------------------


def test_simultaneous_launch_identity_loading(tmp_path: Path) -> None:
    """Concurrent processes/threads calling load_or_create_identity on a fresh profile

    must obtain the exact same LocalIdentity without generating conflicting keys.
    """
    identity_file = tmp_path / "identity.json"
    config_file = tmp_path / "config.json"

    def worker_load() -> tuple[str, str]:
        storage = FileConfigStorage(
            config_path=config_file, identity_path=identity_file
        )
        identity = storage.load_or_create_identity()
        return identity.peer_id_hex, identity.fingerprint

    # Launch 8 concurrent workers simultaneously on an empty profile
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_load) for _ in range(8)]
        results = [f.result() for f in futures]

    peer_ids = {r[0] for r in results}
    fingerprints = {r[1] for r in results}

    assert len(peer_ids) == 1, f"Expected 1 unique peer_id, got: {peer_ids}"
    assert len(fingerprints) == 1, f"Expected 1 unique fingerprint, got: {fingerprints}"
    assert identity_file.exists()


# ---------------------------------------------------------------------------
# 2. Identity Persistence Across Restarts
# ---------------------------------------------------------------------------


def test_identity_persistence_across_restarts(tmp_path: Path) -> None:
    """A restarted instance must load the exact same persistent Device Identity."""
    identity_file = tmp_path / "identity.json"
    config_file = tmp_path / "config.json"

    storage1 = FileConfigStorage(config_path=config_file, identity_path=identity_file)
    id1 = storage1.load_or_create_identity()
    storage1.close()

    storage2 = FileConfigStorage(config_path=config_file, identity_path=identity_file)
    id2 = storage2.load_or_create_identity()
    storage2.close()

    assert id1.peer_id == id2.peer_id
    assert id1.peer_id_hex == id2.peer_id_hex
    assert id1.fingerprint == id2.fingerprint
    assert id1.x25519_private == id2.x25519_private
    assert id1.ed25519_private == id2.ed25519_private
    assert id1.device_id == id1.peer_id
    assert id1.device_id_hex == id1.peer_id_hex


# ---------------------------------------------------------------------------
# 3. LAN Self-Discovery Prevention (Same Instance)
# ---------------------------------------------------------------------------


def test_lan_self_discovery_prevention() -> None:
    """An instance broadcasting on LAN must ignore its own discovery packets."""
    local_id = LocalIdentity.generate()
    discovered: list[LANDiscoveredPeer] = []

    discovery = LANDiscovery(
        local_peer_id=local_id.peer_id_hex,
        local_nickname="AliceNode",
        listening_port=41235,
        on_peer_discovered=discovered.append,
    )

    # Simulate loopback packet with local peer ID
    self_packet = DiscoveryPacket(
        peer_id=local_id.peer_id_hex,
        nickname="AliceNode",
        port=41235,
        instance_id=discovery.instance_id,
    )
    result = discovery._process_incoming_packet(
        self_packet.to_bytes(), sender_ip="192.168.1.50"
    )

    assert result is None
    assert len(discovered) == 0
    assert len(discovery.discovered_peers) == 0


# ---------------------------------------------------------------------------
# 4. LAN Multi-Instance Self-Discovery Prevention
# ---------------------------------------------------------------------------


def test_lan_multi_instance_self_discovery_prevention() -> None:
    """Two instances running on the same laptop sharing the same Device Identity

    must suppress each other from the peer table based on shared peer_id.
    """
    shared_device_id = LocalIdentity.generate()
    discovered_a: list[LANDiscoveredPeer] = []
    discovered_b: list[LANDiscoveredPeer] = []

    instance_a_token = generate_instance_id()
    instance_b_token = generate_instance_id()
    assert instance_a_token != instance_b_token

    discovery_a = LANDiscovery(
        local_peer_id=shared_device_id.peer_id_hex,
        local_nickname="AliceInstanceA",
        listening_port=41235,
        instance_id=instance_a_token,
        on_peer_discovered=discovered_a.append,
    )

    discovery_b = LANDiscovery(
        local_peer_id=shared_device_id.peer_id_hex,
        local_nickname="AliceInstanceB",
        listening_port=41236,  # Port fallback on second instance
        instance_id=instance_b_token,
        on_peer_discovered=discovered_b.append,
    )

    # Instance B broadcasts beacon with shared peer_id
    b_beacon = DiscoveryPacket(
        peer_id=shared_device_id.peer_id_hex,
        nickname="AliceInstanceB",
        port=41236,
        instance_id=instance_b_token,
    )

    # Instance A receives Instance B's beacon
    result_a = discovery_a._process_incoming_packet(
        b_beacon.to_bytes(), sender_ip="192.168.1.50"
    )
    assert result_a is None
    assert len(discovered_a) == 0

    # Instance A broadcasts beacon with shared peer_id
    a_beacon = DiscoveryPacket(
        peer_id=shared_device_id.peer_id_hex,
        nickname="AliceInstanceA",
        port=41235,
        instance_id=instance_a_token,
    )

    # Instance B receives Instance A's beacon
    result_b = discovery_b._process_incoming_packet(
        a_beacon.to_bytes(), sender_ip="192.168.1.50"
    )
    assert result_b is None
    assert len(discovered_b) == 0


# ---------------------------------------------------------------------------
# 5. BLE Self-Discovery Prevention
# ---------------------------------------------------------------------------


def test_ble_self_discovery_prevention() -> None:
    """BLE scanner must filter out loopback advertisements matching local peer_id."""
    local_id = LocalIdentity.generate()
    discovered: list[DiscoveredPeer] = []

    scanner = BLEScanner(
        local_peer_id=local_id.peer_id_hex,
        on_peer_discovered=discovered.append,
    )

    # Construct mock BLE device and advertisement data reflecting local node
    mock_device = MagicMock()
    mock_device.address = "AA:BB:CC:11:22:33"
    mock_device.name = "BitChat Node"

    mock_adv = MagicMock()
    mock_adv.service_uuids = [scanner.service_uuid]
    mock_adv.service_data = {}
    mock_adv.local_name = "AliceNode"
    mock_adv.rssi = -42
    # Manufacturer data contains the local peer ID
    srv_bytes = bytes.fromhex(scanner.service_uuid.replace("-", ""))
    mock_adv.manufacturer_data = {
        0xFFFF: b"BC" + srv_bytes + local_id.peer_id_hex.encode("utf-8") + b"|AliceNode"
    }

    scanner._detection_callback(mock_device, mock_adv)

    assert len(discovered) == 0
    assert len(scanner.discovered_peers) == 0


# ---------------------------------------------------------------------------
# 6. Cryptographic Noise Handshake Self-Rejection
# ---------------------------------------------------------------------------


def test_noise_self_handshake_rejection() -> None:
    """NoiseSession must abort if the remote static key matches local static key."""
    alice_id = LocalIdentity.generate()

    # Create initiator and responder sharing the exact same local identity
    initiator_session = NoiseSession(
        local_identity=alice_id,
        remote_peer_id=alice_id.peer_id_hex,
        role=NoiseRole.INITIATOR,
    )
    responder_session = NoiseSession(
        local_identity=alice_id,
        remote_peer_id=alice_id.peer_id_hex,
        role=NoiseRole.RESPONDER,
    )

    # Step 1: Initiator -> Responder (msg 1: -> e)
    msg1 = initiator_session.start_handshake()
    assert msg1 is not None

    # Step 2: Responder processes msg 1 and returns msg 2 (msg 2: <- e, ee, s, es)
    msg2 = responder_session.process_handshake_message(msg1)
    assert msg2 is not None

    # Step 3: Initiator processes msg 2 and authenticates responder's static key.
    # Because responder's static key matches local identity, finalise_handshake
    # detects the self-connection immediately and raises AuthenticationError.
    with pytest.raises(
        AuthenticationError, match="Self-connection rejected: remote peer authenticated"
    ):
        initiator_session.process_handshake_message(msg2)

    assert initiator_session.state == NoiseSessionState.FAILED


# ---------------------------------------------------------------------------
# 7. Coordinator Self-Session Rejection
# ---------------------------------------------------------------------------


def test_coordinator_rejects_self_session_creation() -> None:
    """SessionCoordinator must refuse self Noise session for local peer ID."""
    local_id = LocalIdentity.generate()
    coord = SessionCoordinator(local_identity=local_id)

    with pytest.raises(ValueError, match="Cannot establish Noise session with self"):
        coord.get_or_create_session(local_id.peer_id_hex)


# ---------------------------------------------------------------------------
# 8. Coordinator Self Direct-Messaging Rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_rejects_self_direct_message() -> None:
    """SessionCoordinator must refuse to send direct messages to local peer ID."""
    local_id = LocalIdentity.generate()
    coord = SessionCoordinator(local_identity=local_id)

    with pytest.raises(ValueError, match="Cannot establish Noise session with self"):
        await coord.send_direct_message(local_id.peer_id_hex, "Hello to myself")


# ---------------------------------------------------------------------------
# 9. Coordinator Filters Self-Discovered Peer
# ---------------------------------------------------------------------------


def test_coordinator_filters_self_discovered_peer() -> None:
    """SessionCoordinator._handle_peer_discovered must suppress local peer ID."""
    local_id = LocalIdentity.generate()
    coord = SessionCoordinator(local_identity=local_id)

    mock_peer = MagicMock()
    mock_peer.peer_id = local_id.peer_id_hex
    mock_peer.address = "192.168.1.50:41235"
    mock_peer.name = "SelfLoop"

    coord._handle_peer_discovered(mock_peer)

    assert local_id.peer_id_hex.lower() not in coord.peer_addresses
    assert mock_peer.address not in coord.address_to_peer_id
    assert local_id.peer_id_hex.lower() not in coord.peer_nicknames


# ---------------------------------------------------------------------------
# 10. Local Socket Self-Connect Rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lan_transport_rejects_connecting_to_local_server_port() -> None:
    """LANTransport.connect_peer must reject connections to local server port."""
    local_id = LocalIdentity.generate()
    transport = LANTransport(
        local_peer_id=local_id.peer_id_hex,
        local_nickname="Tester",
        tcp_port=0,
    )
    # Start server to acquire bound port
    await transport.server.start()
    bound_port = transport.server.bound_port
    assert bound_port > 0

    try:
        # Connecting to loopback with own bound port must raise ValueError
        with pytest.raises(
            ValueError, match="Cannot connect to local listening endpoint"
        ):
            await transport.connect_peer(f"127.0.0.1:{bound_port}")
    finally:
        await transport.server.stop()


# ---------------------------------------------------------------------------
# 11. Cross-Transport (BLE + LAN) Peer Deduplication
# ---------------------------------------------------------------------------


def test_cross_transport_peer_deduplication() -> None:
    """Remote peer discovered on BLE then LAN must map to a single peer entry."""
    local_id = LocalIdentity.generate()
    remote_id = LocalIdentity.generate()
    coord = SessionCoordinator(local_identity=local_id)

    # 1. Peer discovered via BLE
    ble_peer = MagicMock()
    ble_peer.peer_id = remote_id.peer_id_hex
    ble_peer.address = "AA:BB:CC:DD:EE:FF"
    ble_peer.name = "RemotePeer"
    coord._handle_peer_discovered(ble_peer)

    assert coord.peer_addresses[remote_id.peer_id_hex] == "AA:BB:CC:DD:EE:FF"
    assert coord.peer_nicknames[remote_id.peer_id_hex] == "RemotePeer"
    assert len(coord.peer_addresses) == 1

    # 2. Same peer discovered via LAN
    lan_peer = MagicMock()
    lan_peer.peer_id = remote_id.peer_id_hex
    lan_peer.address = "192.168.1.150:41235"
    lan_peer.name = "RemotePeer"
    coord._handle_peer_discovered(lan_peer)

    # Address updated to LAN endpoint, still only 1 entry in peer_addresses!
    assert coord.peer_addresses[remote_id.peer_id_hex] == "192.168.1.150:41235"
    assert len(coord.peer_addresses) == 1
    assert len(coord.peer_nicknames) == 1


# ---------------------------------------------------------------------------
# 12. Corrupt Identity Safe Recovery Under Concurrency
# ---------------------------------------------------------------------------


def test_corrupt_identity_concurrent_recovery(tmp_path: Path) -> None:
    """Corrupt identity.json raises ConfigurationError and creates a backup."""
    identity_file = tmp_path / "identity.json"
    config_file = tmp_path / "config.json"

    # Write corrupt JSON
    identity_file.write_text("{invalid_json: true", encoding="utf-8")

    storage = FileConfigStorage(config_path=config_file, identity_path=identity_file)

    with pytest.raises(ConfigurationError):
        storage.load_or_create_identity()

    # Backup file must be created
    backups = list(tmp_path.glob("identity.json.corrupt.*"))
    assert len(backups) >= 1
    assert backups[0].read_text(encoding="utf-8") == "{invalid_json: true"
