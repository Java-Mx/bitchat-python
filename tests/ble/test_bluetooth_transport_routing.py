"""Regression tests for BLE GATT server inbound routing and fragment padding."""

from __future__ import annotations

import pytest
from tests.ble.mocks import MockBleakClient, MockBleakScanner, MockBLEServerBackend

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.connection import BLEConnection
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
from bitchat.ble.transport import BLETransport
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.transport.bluetooth import BluetoothTransport


class StaticAdapterBackend:
    def __init__(self, info: AdapterInfo) -> None:
        self.info = info

    async def check_adapter(self) -> AdapterInfo:
        return self.info


def make_test_transport() -> tuple[
    BluetoothTransport, MockBLEServerBackend, BLEManager
]:
    info = AdapterInfo(
        is_available=True,
        radio_state="on",
        is_central_supported=True,
        is_peripheral_supported=True,
        is_advertisement_offload_supported=True,
        device_id="test-adapter",
        name="Test BLE",
    )
    server_backend = MockBLEServerBackend()
    adapter_manager = BLEAdapterManager(
        custom_backend=StaticAdapterBackend(info),
    )
    manager = BLEManager(
        sender_id=b"\x01" * 8,
        scanner_factory=lambda **kwargs: MockBleakScanner(
            kwargs["detection_callback"], kwargs["service_uuids"]
        ),
        adapter_manager=adapter_manager,
    )
    server = BLEServer(backend=server_backend)
    transport = BluetoothTransport(manager, server)
    return transport, server_backend, manager


def make_packet(payload: bytes = b"test payload") -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=12345678,
        flags=FLAG_HAS_RECIPIENT,
        sender_id=b"\x11" * 8,
        recipient_id=b"\x22" * 8,
        payload=payload,
        signature=None,
    )


@pytest.mark.asyncio
async def test_server_data_inbound_routing_unfragmented() -> None:
    """Inbound GATT server writes are decoded and dispatched to on_packet_received."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    pkt = make_packet(b"hello from central")
    raw = encode_packet(pkt, add_padding=True)

    transport._handle_server_data(raw, "central_client_1")

    assert len(received) == 1
    dispatched_pkt, addr = received[0]
    assert dispatched_pkt.payload == b"hello from central"
    assert addr == "central_client_1"
    assert "central_client_1" in transport._server_clients


@pytest.mark.asyncio
async def test_server_data_inbound_routing_fragmented() -> None:
    """Multi-fragment incoming GATT writes are reassembled before delivery."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    large_payload = b"Z" * 800
    pkt = make_packet(large_payload)
    encoded = encode_packet(pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded, sender_id=pkt.sender_id, original_message_type=pkt.message_type
    )
    assert len(fragments) > 1

    # Send all but last fragment
    for frag in fragments[:-1]:
        frag_bytes = encode_packet(frag, add_padding=False)
        transport._handle_server_data(frag_bytes, "central_client_2")
        assert len(received) == 0

    # Send last fragment
    last_frag_bytes = encode_packet(fragments[-1], add_padding=False)
    transport._handle_server_data(last_frag_bytes, "central_client_2")

    assert len(received) == 1
    dispatched_pkt, addr = received[0]
    assert dispatched_pkt.payload == large_payload
    assert addr == "central_client_2"


@pytest.mark.asyncio
async def test_server_data_malformed_discarded_cleanly() -> None:
    """Malformed server data is cleanly discarded without crashing or emitting."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    transport._handle_server_data(b"not a valid packet wire", "client_bad")
    assert len(received) == 0


@pytest.mark.asyncio
async def test_send_to_peer_unicast_server_client() -> None:
    """Validate send_to_peer routes to ble_server for a connected server client."""
    transport, server_backend, _ = make_test_transport()
    await transport.start()
    assert transport.ble_server.is_advertising

    client = MockBleakClient(address="central_client_3")
    await client.connect()
    server_backend.attach_client(client)
    transport._handle_server_client_subscribed("central_client_3")

    notifications: list[bytes] = []
    client.subscribed_char = "mock_char"
    client.subscribed_callback = lambda _c, data: notifications.append(bytes(data))

    pkt = make_packet(b"unicast reply to central")
    await transport.send_to_peer("central_client_3", pkt)

    assert len(notifications) == 1
    assert b"unicast reply to central" in notifications[0]

    await transport.stop()


@pytest.mark.asyncio
async def test_send_to_peer_forwarded_to_manager_for_regular_peer() -> None:
    """Validate send_to_peer forwards to ble_manager when peer is not server client."""
    transport, _, manager = make_test_transport()
    manager_calls: list[tuple[str, BitchatPacket]] = []

    async def mock_manager_send(addr: str, p: BitchatPacket) -> None:
        manager_calls.append((addr, p))

    manager.send_to_peer = mock_manager_send  # type: ignore[method-assign]

    pkt = make_packet(b"regular peer message")
    await transport.send_to_peer("peripheral_device_1", pkt)

    assert len(manager_calls) == 1
    assert manager_calls[0] == ("peripheral_device_1", pkt)


@pytest.mark.asyncio
async def test_ble_transport_fragments_do_not_have_redundant_padding() -> None:
    """Validate fragments from BLETransport do not contain redundant block padding."""
    mock_client = MockBleakClient(address="11:22:33:44:55:66")
    ble_conn = BLEConnection(
        peer_address="11:22:33:44:55:66",
        client_factory=lambda _addr, **kwargs: mock_client,
    )
    await ble_conn.connect()
    transport = BLETransport(
        connection=ble_conn,
        sender_id=b"\x01" * 8,
        inter_fragment_delay=0.001,
    )

    large_pkt = make_packet(b"Y" * 600)
    await transport.send_packet(large_pkt)

    assert len(mock_client.written_chunks) > 1
    for _uuid, chunk, _resp in mock_client.written_chunks:
        # Without padding, fragment size is ~185 bytes (well below 256 bytes)
        assert len(chunk) < 256
