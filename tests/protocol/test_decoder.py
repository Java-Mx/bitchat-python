"""Unit tests for the BitChat binary packet decoder and unpadding logic."""

import contextlib
import os
import struct

import pytest

from bitchat.exceptions import (
    PacketDecodingError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)
from bitchat.protocol.constants import (
    BROADCAST_RECIPIENT,
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    MINIMUM_PACKET_SIZE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet, unpad_packet_data
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket


class TestDecoder:
    """Validate packet decoding against wire formats and malformed inputs."""

    def test_decode_unpadded_minimal_packet(self) -> None:
        """Decode exact unpadded Announce packet."""
        raw_hex = (
            "01"  # Version = 1
            "01"  # Type = Announce (0x01)
            "07"  # TTL = 7
            "0000018bcfe56800"  # Timestamp = 1700000000000
            "00"  # Flags = 0
            "0000"  # Payload Length = 0
            "0102030405060708"  # Sender ID
        )
        data = bytes.fromhex(raw_hex)
        pkt = decode_packet(data)

        assert pkt.version == 1
        assert pkt.message_type == MessageType.Announce
        assert pkt.ttl == 7
        assert pkt.timestamp == 1700000000000
        assert pkt.flags == 0
        assert pkt.sender_id == bytes.fromhex("0102030405060708")
        assert pkt.recipient_id is None
        assert pkt.payload == b""
        assert pkt.signature is None

    def test_decode_with_broadcast_recipient(self) -> None:
        """Decode packet carrying broadcast recipient."""
        raw_hex = (
            "01"  # Version
            "04"  # Type = Message
            "07"  # TTL
            "0000018bcfe56800"  # Timestamp
            "01"  # Flags = FLAG_HAS_RECIPIENT
            "0005"  # Payload Length = 5
            "0102030405060708"  # Sender ID
            "ffffffffffffffff"  # Recipient ID = Broadcast
            "48656c6c6f"  # Payload = "Hello"
        )
        data = bytes.fromhex(raw_hex)
        pkt = decode_packet(data)

        assert pkt.version == 1
        assert pkt.message_type == MessageType.Message
        assert pkt.recipient_id == BROADCAST_RECIPIENT
        assert pkt.payload == b"Hello"
        assert pkt.has_recipient is True
        assert pkt.signature is None

    def test_decode_padded_packet(self) -> None:
        """Decode packet with valid trailing padding bytes."""
        original_pkt = BitchatPacket.create(
            message_type=MessageType.DeliveryAck,
            sender_id=b"\x12" * 8,
            recipient_id=b"\x34" * 8,
            payload=b"ack_payload_data",
        )
        encoded_padded = encode_packet(original_pkt, add_padding=True)
        assert len(encoded_padded) == 256

        decoded = decode_packet(encoded_padded)
        assert decoded.version == original_pkt.version
        assert decoded.message_type == original_pkt.message_type
        assert decoded.ttl == original_pkt.ttl
        assert decoded.sender_id == original_pkt.sender_id
        assert decoded.recipient_id == original_pkt.recipient_id
        assert decoded.payload == original_pkt.payload
        assert decoded.signature is None

    def test_decode_with_signature(self) -> None:
        """Decode packet containing 64-byte signature."""
        sig = b"\xfe" * 64
        original_pkt = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=b"\x01" * 8,
            payload=b"signed content",
            signature=sig,
        )
        encoded = encode_packet(original_pkt, add_padding=False)
        decoded = decode_packet(encoded)

        assert decoded.signature == sig
        assert decoded.has_signature is True

    def test_decode_preserves_compression_flag(self) -> None:
        """FLAG_IS_COMPRESSED is preserved without decompressing in Phase 3."""
        original_pkt = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=b"\x01" * 8,
            payload=b"raw compressed bytes",
            is_compressed=True,
        )
        encoded = encode_packet(original_pkt, add_padding=False)
        decoded = decode_packet(encoded)

        assert decoded.is_compressed is True
        assert decoded.payload == b"raw compressed bytes"

    def test_unpad_packet_data_utility(self) -> None:
        """Standalone unpad_packet_data functions correctly."""
        assert unpad_packet_data(b"") == b""

        # 4 bytes data + 3 bytes padding (last byte is 3)
        data = b"DATA\x00\x00\x03"
        assert unpad_packet_data(data) == b"DATA"

        # Padding length 0 returns unchanged
        assert unpad_packet_data(b"DATA\x00") == b"DATA\x00"

        # Padding length > data length returns unchanged
        assert unpad_packet_data(b"DAT\x05") == b"DAT\x05"


class TestDecoderErrors:
    """Validate explicit errors on malformed or truncated packets."""

    def test_packet_too_small(self) -> None:
        """Packets smaller than 22 bytes raise PacketDecodingError."""
        with pytest.raises(PacketDecodingError, match="Packet too small"):
            decode_packet(b"\x01" * (MINIMUM_PACKET_SIZE - 1))

    def test_unsupported_version(self) -> None:
        """Version != 1 raises UnsupportedProtocolVersionError."""
        raw = bytearray(MINIMUM_PACKET_SIZE)
        raw[0] = 2  # Version 2
        raw[1] = 1  # Type Announce
        with pytest.raises(
            UnsupportedProtocolVersionError, match="Unsupported protocol version: 2"
        ):
            decode_packet(bytes(raw))

    def test_unknown_message_type(self) -> None:
        """Unrecognized message type byte raises UnknownMessageTypeError."""
        raw = bytearray(MINIMUM_PACKET_SIZE)
        raw[0] = 1  # Version 1
        raw[1] = 0x99  # Invalid MessageType
        with pytest.raises(UnknownMessageTypeError, match="Unknown message type"):
            decode_packet(bytes(raw))

    def test_truncated_payload(self) -> None:
        """Packets shorter than payload length indicates raise PacketDecodingError."""
        # Header specifies payload_len = 100, but only 22 bytes total provided
        raw = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 100) + b"\x00" * 8
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(raw)

    def test_truncated_recipient(self) -> None:
        """FLAG_HAS_RECIPIENT set without recipient bytes raises PacketDecodingError."""
        raw = struct.pack(">BBBQBH", 1, 1, 7, 0, FLAG_HAS_RECIPIENT, 0) + b"\x00" * 8
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(raw)

    def test_truncated_signature(self) -> None:
        """FLAG_HAS_SIGNATURE set without signature bytes raises PacketDecodingError."""
        raw = struct.pack(">BBBQBH", 1, 1, 7, 0, FLAG_HAS_SIGNATURE, 0) + b"\x00" * 8
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(raw)

    def test_malformed_padding_last_byte_zero(self) -> None:
        """Padded packet where last byte is 0 raises PacketDecodingError."""
        base = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 0) + b"\x00" * 8  # 22 bytes
        corrupted = base + b"\xaa\xaa\xaa\xaa\x00"
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupted)

    def test_malformed_padding_mismatched_length(self) -> None:
        """Padding with mismatched final byte raises PacketDecodingError."""
        base = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 0) + b"\x00" * 8  # 22 bytes
        corrupted = base + b"\x01" * 9 + bytes([5])
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupted)

    def test_fuzz_random_bytes_decoder_robustness(self) -> None:
        """Random byte sequences produce controlled errors, not unhandled crashes."""
        for _ in range(50):
            length = int.from_bytes(os.urandom(1), "big") % 300
            random_data = os.urandom(length)
            with contextlib.suppress(PacketDecodingError):
                decode_packet(random_data)
