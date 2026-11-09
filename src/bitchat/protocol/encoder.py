"""BitChat binary packet encoder."""

import os
import struct

from bitchat._native import HAS_NATIVE_CORE, _core, raise_mapped_error
from bitchat.exceptions import PacketEncodingError
from bitchat.protocol.constants import (
    BLOCK_SIZES,
    MAX_PADDING_SIZE,
    PADDING_OVERHEAD_ESTIMATE,
    RECIPIENT_ID_SIZE,
    SIGNATURE_SIZE,
)
from bitchat.protocol.packet import BitchatPacket


def py_get_optimal_block_size(unpadded_size: int) -> int:
    """Pure-Python reference implementation of get_optimal_block_size."""
    total_size = unpadded_size + PADDING_OVERHEAD_ESTIMATE
    for block_size in BLOCK_SIZES:
        if total_size <= block_size:
            return block_size
    return unpadded_size


def get_optimal_block_size(unpadded_size: int) -> int:
    """Find the smallest block size in BLOCK_SIZES that fits data plus overhead.

    Accounts for 16 bytes of encryption overhead. For messages larger than
    2048 - 16 bytes, returns unpadded_size (no padding applied).
    """
    if HAS_NATIVE_CORE and unpadded_size >= 0:
        return _core.get_optimal_block_size(unpadded_size)
    return py_get_optimal_block_size(unpadded_size)


def py_pad_packet_data(data: bytes, target_size: int | None = None) -> bytes:
    """Pure-Python reference implementation of pad_packet_data."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketEncodingError(f"Expected bytes-like object, got {type(data)}")
    data_bytes = bytes(data)

    if target_size is None:
        target_size = py_get_optimal_block_size(len(data_bytes))

    if len(data_bytes) >= target_size:
        return data_bytes

    padding_needed = target_size - len(data_bytes)
    if padding_needed > MAX_PADDING_SIZE:
        return data_bytes

    random_bytes = os.urandom(padding_needed - 1)
    return data_bytes + random_bytes + bytes([padding_needed])


def pad_packet_data(data: bytes, target_size: int | None = None) -> bytes:
    """Apply BitChat random block padding (PKCS#7-style length delimiter)."""
    if not isinstance(data, (bytes, bytearray)):
        raise PacketEncodingError(f"Expected bytes-like object, got {type(data)}")
    data_bytes = data if type(data) is bytes else bytes(data)

    if target_size is None:
        target_size = get_optimal_block_size(len(data_bytes))

    if target_size <= 0 or len(data_bytes) >= target_size:
        return data_bytes

    if HAS_NATIVE_CORE:
        return _core.pad_packet_data(data_bytes, target_size)
    return py_pad_packet_data(data_bytes, target_size)


def py_encode_packet(packet: BitchatPacket, add_padding: bool = True) -> bytes:
    """Pure-Python reference implementation of encode_packet."""
    if not isinstance(packet, BitchatPacket):
        raise PacketEncodingError(
            f"Expected BitchatPacket instance, got {type(packet)}"
        )

    try:
        header = struct.pack(
            ">BBBQBH",
            packet.version,
            int(packet.message_type),
            packet.ttl,
            packet.timestamp,
            packet.flags,
            len(packet.payload),
        )
    except struct.error as e:
        raise PacketEncodingError(f"Failed to serialize packet header: {e}") from e

    parts = [header, packet.sender_id]

    if packet.has_recipient:
        if packet.recipient_id is None or len(packet.recipient_id) != RECIPIENT_ID_SIZE:
            raise PacketEncodingError(
                "FLAG_HAS_RECIPIENT is set but recipient_id is invalid or missing"
            )
        parts.append(packet.recipient_id)

    parts.append(packet.payload)

    if packet.has_signature:
        if packet.signature is None or len(packet.signature) != SIGNATURE_SIZE:
            raise PacketEncodingError(
                "FLAG_HAS_SIGNATURE is set but signature is invalid or missing"
            )
        parts.append(packet.signature)

    raw_unpadded = b"".join(parts)

    if add_padding:
        return py_pad_packet_data(raw_unpadded)
    return raw_unpadded


def encode_packet(packet: BitchatPacket, add_padding: bool = True) -> bytes:
    """Encode a BitchatPacket into its wire binary representation."""
    if not isinstance(packet, BitchatPacket):
        raise PacketEncodingError(
            f"Expected BitchatPacket instance, got {type(packet)}"
        )
    if HAS_NATIVE_CORE:
        try:
            return _core.encode_packet_raw(
                packet.version,
                int(packet.message_type),
                packet.ttl,
                packet.timestamp,
                packet.flags,
                packet.sender_id,
                packet.recipient_id,
                packet.payload,
                packet.signature,
                add_padding,
            )
        except ValueError as exc:
            raise_mapped_error(exc)
    return py_encode_packet(packet, add_padding=add_padding)
