"""Protocol constants and MessageType enum matching the BitChat specification."""

from enum import IntEnum

# Protocol versions
CURRENT_PROTOCOL_VERSION: int = 1
MINIMUM_PROTOCOL_VERSION: int = 1
MAXIMUM_PROTOCOL_VERSION: int = 1

# BLE UUIDs
BITCHAT_SERVICE_UUID: str = "F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C"
BITCHAT_CHARACTERISTIC_UUID: str = "A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D"

# Packet header flags
FLAG_HAS_RECIPIENT: int = 0x01
FLAG_HAS_SIGNATURE: int = 0x02
FLAG_IS_COMPRESSED: int = 0x04

# Addressing and sizes
BROADCAST_RECIPIENT: bytes = b"\xff" * 8
SENDER_ID_SIZE: int = 8
RECIPIENT_ID_SIZE: int = 8
SIGNATURE_SIZE: int = 64
# Fixed header BEFORE SenderID:
# Version (1) + Type (1) + TTL (1) + Timestamp (8) + Flags (1) + PayloadLen (2)
# Total = 14 bytes
FIXED_HEADER_SIZE: int = 14
MINIMUM_PACKET_SIZE: int = FIXED_HEADER_SIZE + SENDER_ID_SIZE  # 22 bytes

# Padding parameters
BLOCK_SIZES: tuple[int, ...] = (256, 512, 1024, 2048)
PADDING_OVERHEAD_ESTIMATE: int = 16
MAX_PADDING_SIZE: int = 255

# Cover traffic prefix
COVER_TRAFFIC_PREFIX: str = "☂DUMMY☂"


class MessageType(IntEnum):
    """BitChat protocol message types."""

    Announce = 0x01
    KeyExchange = 0x02
    Leave = 0x03
    Message = 0x04
    FragmentStart = 0x05
    FragmentContinue = 0x06
    FragmentEnd = 0x07
    ChannelAnnounce = 0x08
    ChannelRetention = 0x09
    DeliveryAck = 0x0A
    DeliveryStatusRequest = 0x0B
    ReadReceipt = 0x0C
    NoiseHandshakeInit = 0x10
    NoiseHandshakeResp = 0x11
    NoiseEncrypted = 0x12
    NoiseIdentityAnnounce = 0x13
    VersionHello = 0x20
    VersionAck = 0x21
    ProtocolAck = 0x22
    ProtocolNack = 0x23
    SystemValidation = 0x24
    HandshakeRequest = 0x25
