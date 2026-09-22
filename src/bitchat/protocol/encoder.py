"""BitChat binary packet encoder."""

import os
import struct

from bitchat.exceptions import PacketEncodingError
from bitchat.protocol.constants import (
    BLOCK_SIZES,
    MAX_PADDING_SIZE,
    PADDING_OVERHEAD_ESTIMATE,
    RECIPIENT_ID_SIZE,
    SIGNATURE_SIZE,
)
from bitchat.protocol.packet import BitchatPacket


def get_optimal_block_size(unpadded_size: int) -> int:
    """Find the smallest block size in BLOCK_SIZES that fits data plus overhead.

    Accounts for 16 bytes of encryption overhead. For messages larger than
    2048 - 16 bytes, returns unpadded_size (no padding applied).
    """
    total_size = unpadded_size + PADDING_OVERHEAD_ESTIMATE
    for block_size in BLOCK_SIZES:
        if total_size <= block_size:
            return block_size
    return unpadded_size


def pad_packet_data(data: bytes, target_size: int | None = None) -> bytes:
    """Apply BitChat PKCS#7-style padding to reach target block size.

    Structure: [data][(padding_needed - 1) random bytes][padding_needed byte]
    If data.len() >= target_size, returns data unchanged.
    If padding_needed > 255, returns data unchanged (PKCS#7 u8 limit).
    """
    if target_size is None:
        target_size = get_optimal_block_size(len(data))

    if len(data) >= target_size:
        return data

    padding_needed = target_size - len(data)
    if padding_needed > MAX_PADDING_SIZE:
        return data

    random_bytes = os.urandom(padding_needed - 1)
    return data + random_bytes + bytes([padding_needed])


def encode_packet(packet: BitchatPacket, add_padding: bool = True) -> bytes:
    """Encode a BitchatPacket into its wire binary representation.

    Exact wire layout:
    - Version: 1 byte (u8)
    - MessageType: 1 byte (u8)
    - TTL: 1 byte (u8)
    - Timestamp: 8 bytes (big-endian u64)
    - Flags: 1 byte (u8)
    - PayloadLength: 2 bytes (big-endian u16)
    - SenderID: 8 bytes
    - RecipientID: 8 bytes (only if has_recipient is True)
    - Payload: PayloadLength bytes
    - Signature: 64 bytes (only if has_signature is True)
    - Padding: variable (if add_padding=True)
    """
    try:
        # Fixed 14-byte header BEFORE SenderID:
        header = struct.pack(
            ">BBBQBH",
            packet.version,
            int(packet.message_type),
            packet.ttl,
            packet.timestamp,
            packet.flags,
            len(packet.payload),
        )

        parts = [header, packet.sender_id]

        if packet.has_recipient:
            if (
                packet.recipient_id is None
                or len(packet.recipient_id) != RECIPIENT_ID_SIZE
            ):
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
            return pad_packet_data(raw_unpadded)
        return raw_unpadded

    except struct.error as e:
        raise PacketEncodingError(f"Failed to serialize packet header: {e}") from e
    except PacketEncodingError:
        raise
    except Exception as e:
        raise PacketEncodingError(f"Unexpected error while encoding packet: {e}") from e
