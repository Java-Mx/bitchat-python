"""Adversarial stress harness for Milestone 2: BLE GATT server inbound routing."""

from __future__ import annotations

import os
import time

import pytest
from tests.ble.mocks import MockBleakScanner, MockBLEServerBackend

from bitchat.ble.adapter import AdapterInfo, BLEAdapterManager
from bitchat.ble.manager import BLEManager
from bitchat.ble.server import BLEServer
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
        device_id="adversarial-adapter",
        name="Adversarial BLE",
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


def make_packet(
    payload: bytes = b"adversarial ble test",
    sender_id: bytes = b"\xaa" * 8,
) -> BitchatPacket:
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=sender_id,
        recipient_id=b"\xbb" * 8,
        payload=payload,
        signature=None,
    )


@pytest.mark.asyncio
async def test_adversarial_ble_gatt_out_of_order_fragments() -> None:
    """Verify out-of-order fragmented data chunks are reassembled cleanly."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    large_payload = b"Adversarial Reassembly Test: " + os.urandom(650)
    orig_pkt = make_packet(payload=large_payload)
    encoded = encode_packet(orig_pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded,
        sender_id=orig_pkt.sender_id,
        original_message_type=orig_pkt.message_type,
    )
    assert len(fragments) >= 4, f"Expected >= 4 fragments, got {len(fragments)}"

    out_of_order_indices = list(reversed(range(len(fragments))))

    for idx in out_of_order_indices[:-1]:
        frag_bytes = encode_packet(fragments[idx], add_padding=False)
        transport._handle_server_data(frag_bytes, "client_ooo_1")
        assert len(received) == 0, f"Premature emission at chunk {idx}!"

    final_idx = out_of_order_indices[-1]
    final_frag_bytes = encode_packet(fragments[final_idx], add_padding=False)
    transport._handle_server_data(final_frag_bytes, "client_ooo_1")

    assert len(received) == 1, "Failed to emit packet after all chunks received!"
    delivered_pkt, client_addr = received[0]
    assert client_addr == "client_ooo_1"
    assert delivered_pkt.payload == large_payload


@pytest.mark.asyncio
async def test_adversarial_ble_gatt_duplicate_fragments() -> None:
    """Verify duplicate fragment packets do not cause corruption."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    large_payload = b"Duplicate test payload " * 35
    orig_pkt = make_packet(payload=large_payload)
    encoded = encode_packet(orig_pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded,
        sender_id=orig_pkt.sender_id,
        original_message_type=orig_pkt.message_type,
    )

    frag0_bytes = encode_packet(fragments[0], add_padding=False)
    transport._handle_server_data(frag0_bytes, "client_dup")
    transport._handle_server_data(frag0_bytes, "client_dup")
    transport._handle_server_data(frag0_bytes, "client_dup")

    for frag in fragments[1:]:
        frag_bytes = encode_packet(frag, add_padding=False)
        transport._handle_server_data(frag_bytes, "client_dup")

    assert len(received) == 1
    assert received[0][0].payload == large_payload


@pytest.mark.asyncio
async def test_adversarial_ble_gatt_conflicting_fragment_chunks() -> None:
    """Verify conflicting chunk data for the same index aborts assembly."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    orig_pkt = make_packet(payload=b"A" * 600)
    encoded = encode_packet(orig_pkt, add_padding=False)
    fragments = fragment_encoded_packet(
        encoded,
        sender_id=orig_pkt.sender_id,
        original_message_type=orig_pkt.message_type,
    )

    transport._handle_server_data(
        encode_packet(fragments[0], add_padding=False), "client_conflict"
    )

    corrupted_frag0 = BitchatPacket(
        version=fragments[0].version,
        message_type=fragments[0].message_type,
        ttl=fragments[0].ttl,
        timestamp=fragments[0].timestamp,
        flags=fragments[0].flags,
        sender_id=fragments[0].sender_id,
        recipient_id=fragments[0].recipient_id,
        payload=fragments[0].payload[:-1] + b"\xff",
        signature=None,
    )
    transport._handle_server_data(
        encode_packet(corrupted_frag0, add_padding=False), "client_conflict"
    )

    for frag in fragments[1:]:
        transport._handle_server_data(
            encode_packet(frag, add_padding=False), "client_conflict"
        )

    assert len(received) == 0


@pytest.mark.asyncio
async def test_adversarial_ble_gatt_interleaved_multi_client_fragments() -> None:
    """Verify interleaved fragments from multiple clients reassemble cleanly."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    payload_a = b"Client A payload: " + b"1" * 500
    pkt_a = make_packet(payload=payload_a, sender_id=b"\x0a" * 8)
    fragments_a = fragment_encoded_packet(
        encode_packet(pkt_a, add_padding=False),
        sender_id=pkt_a.sender_id,
        original_message_type=pkt_a.message_type,
    )

    payload_b = b"Client B payload: " + b"2" * 500
    pkt_b = make_packet(payload=payload_b, sender_id=b"\x0b" * 8)
    fragments_b = fragment_encoded_packet(
        encode_packet(pkt_b, add_padding=False),
        sender_id=pkt_b.sender_id,
        original_message_type=pkt_b.message_type,
    )

    max_len = max(len(fragments_a), len(fragments_b))
    for i in range(max_len):
        if i < len(fragments_a):
            transport._handle_server_data(
                encode_packet(fragments_a[i], add_padding=False), "client_a"
            )
        if i < len(fragments_b):
            transport._handle_server_data(
                encode_packet(fragments_b[i], add_padding=False), "client_b"
            )

    assert len(received) == 2
    rec_a = next(p for p, addr in received if addr == "client_a")
    rec_b = next(p for p, addr in received if addr == "client_b")
    assert rec_a.payload == payload_a
    assert rec_b.payload == payload_b


@pytest.mark.asyncio
async def test_adversarial_ble_gatt_fuzzed_corrupt_data() -> None:
    """Verify 200 arbitrary corrupt or fuzzed byte inputs never crash handler."""
    transport, _, _ = make_test_transport()
    received: list[tuple[BitchatPacket, str]] = []
    transport.on_packet_received = lambda pkt, addr: received.append((pkt, addr))

    corrupt_inputs: list[bytes] = [
        b"",
        b"\x00",
        b"\xff" * 5,
        b"BitchatMagicHeaderTruncated",
        os.urandom(1),
        os.urandom(10),
        os.urandom(50),
        os.urandom(256),
        os.urandom(1024),
    ]
    for _ in range(190):
        corrupt_inputs.append(os.urandom(int.from_bytes(os.urandom(1), "big")))

    for i, bad_data in enumerate(corrupt_inputs):
        transport._handle_server_data(bad_data, f"attacker_{i % 10}")

    assert len(received) == 0
