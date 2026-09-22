"""Unit tests for the BitChat binary packet encoder and padding logic."""

import struct

import pytest

from bitchat.exceptions import PacketEncodingError
from bitchat.protocol.constants import (
    BROADCAST_RECIPIENT,
    FIXED_HEADER_SIZE,
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.encoder import (
    encode_packet,
    get_optimal_block_size,
    pad_packet_data,
)
from bitchat.protocol.packet import BitchatPacket


class TestPaddingLogic:
    """Validate padding size calculation and structure."""

    @pytest.mark.parametrize(
        ("unpadded_len", "expected_target"),
        [
            (10, 256),  # 10 + 16 = 26 <= 256
            (239, 256),  # 239 + 16 = 255 <= 256
            (240, 256),  # 240 + 16 = 256 <= 256
            (241, 512),  # 241 + 16 = 257 > 256, <= 512
            (496, 512),  # 496 + 16 = 512 <= 512
            (497, 1024),  # 497 + 16 = 513 <= 1024
            (1008, 1024),  # 1008 + 16 = 1024 <= 1024
            (1009, 2048),  # 1009 + 16 = 1025 <= 2048
            (2032, 2048),  # 2032 + 16 = 2048 <= 2048
            (2033, 2033),  # Exceeds 2048 - 16, returns unpadded size
            (3000, 3000),  # Very large message
        ],
    )
    def test_optimal_block_size(self, unpadded_len: int, expected_target: int) -> None:
        """Optimal block size accounts for 16-byte overhead and matches block bounds."""
        assert get_optimal_block_size(unpadded_len) == expected_target

    def test_pad_packet_normal(self) -> None:
        """Padded packet reaches target size and has correct last byte."""
        data = b"\x01" * 100
        padded = pad_packet_data(data, target_size=256)
        assert len(padded) == 256
        assert padded[:100] == data
        # 256 - 100 = 156 bytes of padding
        assert padded[-1] == 156

    def test_pad_packet_exact_target(self) -> None:
        """Data already at target size is not padded."""
        data = b"\x01" * 256
        padded = pad_packet_data(data, target_size=256)
        assert padded == data
        assert len(padded) == 256

    def test_pad_packet_padding_exceeds_255(self) -> None:
        """Data requiring > 255 bytes of padding is returned unchanged."""
        # Target 512 with 241 bytes -> padding needed = 271 > 255
        data = b"\x01" * 241
        padded = pad_packet_data(data, target_size=512)
        assert padded == data
        assert len(padded) == 241

    def test_pad_packet_final_byte_indicates_padding_length(self) -> None:
        """For any padded message, the final byte strictly matches the pad length."""
        for length in (22, 50, 100, 200, 240):
            data = b"\x42" * length
            padded = pad_packet_data(data)
            padding_len = padded[-1]
            assert len(padded) - length == padding_len
            assert padded[:length] == data


class TestPacketEncoder:
    """Validate deterministic binary wire serialization."""

    def test_deterministic_vector_minimal_unpadded(self) -> None:
        """Test Vector 1: Minimal Announce packet without recipient or signature."""
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Announce,
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01\x02\x03\x04\x05\x06\x07\x08",
            recipient_id=None,
            payload=b"",
            signature=None,
        )

        wire = encode_packet(pkt, add_padding=False)
        expected_hex = (
            "01"  # Version
            "01"  # Type
            "07"  # TTL
            "0000018bcfe56800"  # Timestamp (1700000000000 BE u64)
            "00"  # Flags
            "0000"  # Payload Length (0 BE u16)
            "0102030405060708"  # Sender ID
        )

        assert wire.hex() == expected_hex
        assert len(wire) == FIXED_HEADER_SIZE + SENDER_ID_SIZE  # 22 bytes

    def test_deterministic_vector_with_broadcast_recipient(self) -> None:
        """Test Vector 2: Message packet with broadcast recipient and text payload."""
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1700000000000,
            flags=FLAG_HAS_RECIPIENT,
            sender_id=b"\x01\x02\x03\x04\x05\x06\x07\x08",
            recipient_id=BROADCAST_RECIPIENT,
            payload=b"Hello",
            signature=None,
        )

        wire = encode_packet(pkt, add_padding=False)
        expected_hex = (
            "01"  # Version
            "04"  # Type (Message)
            "07"  # TTL
            "0000018bcfe56800"  # Timestamp
            "01"  # Flags (FLAG_HAS_RECIPIENT)
            "0005"  # Payload Length (5 BE u16)
            "0102030405060708"  # Sender ID
            "ffffffffffffffff"  # Recipient ID (Broadcast)
            "48656c6c6f"  # Payload ("Hello")
        )

        assert wire.hex() == expected_hex
        assert len(wire) == FIXED_HEADER_SIZE + 8 + 8 + 5  # 35 bytes

    def test_deterministic_vector_with_recipient_and_signature(self) -> None:
        """Test Vector 3: Packet with directed recipient and 64-byte signature."""
        sig = b"\x77" * 64
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.KeyExchange,
            ttl=5,
            timestamp=1000,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=b"\xaa" * 8,
            recipient_id=b"\xbb" * 8,
            payload=b"\xcc" * 10,
            signature=sig,
        )

        wire = encode_packet(pkt, add_padding=False)
        assert len(wire) == FIXED_HEADER_SIZE + 8 + 8 + 10 + 64  # 104 bytes
        assert wire[0] == 1
        assert wire[1] == MessageType.KeyExchange.value
        assert wire[2] == 5
        assert struct.unpack(">Q", wire[3:11])[0] == 1000
        assert wire[11] == FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE
        assert struct.unpack(">H", wire[12:14])[0] == 10
        assert wire[14:22] == b"\xaa" * 8
        assert wire[22:30] == b"\xbb" * 8
        assert wire[30:40] == b"\xcc" * 10
        assert wire[40:104] == sig

    def test_maximum_valid_uint16_payload(self) -> None:
        """Packets with 65535-byte payload serialize correctly without padding."""
        payload = b"\x55" * 65535
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=0,
            flags=0,
            sender_id=b"\x00" * 8,
            recipient_id=None,
            payload=payload,
            signature=None,
        )
        wire = encode_packet(pkt, add_padding=False)
        assert len(wire) == FIXED_HEADER_SIZE + 8 + 65535
        assert struct.unpack(">H", wire[12:14])[0] == 65535

    def test_encode_with_padding_default(self) -> None:
        """By default, encode_packet applies block padding up to optimal size."""
        pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=b"\x01" * 8,
            payload=b"test",
        )
        wire = encode_packet(pkt, add_padding=True)
        # 14 + 8 + 4 = 26 bytes. 26 + 16 = 42 <= 256. Target = 256.
        assert len(wire) == 256
        padding_len = wire[-1]
        assert padding_len == 256 - 26

    def test_encoding_error_on_inconsistent_packet(self) -> None:
        """Inconsistent flags without required fields raise PacketEncodingError."""
        # Using object.__setattr__ to bypass dataclass validation
        pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=b"\x01" * 8,
        )
        # Artificially set flag without recipient
        object.__setattr__(pkt, "flags", FLAG_HAS_RECIPIENT)
        with pytest.raises(PacketEncodingError):
            encode_packet(pkt)
