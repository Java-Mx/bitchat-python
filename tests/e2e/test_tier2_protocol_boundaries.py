"""Tier 2: Boundary & Corner Cases — Protocol Framing Boundaries."""

from __future__ import annotations

import os
import struct

import pytest

from bitchat.exceptions import (
    PacketDecodingError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FIXED_HEADER_SIZE,
    MINIMUM_PACKET_SIZE,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket


def test_decode_truncated_fixed_header() -> None:
    """Validate decoding byte buffer shorter than minimum 22 bytes raises PacketDecodingError."""
    truncated = b"\x01\x04\x05\x00\x00\x00"  # 6 bytes
    with pytest.raises(PacketDecodingError, match="too small"):
        decode_packet(truncated)


def test_decode_missing_sender_id() -> None:
    """Validate 14-byte header without 8-byte SenderID raises PacketDecodingError."""
    header = struct.pack(
        ">BBBQBH", CURRENT_PROTOCOL_VERSION, int(MessageType.Message), 5, 1000, 0, 0
    )
    assert len(header) == FIXED_HEADER_SIZE
    with pytest.raises(PacketDecodingError, match="too small"):
        decode_packet(header)


def test_decode_unsupported_protocol_version() -> None:
    """Validate unsupported protocol version (e.g. 2 or 0) raises UnsupportedProtocolVersionError."""
    sender = os.urandom(SENDER_ID_SIZE)
    # Version = 2
    raw = struct.pack(">BBBQBH", 2, int(MessageType.Message), 5, 1000, 0, 0) + sender
    with pytest.raises(UnsupportedProtocolVersionError):
        decode_packet(raw)

    # Version = 0
    raw_zero = (
        struct.pack(">BBBQBH", 0, int(MessageType.Message), 5, 1000, 0, 0) + sender
    )
    with pytest.raises(UnsupportedProtocolVersionError):
        decode_packet(raw_zero)


def test_decode_unknown_message_type() -> None:
    """Validate unassigned message type (e.g. 0xFF or 0x00) raises UnknownMessageTypeError."""
    sender = os.urandom(SENDER_ID_SIZE)
    raw = struct.pack(">BBBQBH", CURRENT_PROTOCOL_VERSION, 0xFF, 5, 1000, 0, 0) + sender
    with pytest.raises(UnknownMessageTypeError):
        decode_packet(raw)


def test_decode_truncated_payload() -> None:
    """Validate payload shorter than claimed PayloadLength raises PacketDecodingError."""
    sender = os.urandom(SENDER_ID_SIZE)
    claimed_length = 50
    actual_payload = b"short"
    raw = (
        struct.pack(
            ">BBBQBH",
            CURRENT_PROTOCOL_VERSION,
            int(MessageType.Message),
            5,
            1000,
            0,
            claimed_length,
        )
        + sender
        + actual_payload
    )

    with pytest.raises(PacketDecodingError):
        decode_packet(raw)


def test_decode_tampered_padding_delimiter() -> None:
    """Validate packet with inconsistent padding delimiter is rejected."""
    sender = os.urandom(SENDER_ID_SIZE)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=1000,
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=b"Sample payload for padding tampering",
        signature=None,
    )
    encoded = bytearray(encode_packet(packet, add_padding=True))
    # Corrupt last delimiter byte
    encoded[-1] ^= 0x55

    with pytest.raises(PacketDecodingError):
        decode_packet(bytes(encoded))


def test_empty_payload_boundary() -> None:
    """Validate 0-byte payload encodes and decodes properly."""
    sender = os.urandom(SENDER_ID_SIZE)
    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=3,
        timestamp=1000,
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=b"",
        signature=None,
    )
    encoded = encode_packet(packet, add_padding=False)
    assert len(encoded) == MINIMUM_PACKET_SIZE

    decoded = decode_packet(encoded)
    assert decoded.payload == b""
    assert decoded.sender_id == sender
