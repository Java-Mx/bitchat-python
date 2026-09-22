"""Interoperability and round-trip integration tests for fragmentation."""

from __future__ import annotations

from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    encode_fragment_packets,
    fragment_encoded_packet,
    fragment_packet,
    parse_fragment_payload,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler


class TestRustWireCompatibilityVectors:
    """Validate binary layout matches the exact Rust reference format.

    Reference:
      `src/fragmentation.rs` line 178:
        fragmentID (8) + index (2) + total (2) + originalType (1) + data
        index_bytes = [(index >> 8) as u8, (index & 0xFF) as u8]
        total_bytes = [(total >> 8) as u8, (total & 0xFF) as u8]
        originalType = 1 byte
    """

    def test_metadata_wire_layout_vector(self) -> None:
        frag_id = bytes.fromhex("0102030405060708")
        index = 1
        total = 3
        orig_type = MessageType.Message  # 0x04
        chunk = b"TEST CHUNK DATA"

        payload = create_fragment_payload(frag_id, index, total, orig_type, chunk)

        # Expected wire representation:
        # 0..8:   01 02 03 04 05 06 07 08
        # 8..10:  00 01 (BE u16)
        # 10..12: 00 03 (BE u16)
        # 12:     04 (u8)
        # 13..:   b"TEST CHUNK DATA"
        expected_header = bytes.fromhex("01020304050607080001000304")
        assert payload[:13] == expected_header
        assert payload[13:] == chunk

    def test_parse_reference_style_vector(self) -> None:
        raw_payload = bytes.fromhex("aabbccdd112233440000000408") + b"sample payload"
        frag_id, index, total, orig_type, data = parse_fragment_payload(raw_payload)

        assert frag_id == bytes.fromhex("aabbccdd11223344")
        assert index == 0
        assert total == 4
        assert orig_type == 0x08  # ChannelAnnounce
        assert data == b"sample payload"


class TestEndToEndFragmentationPipeline:
    """Integration test verifying full round-trip:

    original packet
    → encode
    → fragment
    → encode fragment packets
    → decode fragment packets
    → reassemble
    → decode original packet
    """

    def test_full_roundtrip_message_packet(self) -> None:
        # Create an original large Message packet that exceeds 500 bytes
        payload_data = (
            b"This is a large chat message that will be fragmented over BLE. " * 15
        )
        original_packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1700000000000,
            flags=FLAG_HAS_RECIPIENT,
            sender_id=b"\x01\x02\x03\x04\x05\x06\x07\x08",
            recipient_id=b"\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10",
            payload=payload_data,
            signature=None,
        )

        # 1. Encode original packet to wire bytes
        original_encoded_bytes = encode_packet(original_packet)
        assert len(original_encoded_bytes) > 500

        # 2. Fragment the encoded packet (testing byte-for-byte reconstruction)
        fragment_packets = fragment_encoded_packet(
            encoded_packet=original_encoded_bytes,
            sender_id=original_packet.sender_id,
            original_message_type=original_packet.message_type,
            ttl=original_packet.ttl,
            timestamp=original_packet.timestamp,
        )
        assert len(fragment_packets) >= 4
        assert fragment_packets[0].message_type == MessageType.FragmentStart
        assert fragment_packets[-1].message_type == MessageType.FragmentEnd

        # 3. Encode fragment packets to wire bytes (as transmitted over BLE)
        transmitted_frames = encode_fragment_packets(fragment_packets)
        assert len(transmitted_frames) == len(fragment_packets)

        # 4. Simulate BLE reception: decode each received frame into BitchatPacket
        received_fragment_packets = [
            decode_packet(frame) for frame in transmitted_frames
        ]

        # 5. Reassemble fragments
        reassembler = FragmentReassembler()
        reassembled_bytes = None
        for frag in received_fragment_packets:
            res = reassembler.add_fragment_packet(frag)
            if res is not None:
                reassembled_bytes = res

        # 6. Verify exact byte-for-byte match with original encoded bytes
        assert reassembled_bytes is not None
        assert reassembled_bytes == original_encoded_bytes

        # 7. Decode reassembled bytes into final packet
        reconstructed_packet = decode_packet(reassembled_bytes)

        # 8. Verify semantic equality with original packet
        assert reconstructed_packet == original_packet
        assert reconstructed_packet.version == original_packet.version
        assert reconstructed_packet.message_type == original_packet.message_type
        assert reconstructed_packet.ttl == original_packet.ttl
        assert reconstructed_packet.timestamp == original_packet.timestamp
        assert reconstructed_packet.sender_id == original_packet.sender_id
        assert reconstructed_packet.recipient_id == original_packet.recipient_id
        assert reconstructed_packet.payload == original_packet.payload

    def test_full_roundtrip_channel_announce_packet(self) -> None:
        channel_payload = b"#public|0|creator_peer_id|commitment_data|" + (b"X" * 600)
        original_packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.ChannelAnnounce,
            ttl=7,
            timestamp=1700000000123,
            flags=0,
            sender_id=b"\xaa" * 8,
            recipient_id=None,
            payload=channel_payload,
            signature=None,
        )

        fragment_packets = fragment_packet(original_packet)
        transmitted_frames = encode_fragment_packets(fragment_packets)

        reassembler = FragmentReassembler()
        reassembled_bytes = None
        for frame in transmitted_frames:
            frag_pkt = decode_packet(frame)
            res = reassembler.add_fragment_packet(frag_pkt)
            if res is not None:
                reassembled_bytes = res
        assert reassembled_bytes is not None
        reconstructed = decode_packet(reassembled_bytes)
        assert reconstructed == original_packet

    def test_fragment_packet_convenience_api_semantic_roundtrip(self) -> None:
        """Verify fragment_packet produces valid reconstructed packet."""
        packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1700000000456,
            flags=FLAG_HAS_RECIPIENT,
            sender_id=b"\x12\x34\x56\x78\x90\xab\xcd\xef",
            recipient_id=b"\xfe\xdc\xba\x09\x87\x65\x43\x21",
            payload=b"A" * 600,
            signature=None,
        )

        # Convenience function fragments the packet directly
        frags = fragment_packet(packet)
        assert len(frags) >= 4

        # Reassemble
        reassembler = FragmentReassembler()
        reassembled = None
        for f in frags:
            res = reassembler.add_fragment_packet(f)
            if res is not None:
                reassembled = res

        assert reassembled is not None
        decoded = decode_packet(reassembled)
        assert decoded == packet
