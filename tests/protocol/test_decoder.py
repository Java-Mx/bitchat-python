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


class TestSecurityAndAdversarialInputs:
    """Rigorous tests verifying decoder behavior under attacker-controlled inputs."""

    def test_non_bytes_input_raises_decoding_error(self) -> None:
        """Non-bytes inputs to decoder utilities raise PacketDecodingError."""
        for invalid_input in (None, 12345, "string_data", [1, 2, 3], {"key": "val"}):
            with pytest.raises(PacketDecodingError, match="bytes-like object"):
                decode_packet(invalid_input)  # type: ignore[arg-type]

            with pytest.raises(PacketDecodingError, match="bytes-like object"):
                unpad_packet_data(invalid_input)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_version", [0, 2, 3, 10, 255])
    def test_mutate_version_byte_all_invalid(self, bad_version: int) -> None:
        """Unsupported version bytes strictly raise UnsupportedProtocolVersionError."""
        raw = bytearray(MINIMUM_PACKET_SIZE)
        raw[0] = bad_version
        raw[1] = 1  # Announce
        expected_msg = f"Unsupported protocol version: {bad_version}"
        with pytest.raises(UnsupportedProtocolVersionError, match=expected_msg):
            decode_packet(bytes(raw))

    @pytest.mark.parametrize(
        "bad_type",
        [0x00, 0x0D, 0x0E, 0x14, 0x1F, 0x26, 0xFE, 0xFF],
    )
    def test_mutate_message_type_unknown(self, bad_type: int) -> None:
        """Unrecognized MessageType bytes strictly raise UnknownMessageTypeError."""
        raw = bytearray(MINIMUM_PACKET_SIZE)
        raw[0] = 1  # Version 1
        raw[1] = bad_type
        with pytest.raises(UnknownMessageTypeError, match="Unknown message type"):
            decode_packet(bytes(raw))

    def test_mutate_payload_length_overflow_declaration(self) -> None:
        """Declared payload length 65535 on short wire raises PacketDecodingError."""
        raw = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 65535) + b"\x00" * 8
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(raw)

    def test_mutate_payload_length_underdeclaration_causes_padding_error(self) -> None:
        """Underdeclaring payload length causes padding consistency check to fail."""
        # 10 bytes payload provided, but header claims payload_len = 5
        wire = (
            struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 5)
            + b"\x00" * 8
            + b"1234567890"  # 10 bytes
        )
        # Expected unpadded = 14 + 8 + 5 = 27. Total len = 32.
        # Trailing 5 bytes do not match expected padding delimiter.
        with pytest.raises(PacketDecodingError):
            decode_packet(wire)

    def test_truncate_at_every_field_boundary(self) -> None:
        """Truncating at every field boundary raises PacketDecodingError."""
        full_packet = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1000,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=b"\x01" * 8,
            recipient_id=b"\x02" * 8,
            payload=b"payload_of_10",
            signature=b"\x03" * 64,
        )
        wire = encode_packet(full_packet, add_padding=False)
        assert len(wire) == 14 + 8 + 8 + len(full_packet.payload) + 64

        # Significant boundaries to test
        boundaries = [0, 1, 5, 13, 14, 21, 22, 29, 30, 39, 40, 103]
        for boundary in boundaries:
            truncated = wire[:boundary]
            with pytest.raises(PacketDecodingError):
                decode_packet(truncated)

    def test_corrupt_padding_delimiter_cases(self) -> None:
        """Malformed padding delimiter byte values are rejected with error."""
        pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=b"\x11" * 8,
            payload=b"test",
        )
        wire = encode_packet(pkt, add_padding=True)
        assert len(wire) == 256
        actual_padding_len = wire[-1]

        # Case 1: Final byte is 0
        corrupt_zero = wire[:-1] + b"\x00"
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupt_zero)

        # Case 2: Final byte is padding_needed + 1
        corrupt_plus = wire[:-1] + bytes([(actual_padding_len + 1) % 256])
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupt_plus)

        # Case 3: Final byte is padding_needed - 1
        corrupt_minus = wire[:-1] + bytes([(actual_padding_len - 1) % 256])
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupt_minus)

        # Case 4: Final byte is 255
        corrupt_255 = wire[:-1] + b"\xff"
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupt_255)

    def test_append_garbage_after_valid_packet(self) -> None:
        """Appending extra unpadded bytes to a valid packet fails verification."""
        pkt = BitchatPacket(
            version=1,
            message_type=MessageType.Announce,
            ttl=7,
            timestamp=1000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=b"test",
            signature=None,
        )
        wire = encode_packet(pkt, add_padding=False)
        garbage_wire = wire + b"\xde\xad\xbe\xef"
        with pytest.raises(PacketDecodingError):
            decode_packet(garbage_wire)

    def test_remove_bytes_from_padded_packet(self) -> None:
        """Stripping bytes from a padded packet invalidates trailing padding check."""
        pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=b"\x01" * 8,
            payload=b"test",
        )
        wire = encode_packet(pkt, add_padding=True)
        # Remove 4 bytes from end
        truncated_padded = wire[:-4]
        with pytest.raises(PacketDecodingError):
            decode_packet(truncated_padded)

    def test_change_padding_count_without_changing_length(self) -> None:
        """Altering padding count byte causes inconsistency and is rejected."""
        pkt = BitchatPacket.create(
            message_type=MessageType.Announce,
            sender_id=b"\x01" * 8,
            payload=b"test",
        )
        wire = bytearray(encode_packet(pkt, add_padding=True))
        wire[-1] = (wire[-1] ^ 0x05) or 0x01
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(bytes(wire))

    def test_random_byte_fuzz_corpus_150_samples(self) -> None:
        """Random byte sequences produce controlled errors, never uncaught crashes."""
        expected_exceptions = (
            PacketDecodingError,
            UnsupportedProtocolVersionError,
            UnknownMessageTypeError,
        )
        for i in range(150):
            # Vary lengths from 0 to 1024
            length = (i * 7 + 13) % 1025
            data = os.urandom(length)
            try:
                result = decode_packet(data)
                # If it successfully decoded, it must be a valid BitchatPacket
                assert isinstance(result, BitchatPacket)
            except expected_exceptions:
                pass  # Controlled expected error
            except Exception as e:
                pytest.fail(
                    f"Unexpected unhandled exception {type(e).__name__}: {e} "
                    f"on random payload of length {length}"
                )
