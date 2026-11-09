"""BitChat binary packet decoder."""

import struct

from bitchat._native import HAS_NATIVE_CORE, _core, raise_mapped_error
from bitchat.exceptions import (
    InvalidPacketError,
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


def py_unpad_packet_data(data: bytes) -> bytes:
    """Pure-Python reference implementation of unpad_packet_data."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketDecodingError(f"Expected bytes-like object, got {type(data)}")
    if not data:
        return b""

    padding_length = data[-1]
    if (
        padding_length == 0
        or padding_length > len(data)
        or padding_length > MAX_PADDING_SIZE
    ):
        return bytes(data)

    return bytes(data[:-padding_length])


def unpad_packet_data(data: bytes) -> bytes:
    """Remove BitChat random block padding (PKCS#7-style length delimiter)."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketDecodingError(f"Expected bytes-like object, got {type(data)}")
    if HAS_NATIVE_CORE:
        return _core.unpad_packet_data(data if type(data) is bytes else bytes(data))
    return py_unpad_packet_data(data)


def py_decode_packet(data: bytes) -> BitchatPacket:
    """Pure-Python reference implementation of decode_packet."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketDecodingError(
            f"Packet data must be a bytes-like object, got {type(data)}"
        )

    if len(data) < MINIMUM_PACKET_SIZE:
        raise PacketDecodingError(
            f"Packet too small: {len(data)} bytes, "
            f"minimum required is {MINIMUM_PACKET_SIZE} bytes"
        )

    try:
        version, msg_type_raw, ttl, timestamp, flags, payload_len = struct.unpack(
            ">BBBQBH", data[:FIXED_HEADER_SIZE]
        )
    except struct.error as e:
        raise PacketDecodingError(
            f"Failed to unpack {FIXED_HEADER_SIZE}-byte packet header: {e}"
        ) from e

    if version != CURRENT_PROTOCOL_VERSION:
        raise UnsupportedProtocolVersionError(
            f"Unsupported protocol version: {version}. "
            f"Expected version {CURRENT_PROTOCOL_VERSION}."
        )

    try:
        message_type = MessageType(msg_type_raw)
    except ValueError as e:
        raise UnknownMessageTypeError(
            f"Unknown message type: 0x{msg_type_raw:02X} ({msg_type_raw})"
        ) from e

    has_recipient = bool(flags & FLAG_HAS_RECIPIENT)
    has_signature = bool(flags & FLAG_HAS_SIGNATURE)

    expected_unpadded_size = (
        FIXED_HEADER_SIZE
        + SENDER_ID_SIZE
        + (RECIPIENT_ID_SIZE if has_recipient else 0)
        + payload_len
        + (SIGNATURE_SIZE if has_signature else 0)
    )

    if len(data) < expected_unpadded_size:
        raise PacketDecodingError(
            f"Packet data shorter than expected: got {len(data)} bytes, "
            f"expected at least {expected_unpadded_size} bytes"
        )

    if len(data) == expected_unpadded_size:
        unpadded = bytes(data)
    else:
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
        unpadded = bytes(data[:expected_unpadded_size])

    offset = FIXED_HEADER_SIZE
    sender_id = unpadded[offset : offset + SENDER_ID_SIZE]
    offset += SENDER_ID_SIZE

    recipient_id: bytes | None = None
    if has_recipient:
        recipient_id = unpadded[offset : offset + RECIPIENT_ID_SIZE]
        offset += RECIPIENT_ID_SIZE

    payload = unpadded[offset : offset + payload_len]
    offset += payload_len

    signature: bytes | None = None
    if has_signature:
        signature = unpadded[offset : offset + SIGNATURE_SIZE]
        offset += SIGNATURE_SIZE

    try:
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
    except InvalidPacketError as e:
        raise PacketDecodingError(f"Decoded packet failed validation: {e}") from e


def decode_packet(data: bytes) -> BitchatPacket:
    """Decode raw binary data into a BitchatPacket with defensive validation."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketDecodingError(
            f"Packet data must be a bytes-like object, got {type(data)}"
        )
    if HAS_NATIVE_CORE:
        raw = data if type(data) is bytes else bytes(data)
        try:
            (
                version,
                msg_type_raw,
                ttl,
                timestamp,
                flags,
                sender_id,
                recipient_id,
                payload,
                signature,
            ) = _core.decode_packet_raw(raw)
            return BitchatPacket._from_trusted(
                version=version,
                message_type=MessageType(msg_type_raw),
                ttl=ttl,
                timestamp=timestamp,
                flags=flags,
                sender_id=sender_id,
                recipient_id=recipient_id,
                payload=payload,
                signature=signature,
            )
        except ValueError as exc:
            raise_mapped_error(exc)
    return py_decode_packet(data)
