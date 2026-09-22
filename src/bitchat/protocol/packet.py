"""BitChat binary packet representation."""

import time
from dataclasses import dataclass

from bitchat.exceptions import InvalidPacketError
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    FLAG_IS_COMPRESSED,
    RECIPIENT_ID_SIZE,
    SENDER_ID_SIZE,
    SIGNATURE_SIZE,
    MessageType,
)


def peer_id_to_hex(peer_id: bytes) -> str:
    """Convert an 8-byte binary peer ID to a 16-character hexadecimal string."""
    if len(peer_id) != SENDER_ID_SIZE:
        raise InvalidPacketError(
            f"Peer ID must be exactly {SENDER_ID_SIZE} bytes, got {len(peer_id)}"
        )
    return peer_id.hex()


def peer_id_from_hex(hex_str: str) -> bytes:
    """Convert a 16-character hexadecimal string to an 8-byte binary peer ID."""
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError as e:
        raise InvalidPacketError(f"Invalid hexadecimal peer ID '{hex_str}': {e}") from e
    if len(raw) != SENDER_ID_SIZE:
        raise InvalidPacketError(
            f"Hexadecimal peer ID must represent {SENDER_ID_SIZE} bytes "
            f"(16 hex chars), got {len(raw)}"
        )
    return raw


@dataclass(frozen=True)
class BitchatPacket:
    """Typed immutable BitChat wire packet representation.

    All multi-byte integer fields are logically represented as native integers;
    wire serialization is handled by encoder and decoder.
    """

    version: int
    message_type: MessageType
    ttl: int
    timestamp: int
    flags: int
    sender_id: bytes
    recipient_id: bytes | None
    payload: bytes
    signature: bytes | None

    def __post_init__(self) -> None:
        """Validate packet field constraints."""
        if not (0 <= self.version <= 255):
            raise InvalidPacketError(
                f"Version must be an 8-bit unsigned integer, got {self.version}"
            )

        if not isinstance(self.message_type, MessageType):
            raise InvalidPacketError(f"Invalid message type: {self.message_type!r}")

        if not (0 <= self.ttl <= 255):
            raise InvalidPacketError(
                f"TTL must be an 8-bit unsigned integer (0..255), got {self.ttl}"
            )

        if not (0 <= self.timestamp <= 0xFFFFFFFFFFFFFFFF):
            raise InvalidPacketError(
                f"Timestamp must be an unsigned 64-bit integer, got {self.timestamp}"
            )

        if not (0 <= self.flags <= 255):
            raise InvalidPacketError(
                f"Flags must be an 8-bit unsigned integer (0..255), got {self.flags}"
            )

        if (
            not isinstance(self.sender_id, (bytes, bytearray))
            or len(self.sender_id) != SENDER_ID_SIZE
        ):
            length = (
                len(self.sender_id)
                if isinstance(self.sender_id, (bytes, bytearray))
                else type(self.sender_id)
            )
            raise InvalidPacketError(
                f"Sender ID must be exactly {SENDER_ID_SIZE} bytes, got {length}"
            )

        if self.recipient_id is not None:
            if (
                not isinstance(self.recipient_id, (bytes, bytearray))
                or len(self.recipient_id) != RECIPIENT_ID_SIZE
            ):
                length = (
                    len(self.recipient_id)
                    if isinstance(self.recipient_id, (bytes, bytearray))
                    else type(self.recipient_id)
                )
                raise InvalidPacketError(
                    f"Recipient ID must be exactly {RECIPIENT_ID_SIZE} bytes "
                    f"when present, got {length}"
                )
            if not (self.flags & FLAG_HAS_RECIPIENT):
                raise InvalidPacketError(
                    "FLAG_HAS_RECIPIENT must be set when recipient_id is present"
                )
        else:
            if self.flags & FLAG_HAS_RECIPIENT:
                raise InvalidPacketError(
                    "FLAG_HAS_RECIPIENT must not be set when recipient_id is None"
                )

        if not isinstance(self.payload, (bytes, bytearray)):
            raise InvalidPacketError(f"Payload must be bytes, got {type(self.payload)}")

        if len(self.payload) > 65535:
            raise InvalidPacketError(
                f"Payload length exceeds maximum 16-bit uint (65535), "
                f"got {len(self.payload)}"
            )

        if self.signature is not None:
            if (
                not isinstance(self.signature, (bytes, bytearray))
                or len(self.signature) != SIGNATURE_SIZE
            ):
                length = (
                    len(self.signature)
                    if isinstance(self.signature, (bytes, bytearray))
                    else type(self.signature)
                )
                raise InvalidPacketError(
                    f"Signature must be exactly {SIGNATURE_SIZE} bytes "
                    f"when present, got {length}"
                )
            if not (self.flags & FLAG_HAS_SIGNATURE):
                raise InvalidPacketError(
                    "FLAG_HAS_SIGNATURE must be set when signature is present"
                )
        else:
            if self.flags & FLAG_HAS_SIGNATURE:
                raise InvalidPacketError(
                    "FLAG_HAS_SIGNATURE must not be set when signature is None"
                )

    @property
    def has_recipient(self) -> bool:
        """Return True if the packet carries a recipient ID."""
        return bool(self.flags & FLAG_HAS_RECIPIENT)

    @property
    def has_signature(self) -> bool:
        """Return True if the packet carries an Ed25519 signature."""
        return bool(self.flags & FLAG_HAS_SIGNATURE)

    @property
    def is_compressed(self) -> bool:
        """Return True if the packet payload is compressed."""
        return bool(self.flags & FLAG_IS_COMPRESSED)

    @property
    def sender_id_hex(self) -> str:
        """Return sender ID as a 16-character hexadecimal string."""
        return self.sender_id.hex()

    @property
    def recipient_id_hex(self) -> str | None:
        """Return recipient ID as a hexadecimal string, or None if no recipient."""
        return self.recipient_id.hex() if self.recipient_id is not None else None

    @classmethod
    def create(
        cls,
        message_type: MessageType,
        sender_id: bytes,
        payload: bytes = b"",
        recipient_id: bytes | None = None,
        signature: bytes | None = None,
        ttl: int = 7,
        timestamp: int | None = None,
        version: int = CURRENT_PROTOCOL_VERSION,
        is_compressed: bool = False,
    ) -> "BitchatPacket":
        """Convenience factory creating a validated packet with computed flags."""
        if timestamp is None:
            timestamp = int(time.time() * 1000)

        flags = 0
        if recipient_id is not None:
            flags |= FLAG_HAS_RECIPIENT
        if signature is not None:
            flags |= FLAG_HAS_SIGNATURE
        if is_compressed:
            flags |= FLAG_IS_COMPRESSED

        return cls(
            version=version,
            message_type=message_type,
            ttl=ttl,
            timestamp=timestamp,
            flags=flags,
            sender_id=bytes(sender_id),
            recipient_id=bytes(recipient_id) if recipient_id is not None else None,
            payload=bytes(payload),
            signature=bytes(signature) if signature is not None else None,
        )
