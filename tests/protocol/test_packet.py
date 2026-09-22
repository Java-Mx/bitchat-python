"""Unit tests for the BitchatPacket model and identity helpers."""

import pytest

from bitchat.exceptions import InvalidPacketError
from bitchat.protocol.constants import (
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    FLAG_IS_COMPRESSED,
    MessageType,
)
from bitchat.protocol.packet import (
    BitchatPacket,
    peer_id_from_hex,
    peer_id_to_hex,
)


class TestPeerIdHelpers:
    """Validate peer ID hexadecimal conversion helpers."""

    def test_peer_id_to_hex_valid(self) -> None:
        """8-byte binary ID converts to 16 hex chars."""
        raw = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        assert peer_id_to_hex(raw) == "0102030405060708"

    def test_peer_id_to_hex_invalid_length(self) -> None:
        """Non-8-byte inputs raise InvalidPacketError."""
        with pytest.raises(InvalidPacketError, match="must be exactly 8 bytes"):
            peer_id_to_hex(b"\x01\x02")

    def test_peer_id_from_hex_valid(self) -> None:
        """16 hex chars convert to 8 raw bytes."""
        hex_str = "0102030405060708"
        assert peer_id_from_hex(hex_str) == b"\x01\x02\x03\x04\x05\x06\x07\x08"

    def test_peer_id_from_hex_invalid_chars(self) -> None:
        """Non-hex characters raise InvalidPacketError."""
        with pytest.raises(InvalidPacketError, match="Invalid hexadecimal"):
            peer_id_from_hex("not_hex_chars_12")

    def test_peer_id_from_hex_invalid_length(self) -> None:
        """Hex strings not representing 8 bytes raise InvalidPacketError."""
        with pytest.raises(InvalidPacketError, match="must represent 8 bytes"):
            peer_id_from_hex("0102")


class TestBitchatPacketModel:
    """Validate BitchatPacket construction, immutability, and constraints."""

    @pytest.fixture
    def valid_packet(self) -> BitchatPacket:
        """Fixture providing a basic valid packet."""
        return BitchatPacket(
            version=1,
            message_type=MessageType.Announce,
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=b"test payload",
            signature=None,
        )

    def test_valid_packet_properties(self, valid_packet: BitchatPacket) -> None:
        """Packet properties reflect its initialized state."""
        assert valid_packet.version == 1
        assert valid_packet.message_type == MessageType.Announce
        assert valid_packet.ttl == 7
        assert valid_packet.timestamp == 1700000000000
        assert valid_packet.flags == 0
        assert not valid_packet.has_recipient
        assert not valid_packet.has_signature
        assert not valid_packet.is_compressed
        assert valid_packet.sender_id_hex == "01" * 8
        assert valid_packet.recipient_id_hex is None

    def test_packet_immutability(self, valid_packet: BitchatPacket) -> None:
        """BitchatPacket is a frozen dataclass and cannot be modified."""
        with pytest.raises(AttributeError):
            valid_packet.ttl = 3  # type: ignore[misc]

    def test_create_factory_method(self) -> None:
        """create factory automatically computes flags and timestamps."""
        pkt = BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=b"\xaa" * 8,
            payload=b"Hello",
            recipient_id=b"\xbb" * 8,
            signature=b"\xcc" * 64,
            is_compressed=True,
        )
        assert pkt.version == 1
        assert pkt.message_type == MessageType.Message
        assert pkt.ttl == 7
        assert pkt.has_recipient is True
        assert pkt.has_signature is True
        assert pkt.is_compressed is True
        assert pkt.flags == (
            FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE | FLAG_IS_COMPRESSED
        )
        assert pkt.recipient_id_hex == "bb" * 8
        assert pkt.signature == b"\xcc" * 64

    def test_invalid_version(self) -> None:
        """Version outside 0..255 raises InvalidPacketError."""
        with pytest.raises(InvalidPacketError, match="Version"):
            BitchatPacket(
                version=300,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

    def test_invalid_sender_id_length(self) -> None:
        """Sender ID not 8 bytes raises InvalidPacketError."""
        with pytest.raises(
            InvalidPacketError, match="Sender ID must be exactly 8 bytes"
        ):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 7,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

    def test_invalid_recipient_id_length(self) -> None:
        """Recipient ID not 8 bytes when present raises InvalidPacketError."""
        with pytest.raises(
            InvalidPacketError, match="Recipient ID must be exactly 8 bytes"
        ):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=FLAG_HAS_RECIPIENT,
                sender_id=b"\x00" * 8,
                recipient_id=b"\x00" * 9,
                payload=b"",
                signature=None,
            )

    def test_flags_recipient_inconsistency(self) -> None:
        """Recipient ID present without flag or absent with flag raises error."""
        with pytest.raises(InvalidPacketError, match="FLAG_HAS_RECIPIENT must be set"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,  # Missing FLAG_HAS_RECIPIENT
                sender_id=b"\x00" * 8,
                recipient_id=b"\x00" * 8,
                payload=b"",
                signature=None,
            )

        with pytest.raises(
            InvalidPacketError, match="FLAG_HAS_RECIPIENT must not be set"
        ):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=FLAG_HAS_RECIPIENT,  # Has flag but None recipient
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

    def test_invalid_signature_length(self) -> None:
        """Signature not 64 bytes when present raises InvalidPacketError."""
        with pytest.raises(
            InvalidPacketError, match="Signature must be exactly 64 bytes"
        ):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=FLAG_HAS_SIGNATURE,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=b"\x00" * 32,
            )

    def test_flags_signature_inconsistency(self) -> None:
        """Signature present without flag or absent with flag raises error."""
        with pytest.raises(InvalidPacketError, match="FLAG_HAS_SIGNATURE must be set"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=b"\x00" * 64,
            )

    def test_payload_length_overflow(self) -> None:
        """Payload exceeding 65535 bytes raises InvalidPacketError."""
        with pytest.raises(InvalidPacketError, match="Payload length exceeds maximum"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"\x00" * 65536,
                signature=None,
            )

    def test_immutability_from_mutable_bytearray(self) -> None:
        """Passing bytearray produces strictly immutable bytes attributes."""
        sender_buf = bytearray(b"\x11" * 8)
        recipient_buf = bytearray(b"\x22" * 8)
        payload_buf = bytearray(b"mutable payload")
        sig_buf = bytearray(b"\x33" * 64)

        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1000,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=sender_buf,  # type: ignore[arg-type]
            recipient_id=recipient_buf,  # type: ignore[arg-type]
            payload=payload_buf,  # type: ignore[arg-type]
            signature=sig_buf,  # type: ignore[arg-type]
        )

        assert type(pkt.sender_id) is bytes
        assert type(pkt.recipient_id) is bytes
        assert type(pkt.payload) is bytes
        assert type(pkt.signature) is bytes

    def test_mutation_of_original_bytearray_does_not_alter_packet(self) -> None:
        """Mutating original bytearray after creation has zero effect on packet."""
        sender_buf = bytearray(b"\x11" * 8)
        recipient_buf = bytearray(b"\x22" * 8)
        payload_buf = bytearray(b"original payload")
        sig_buf = bytearray(b"\x33" * 64)

        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1000,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=sender_buf,  # type: ignore[arg-type]
            recipient_id=recipient_buf,  # type: ignore[arg-type]
            payload=payload_buf,  # type: ignore[arg-type]
            signature=sig_buf,  # type: ignore[arg-type]
        )

        # Mutate the source buffers
        sender_buf[0] = 0xFF
        recipient_buf[0] = 0xEE
        payload_buf[:] = b"tampered payload!"
        sig_buf[0] = 0xAA

        # Verify packet values are unchanged
        assert pkt.sender_id == b"\x11" * 8
        assert pkt.recipient_id == b"\x22" * 8
        assert pkt.payload == b"original payload"
        assert pkt.signature == b"\x33" * 64

    def test_packet_fields_cannot_be_reassigned(
        self, valid_packet: BitchatPacket
    ) -> None:
        """Packet fields cannot be reassigned (FrozenInstanceError / AttributeError)."""
        with pytest.raises((AttributeError, TypeError)):
            valid_packet.sender_id = b"\x99" * 8  # type: ignore[misc]

        with pytest.raises((AttributeError, TypeError)):
            valid_packet.payload = b"new payload"  # type: ignore[misc]

    def test_packet_byte_fields_cannot_be_mutated_in_place(
        self, valid_packet: BitchatPacket
    ) -> None:
        """Packet byte attributes cannot be modified in-place."""
        with pytest.raises(TypeError, match="does not support item assignment"):
            valid_packet.sender_id[0] = 0xFF  # type: ignore[index]

        with pytest.raises(TypeError, match="does not support item assignment"):
            valid_packet.payload[0] = 0xFF  # type: ignore[index]

    def test_integer_fields_reject_bool(self) -> None:
        """Boolean values (subclass of int) are rejected for integer fields."""
        with pytest.raises(InvalidPacketError, match="Version"):
            BitchatPacket(
                version=True,  # type: ignore[arg-type]
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

        with pytest.raises(InvalidPacketError, match="TTL"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=False,  # type: ignore[arg-type]
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

        with pytest.raises(InvalidPacketError, match="Flags"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=True,  # type: ignore[arg-type]
                sender_id=b"\x00" * 8,
                recipient_id=None,
                payload=b"",
                signature=None,
            )

    def test_peer_id_helpers_reject_invalid_types(self) -> None:
        """Peer ID conversion helpers strictly check types."""
        with pytest.raises(InvalidPacketError, match="bytes-like object"):
            peer_id_to_hex(12345)  # type: ignore[arg-type]

        with pytest.raises(InvalidPacketError, match="must be a str"):
            peer_id_from_hex(b"0102030405060708")  # type: ignore[arg-type]

    def test_compressed_flag_preserves_payload_verbatim(self) -> None:
        """In Phase 3, FLAG_IS_COMPRESSED preserves payload bytes unmodified."""
        raw_payload = b"raw compressed bytes \x00\x01\x02\xff"
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=12345,
            flags=FLAG_IS_COMPRESSED,
            sender_id=b"\xaa" * 8,
            recipient_id=None,
            payload=raw_payload,
            signature=None,
        )
        assert pkt.is_compressed is True
        assert pkt.payload == raw_payload

    def test_unknown_reserved_flags_preserved(self) -> None:
        """Reserved flag bits are preserved on the model for forward compatibility."""
        flags_with_reserved = FLAG_HAS_RECIPIENT | 0x80 | 0x20
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=12345,
            flags=flags_with_reserved,
            sender_id=b"\xaa" * 8,
            recipient_id=b"\xbb" * 8,
            payload=b"test",
            signature=None,
        )
        assert pkt.flags == flags_with_reserved
        assert pkt.has_recipient is True
