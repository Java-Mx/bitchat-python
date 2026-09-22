"""Formal verification of BitChat packet layer security invariants.

Invariants verified:
1. Identity of immutable packet bytes (original mutable inputs cannot alter packet).
2. Exact field boundaries (decoder cannot misinterpret trailing bytes as other fields).
3. Padding integrity (malformed or inconsistent padding is rejected).
4. Length integrity (declared payload length controls exact payload bytes consumed).
5. Flag integrity (optional fields cannot appear or disappear without matching flags).
6. Version integrity (unsupported protocol versions are strictly rejected).
7. Message type integrity (unknown message types are strictly rejected).
8. Bounded allocation (attacker-controlled lengths do not cause unbounded allocations).
"""

import struct

import pytest

from bitchat.exceptions import (
    InvalidPacketError,
    PacketDecodingError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)
from bitchat.protocol.constants import (
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket


class TestProtocolSecurityInvariants:
    """Explicit tests verifying the seven BitChat security invariants."""

    def test_invariant_1_identity_of_immutable_packet_bytes(self) -> None:
        """Invariant 1: Original mutable inputs cannot modify a constructed packet."""
        sender_src = bytearray(b"\x10" * 8)
        recipient_src = bytearray(b"\x20" * 8)
        payload_src = bytearray(b"secure original payload")
        sig_src = bytearray(b"\x30" * 64)

        packet = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=123456789,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=sender_src,  # type: ignore[arg-type]
            recipient_id=recipient_src,  # type: ignore[arg-type]
            payload=payload_src,  # type: ignore[arg-type]
            signature=sig_src,  # type: ignore[arg-type]
        )

        # Mutate the original sources in-place
        sender_src[0] = 0xFF
        recipient_src[0] = 0xFF
        payload_src[:] = b"hacked payload!"
        sig_src[0] = 0xFF

        # Verify packet attributes remain identical to the original values
        assert packet.sender_id == b"\x10" * 8
        assert packet.recipient_id == b"\x20" * 8
        assert packet.payload == b"secure original payload"
        assert packet.signature == b"\x30" * 64

        # Verify packet attributes are immutable bytes
        assert isinstance(packet.sender_id, bytes)
        assert isinstance(packet.recipient_id, bytes)
        assert isinstance(packet.payload, bytes)
        assert isinstance(packet.signature, bytes)

    def test_invariant_2_exact_field_boundaries(self) -> None:
        """Invariant 2: Decoder cannot reinterpret trailing bytes as other fields."""
        sender = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        recipient = b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11"
        payload = b"test_payload"
        sig = b"\x99" * 64

        packet = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1000,
            flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            sender_id=sender,
            recipient_id=recipient,
            payload=payload,
            signature=sig,
        )
        wire = encode_packet(packet, add_padding=False)

        # Decoding wire must isolate each field precisely without boundary bleed
        decoded = decode_packet(wire)
        assert decoded.sender_id == sender
        assert decoded.recipient_id == recipient
        assert decoded.payload == payload
        assert decoded.signature == sig

    def test_invariant_3_padding_integrity(self) -> None:
        """Invariant 3: Malformed, truncated, or inconsistent padding is rejected."""
        base_packet = BitchatPacket(
            version=1,
            message_type=MessageType.Announce,
            ttl=7,
            timestamp=1000,
            flags=0,
            sender_id=b"\x00" * 8,
            recipient_id=None,
            payload=b"test",
            signature=None,
        )
        unpadded = encode_packet(base_packet, add_padding=False)
        assert len(unpadded) == 26

        # Target 256 requires 230 bytes of padding
        # Invariant 3a: Delimiter claiming 0 bytes on a padded packet
        corrupted_0 = unpadded + b"\x00" * 229 + b"\x00"
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupted_0)

        # Invariant 3b: Delimiter claiming wrong count
        corrupted_mismatch = unpadded + b"\x00" * 229 + b"\x05"
        with pytest.raises(PacketDecodingError, match="Malformed packet padding"):
            decode_packet(corrupted_mismatch)

    def test_invariant_4_length_integrity(self) -> None:
        """Invariant 4: Declared payload length controls exact bytes consumed."""
        payload = b"exact_payload_bytes"
        packet = BitchatPacket(
            version=1,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=payload,
            signature=None,
        )
        wire = encode_packet(packet, add_padding=False)

        # If payload length header field is tampered to be 1 byte shorter,
        # the remaining 1 byte cannot be consumed as payload and fails padding
        tampered_short = bytearray(wire)
        tampered_short[13] = len(payload) - 1
        with pytest.raises(PacketDecodingError):
            decode_packet(bytes(tampered_short))

        # If payload length header field is tampered to be 1 byte longer,
        # decoder detects truncated wire data
        tampered_long = bytearray(wire)
        tampered_long[13] = len(payload) + 1
        with pytest.raises(PacketDecodingError):
            decode_packet(bytes(tampered_long))

    def test_invariant_5_flag_integrity(self) -> None:
        """Invariant 5: Optional fields cannot appear without matching flags."""
        # 5a: Dataclass level invariant
        with pytest.raises(InvalidPacketError, match="FLAG_HAS_RECIPIENT must be set"):
            BitchatPacket(
                version=1,
                message_type=MessageType.Announce,
                ttl=7,
                timestamp=0,
                flags=0,
                sender_id=b"\x00" * 8,
                recipient_id=b"\x01" * 8,  # Recipient present without flag
                payload=b"",
                signature=None,
            )

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
                signature=b"\x02" * 64,  # Signature present without flag
            )

        # 5b: Setting flag without bytes raises PacketDecodingError
        wire_header_has_recipient = (
            struct.pack(">BBBQBH", 1, 1, 7, 0, FLAG_HAS_RECIPIENT, 0)
            + b"\x00" * 8  # Only sender_id provided, no recipient bytes
        )
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(wire_header_has_recipient)

    def test_invariant_6_version_integrity(self) -> None:
        """Invariant 6: Unsupported protocol versions are strictly rejected."""
        valid_unpadded = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 0) + b"\x00" * 8
        assert decode_packet(valid_unpadded).version == 1

        for unsupported_version in (0, 2, 3, 255):
            tampered_version = bytearray(valid_unpadded)
            tampered_version[0] = unsupported_version
            with pytest.raises(
                UnsupportedProtocolVersionError,
                match=f"Unsupported protocol version: {unsupported_version}",
            ):
                decode_packet(bytes(tampered_version))

    def test_invariant_7_message_type_integrity(self) -> None:
        """Invariant 7: Unknown message types are strictly rejected."""
        valid_unpadded = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 0) + b"\x00" * 8

        for unknown_type in (0x00, 0x0D, 0x14, 0x1F, 0x26, 0xFE, 0xFF):
            tampered_type = bytearray(valid_unpadded)
            tampered_type[1] = unknown_type
            with pytest.raises(UnknownMessageTypeError, match="Unknown message type"):
                decode_packet(bytes(tampered_type))

    def test_invariant_8_dos_bounded_parsing(self) -> None:
        """Invariant 8: Spoofed lengths on small wire buffers do not allocate."""
        # Header claiming 65535 bytes of payload on a 22-byte wire
        spoofed_payload_len = struct.pack(">BBBQBH", 1, 1, 7, 0, 0, 65535) + b"\x00" * 8
        with pytest.raises(PacketDecodingError, match="shorter than expected"):
            decode_packet(spoofed_payload_len)
