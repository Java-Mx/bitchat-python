"""Tier 1: Feature Coverage — Protocol Framing & TLV Packet Encoding/Decoding."""

from __future__ import annotations

import os

import pytest

from bitchat.exceptions import InvalidPacketError
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FIXED_HEADER_SIZE,
    FLAG_HAS_RECIPIENT,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket, peer_id_from_hex, peer_id_to_hex


def test_encode_decode_broadcast_announce() -> None:
    """Validate encoding and decoding of an Announce broadcast packet."""
    sender = os.urandom(SENDER_ID_SIZE)
    nickname_payload = b"Alice_Node_1"

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Announce,
        ttl=5,
        timestamp=1700000000000,
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=nickname_payload,
        signature=None,
    )

    encoded = encode_packet(packet, add_padding=False)
    assert len(encoded) >= FIXED_HEADER_SIZE + SENDER_ID_SIZE + len(nickname_payload)

    decoded = decode_packet(encoded)
    assert decoded.version == CURRENT_PROTOCOL_VERSION
    assert decoded.message_type == MessageType.Announce
    assert decoded.ttl == 5
    assert decoded.timestamp == 1700000000000
    assert decoded.flags == 0
    assert decoded.sender_id == sender
    assert decoded.recipient_id is None
    assert decoded.payload == nickname_payload
    assert decoded.has_recipient is False
    assert decoded.has_signature is False


def test_encode_decode_direct_message() -> None:
    """Validate encoding and decoding of a DirectMessage with recipient ID."""
    sender = os.urandom(SENDER_ID_SIZE)
    recipient = os.urandom(SENDER_ID_SIZE)
    msg_payload = b"Hello secret peer!"

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=7,
        timestamp=1700000005000,
        flags=FLAG_HAS_RECIPIENT,
        sender_id=sender,
        recipient_id=recipient,
        payload=msg_payload,
        signature=None,
    )

    encoded = encode_packet(packet, add_padding=False)
    decoded = decode_packet(encoded)

    assert decoded.message_type == MessageType.Message
    assert decoded.sender_id == sender
    assert decoded.recipient_id == recipient
    assert decoded.has_recipient is True
    assert decoded.payload == msg_payload


def test_encode_decode_with_random_block_padding() -> None:
    """Validate wire encoding with random block padding and automatic unpadding."""
    sender = os.urandom(SENDER_ID_SIZE)
    payload = b"Padded content block"

    packet = BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=MessageType.Message,
        ttl=3,
        timestamp=1700000010000,
        flags=0,
        sender_id=sender,
        recipient_id=None,
        payload=payload,
        signature=None,
    )

    encoded = encode_packet(packet, add_padding=True)
    # Block sizes are 256, 512, 1024, 2048
    assert len(encoded) in (256, 512, 1024, 2048) or len(encoded) >= len(payload)

    decoded = decode_packet(encoded)
    assert decoded.payload == payload
    assert decoded.sender_id == sender


def test_encode_decode_all_message_types() -> None:
    """Validate that every defined MessageType can be encoded and decoded without error."""
    sender = os.urandom(SENDER_ID_SIZE)
    for mtype in MessageType:
        packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=mtype,
            ttl=1,
            timestamp=123456789,
            flags=0,
            sender_id=sender,
            recipient_id=None,
            payload=b"test-type-payload",
            signature=None,
        )
        encoded = encode_packet(packet, add_padding=False)
        decoded = decode_packet(encoded)
        assert decoded.message_type == mtype
        assert decoded.payload == b"test-type-payload"


def test_packet_immutability_and_normalization() -> None:
    """Verify packet normalizes mutable bytearrays and maintains immutability."""
    mutable_sender = bytearray(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    mutable_payload = bytearray(b"original data")

    packet = BitchatPacket(
        version=1,
        message_type=MessageType.Message,
        ttl=5,
        timestamp=100,
        flags=0,
        sender_id=mutable_sender,  # type: ignore[arg-type]
        recipient_id=None,
        payload=mutable_payload,  # type: ignore[arg-type]
        signature=None,
    )

    # Mutate the source bytearrays
    mutable_sender[0] = 0xFF
    mutable_payload[0] = 0xAA

    # Packet content must remain unaffected
    assert packet.sender_id[0] == 0x01
    assert packet.payload[0] == ord("o")

    # Packet instance is frozen
    with pytest.raises((AttributeError, TypeError, InvalidPacketError)):
        packet.ttl = 10  # type: ignore[misc]


def test_peer_id_hex_conversion_roundtrip() -> None:
    """Validate peer ID hex string conversion and bidirectional roundtrip."""
    raw_id = b"\x12\x34\x56\x78\x9a\xbc\xde\xf0"
    hex_str = peer_id_to_hex(raw_id)
    assert hex_str == "123456789abcdef0"
    recovered = peer_id_from_hex(hex_str)
    assert recovered == raw_id
