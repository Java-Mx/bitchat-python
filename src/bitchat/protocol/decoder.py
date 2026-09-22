"""BitChat binary packet decoder."""

import struct

from bitchat.exceptions import (
    PacketDecodingError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FIXED_HEADER_SIZE,
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    MAX_PADDING_SIZE,
    MINIMUM_PACKET_SIZE,
    RECIPIENT_ID_SIZE,
    SENDER_ID_SIZE,
    SIGNATURE_SIZE,
    MessageType,
)
from bitchat.protocol.packet import BitchatPacket


def unpad_packet_data(data: bytes) -> bytes:
    """Remove BitChat PKCS#7-style padding from a binary byte buffer.

    The final byte indicates the count of padding bytes to remove (1..255).
    If padding length is 0, exceeds data length, or exceeds 255, returns data unchanged.
    """
    if not data:
        return data

    padding_length = data[-1]
    if (
        padding_length == 0
        or padding_length > len(data)
        or padding_length > MAX_PADDING_SIZE
    ):
        return data

    return data[:-padding_length]


def decode_packet(data: bytes) -> BitchatPacket:
    """Decode raw binary data into a typed BitchatPacket.

    Validation steps:
    1. Validates minimum wire length (22 bytes: 14 header + 8 sender ID).
    2. Parses the 14-byte fixed header BEFORE SenderID.
    3. Validates protocol version equals CURRENT_PROTOCOL_VERSION (1).
    4. Validates message type against known MessageType enum.
    5. Computes exact expected unpadded packet length based on header flags.
    6. Validates and removes trailing block padding if present.
    7. Extracts SenderID, optional RecipientID, Payload, and optional Signature.
    8. Returns the validated, immutable BitchatPacket instance.

    Raises:
        PacketDecodingError: If data is truncated, malformed, or has invalid padding.
        UnsupportedProtocolVersionError: If protocol version is unsupported.
        UnknownMessageTypeError: If message type is unrecognized.
    """
    if len(data) < MINIMUM_PACKET_SIZE:
        raise PacketDecodingError(
            f"Packet too small: {len(data)} bytes, "
            f"minimum required is {MINIMUM_PACKET_SIZE} bytes"
        )

    # 1. Parse fixed 14-byte header BEFORE SenderID:
    try:
        version, msg_type_raw, ttl, timestamp, flags, payload_len = struct.unpack(
            ">BBBQBH", data[:FIXED_HEADER_SIZE]
        )
    except struct.error as e:
        raise PacketDecodingError(
            f"Failed to unpack {FIXED_HEADER_SIZE}-byte packet header: {e}"
        ) from e

    # 2. Validate protocol version
    if version != CURRENT_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersionError(
            f"Unsupported protocol version: {version}. "
            f"Expected version {CURRENT_PROTOCOL_VERSION}."
        )

    # 3. Validate message type
    try:
        message_type = MessageType(msg_type_raw)
    except ValueError as e:
        raise UnknownMessageTypeError(
            f"Unknown message type: 0x{msg_type_raw:02X} ({msg_type_raw})"
        ) from e

    # 4. Check header flags
    has_recipient = bool(flags & FLAG_HAS_RECIPIENT)
    has_signature = bool(flags & FLAG_HAS_SIGNATURE)

    # 5. Compute exact expected unpadded size
    expected_unpadded_size = (
        FIXED_HEADER_SIZE
        + SENDER_ID_SIZE
        + (RECIPIENT_ID_SIZE if has_recipient else 0)
        + payload_len
        + (SIGNATURE_SIZE if has_signature else 0)
    )

    # 6. Validate wire length and handle padding
    if len(data) < expected_unpadded_size:
        raise PacketDecodingError(
            f"Packet data shorter than expected: got {len(data)} bytes, "
            f"expected at least {expected_unpadded_size} bytes"
        )

    if len(data) == expected_unpadded_size:
        # Unpadded packet
        unpadded = data
    else:
        # Padded packet: validate trailing padding
        padding_needed = len(data) - expected_unpadded_size
        last_byte = data[-1]
        if (
            padding_needed > MAX_PADDING_SIZE
            or last_byte != padding_needed
            or last_byte == 0
        ):
            raise PacketDecodingError(
                f"Malformed packet padding: packet has {padding_needed} extra bytes, "
                f"but final padding byte indicates {last_byte}"
            )
        unpadded = data[:expected_unpadded_size]

    # 7. Extract variable fields
    offset = FIXED_HEADER_SIZE

    # Sender ID (8 bytes)
    sender_id = unpadded[offset : offset + SENDER_ID_SIZE]
    offset += SENDER_ID_SIZE

    # Recipient ID (8 bytes if present)
    recipient_id: bytes | None = None
    if has_recipient:
        recipient_id = unpadded[offset : offset + RECIPIENT_ID_SIZE]
        offset += RECIPIENT_ID_SIZE

    # Payload (payload_len bytes)
    payload = unpadded[offset : offset + payload_len]
    offset += payload_len

    # Signature (64 bytes if present)
    signature: bytes | None = None
    if has_signature:
        signature = unpadded[offset : offset + SIGNATURE_SIZE]
        offset += SIGNATURE_SIZE

    # 8. Return constructed packet
    return BitchatPacket(
        version=version,
        message_type=message_type,
        ttl=ttl,
        timestamp=timestamp,
        flags=flags,
        sender_id=sender_id,
        recipient_id=recipient_id,
        payload=payload,
        signature=signature,
    )
