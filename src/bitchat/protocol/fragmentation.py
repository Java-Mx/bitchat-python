"""BitChat protocol packet fragmentation."""

from __future__ import annotations

import os
import struct
import time

from bitchat.exceptions import (
    FragmentLimitExceededError,
    FragmentPayloadError,
    InvalidFragmentError,
    PacketEncodingError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FRAGMENT_CHUNK_SIZE,
    FRAGMENT_HEADER_SIZE,
    FRAGMENT_ID_SIZE,
    FRAGMENTATION_THRESHOLD,
    MAX_FRAGMENTS_PER_ASSEMBLY,
    SENDER_ID_SIZE,
    MessageType,
)
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.packet import BitchatPacket


def should_fragment(packet_or_bytes: BitchatPacket | bytes) -> bool:
    """Return True if encoded packet wire size strictly exceeds 500 bytes."""
    if isinstance(packet_or_bytes, BitchatPacket):
        data = encode_packet(packet_or_bytes)
    elif isinstance(packet_or_bytes, (bytes, bytearray)):
        data = bytes(packet_or_bytes)
    else:
        raise TypeError(
            f"Expected BitchatPacket or bytes, got {type(packet_or_bytes).__name__}"
        )
    return len(data) > FRAGMENTATION_THRESHOLD


def generate_fragment_id() -> bytes:
    """Generate an 8-byte random fragment ID."""
    return os.urandom(FRAGMENT_ID_SIZE)


def split_chunks(data: bytes, chunk_size: int = FRAGMENT_CHUNK_SIZE) -> list[bytes]:
    """Split data into chunks of chunk_size."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"Expected bytes, got {type(data).__name__}")
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")

    data_bytes = bytes(data)
    if not data_bytes:
        return []

    chunks = [
        data_bytes[i : i + chunk_size] for i in range(0, len(data_bytes), chunk_size)
    ]
    if len(chunks) > 0xFFFF:
        raise FragmentLimitExceededError(
            f"Data requires {len(chunks)} chunks, exceeding 16-bit total limit"
        )
    if len(chunks) > MAX_FRAGMENTS_PER_ASSEMBLY:
        msg = (
            f"Data requires {len(chunks)} chunks, "
            f"exceeding max {MAX_FRAGMENTS_PER_ASSEMBLY}"
        )
        raise FragmentLimitExceededError(msg)
    return chunks


def create_fragment_payload(
    fragment_id: bytes,
    index: int,
    total: int,
    original_message_type: int | MessageType,
    chunk_data: bytes,
) -> bytes:
    """Create a 13-byte fragment metadata header and append chunk data."""
    if not isinstance(fragment_id, (bytes, bytearray)):
        raise InvalidFragmentError("fragment_id must be bytes")
    if len(fragment_id) != FRAGMENT_ID_SIZE:
        raise InvalidFragmentError(
            f"fragment_id must be {FRAGMENT_ID_SIZE} bytes, got {len(fragment_id)}"
        )
    if not isinstance(index, int) or isinstance(index, bool):
        raise InvalidFragmentError("index must be an integer")
    if not isinstance(total, int) or isinstance(total, bool):
        raise InvalidFragmentError("total must be an integer")
    if total <= 0:
        raise InvalidFragmentError(f"total must be > 0, got {total}")
    if total > 0xFFFF:
        raise FragmentLimitExceededError(f"total exceeds 0xFFFF: {total}")
    if total > MAX_FRAGMENTS_PER_ASSEMBLY:
        raise FragmentLimitExceededError(
            f"total exceeds limit {MAX_FRAGMENTS_PER_ASSEMBLY}: {total}"
        )
    if not (0 <= index < total):
        raise InvalidFragmentError(f"index out of bounds: index={index}, total={total}")

    orig_type_int = int(original_message_type)
    if not (0 <= orig_type_int <= 255):
        raise InvalidFragmentError(
            f"original_message_type out of range (0..255): {orig_type_int}"
        )

    if not isinstance(chunk_data, (bytes, bytearray)):
        raise InvalidFragmentError("chunk_data must be bytes")

    try:
        header = struct.pack(">8sHHB", bytes(fragment_id), index, total, orig_type_int)
    except struct.error as exc:
        raise InvalidFragmentError(f"Failed to pack fragment header: {exc}") from exc

    return header + bytes(chunk_data)


def parse_fragment_payload(payload: bytes) -> tuple[bytes, int, int, int, bytes]:
    """Parse 13-byte fragment header returning (id, index, total, orig_type, data)."""
    if not isinstance(payload, (bytes, bytearray)):
        raise FragmentPayloadError(f"Expected bytes, got {type(payload).__name__}")
    if len(payload) < FRAGMENT_HEADER_SIZE:
        msg = (
            f"Fragment payload too short: {len(payload)} bytes, "
            f"need at least {FRAGMENT_HEADER_SIZE}"
        )
        raise FragmentPayloadError(msg)

    try:
        fragment_id, index, total, orig_type = struct.unpack(
            ">8sHHB", payload[:FRAGMENT_HEADER_SIZE]
        )
    except struct.error as exc:
        raise FragmentPayloadError(f"Malformed fragment header: {exc}") from exc

    if total <= 0:
        raise InvalidFragmentError(f"Invalid fragment total: {total}")
    if not (0 <= index < total):
        raise InvalidFragmentError(
            f"Invalid fragment index: index={index}, total={total}"
        )
    if total > MAX_FRAGMENTS_PER_ASSEMBLY:
        raise FragmentLimitExceededError(
            f"Fragment total {total} exceeds maximum limit {MAX_FRAGMENTS_PER_ASSEMBLY}"
        )

    return fragment_id, index, total, orig_type, bytes(payload[FRAGMENT_HEADER_SIZE:])


def fragment_encoded_packet(
    encoded_packet: bytes,
    sender_id: bytes,
    original_message_type: int | MessageType,
    fragment_id: bytes | None = None,
    ttl: int = 7,
    timestamp: int | None = None,
) -> list[BitchatPacket]:
    """Split an encoded packet into ordered fragment packets."""
    if not isinstance(encoded_packet, (bytes, bytearray)):
        raise PacketEncodingError("encoded_packet must be bytes")
    encoded_bytes = bytes(encoded_packet)

    if not should_fragment(encoded_bytes):
        return []

    if (
        not isinstance(sender_id, (bytes, bytearray))
        or len(sender_id) != SENDER_ID_SIZE
    ):
        raise PacketEncodingError(f"sender_id must be {SENDER_ID_SIZE} bytes")

    frag_id = generate_fragment_id() if fragment_id is None else bytes(fragment_id)
    if len(frag_id) != FRAGMENT_ID_SIZE:
        raise InvalidFragmentError(f"fragment_id must be {FRAGMENT_ID_SIZE} bytes")

    chunks = split_chunks(encoded_bytes, FRAGMENT_CHUNK_SIZE)
    total = len(chunks)
    ts = int(time.time() * 1000) if timestamp is None else timestamp
    orig_type_int = int(original_message_type)

    fragments: list[BitchatPacket] = []
    for index, chunk in enumerate(chunks):
        if index == 0:
            frag_type = MessageType.FragmentStart
        elif index == total - 1:
            frag_type = MessageType.FragmentEnd
        else:
            frag_type = MessageType.FragmentContinue

        payload = create_fragment_payload(frag_id, index, total, orig_type_int, chunk)
        frag_packet = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=frag_type,
            ttl=ttl,
            timestamp=ts,
            flags=0,
            sender_id=bytes(sender_id),
            recipient_id=None,
            payload=payload,
            signature=None,
        )
        fragments.append(frag_packet)

    return fragments


def fragment_packet(
    packet: BitchatPacket, fragment_id: bytes | None = None
) -> list[BitchatPacket]:
    """Fragment a BitchatPacket if its encoded size strictly exceeds 500 bytes."""
    if not isinstance(packet, BitchatPacket):
        raise PacketEncodingError(
            f"Expected BitchatPacket, got {type(packet).__name__}"
        )
    encoded = encode_packet(packet)
    if not should_fragment(encoded):
        return []
    return fragment_encoded_packet(
        encoded_packet=encoded,
        sender_id=packet.sender_id,
        original_message_type=packet.message_type,
        fragment_id=fragment_id,
        ttl=packet.ttl,
        timestamp=packet.timestamp,
    )


def encode_fragment_packets(fragments: list[BitchatPacket]) -> list[bytes]:
    """Encode a list of fragment packets to padded wire bytes."""
    return [encode_packet(f) for f in fragments]
