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
    if not isinstance(peer_id, (bytes, bytearray)):
        raise InvalidPacketError(
            f"Peer ID must be a bytes-like object, got {type(peer_id)}"
        )
    if len(peer_id) != SENDER_ID_SIZE:
        raise InvalidPacketError(
            f"Peer ID must be exactly {SENDER_ID_SIZE} bytes, got {len(peer_id)}"
        )
    return bytes(peer_id).hex()


def peer_id_from_hex(hex_str: str) -> bytes:
    """Convert a 16-character hexadecimal string to an 8-byte binary peer ID."""
    if not isinstance(hex_str, str):
        raise InvalidPacketError(
            f"Hexadecimal peer ID must be a str, got {type(hex_str)}"
        )
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

    All binary fields (sender_id, recipient_id, payload, signature) are normalized
    to immutable bytes upon construction. Mutable bytearrays passed into the constructor
    are safely converted to independent immutable bytes.
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
        """Validate packet field constraints and normalize byte fields."""
        if type(self.version) is not int or not (0 <= self.version <= 255):
            raise InvalidPacketError(
                f"Version must be an 8-bit unsigned integer, got {self.version!r}"
            )

        if not isinstance(self.message_type, MessageType):
            raise InvalidPacketError(f"Invalid message type: {self.message_type!r}")

        if type(self.ttl) is not int or not (0 <= self.ttl <= 255):
            raise InvalidPacketError(
                f"TTL must be an 8-bit unsigned integer (0..255), got {self.ttl!r}"
            )

        if type(self.timestamp) is not int or not (
            0 <= self.timestamp <= 0xFFFFFFFFFFFFFFFF
        ):
            raise InvalidPacketError(
                f"Timestamp must be an unsigned 64-bit integer, got {self.timestamp!r}"
            )

        if type(self.flags) is not int or not (0 <= self.flags <= 255):
            raise InvalidPacketError(
                f"Flags must be an 8-bit unsigned integer (0..255), got {self.flags!r}"
            )

        # 1. Normalize and validate sender_id to immutable bytes
        if not isinstance(self.sender_id, (bytes, bytearray)):
            raise InvalidPacketError(
                f"Sender ID must be bytes, got {type(self.sender_id)}"
            )
        normalized_sender = bytes(self.sender_id)
        if len(normalized_sender) != SENDER_ID_SIZE:
            raise InvalidPacketError(
                f"Sender ID must be exactly {SENDER_ID_SIZE} bytes, "
                f"got {len(normalized_sender)}"
            )
        object.__setattr__(self, "sender_id", normalized_sender)

        # 2. Normalize and validate recipient_id to immutable bytes or None
        if self.recipient_id is not None:
            if not isinstance(self.recipient_id, (bytes, bytearray)):
                raise InvalidPacketError(
                    f"Recipient ID must be bytes when present, "
                    f"got {type(self.recipient_id)}"
                )
            normalized_recipient = bytes(self.recipient_id)
            if len(normalized_recipient) != RECIPIENT_ID_SIZE:
                raise InvalidPacketError(
                    f"Recipient ID must be exactly {RECIPIENT_ID_SIZE} bytes "
                    f"when present, got {len(normalized_recipient)}"
                )
            object.__setattr__(self, "recipient_id", normalized_recipient)
            if not (self.flags & FLAG_HAS_RECIPIENT):
                raise InvalidPacketError(
                    "FLAG_HAS_RECIPIENT must be set when recipient_id is present"
                )
        else:
            if self.flags & FLAG_HAS_RECIPIENT:
                raise InvalidPacketError(
                    "FLAG_HAS_RECIPIENT must not be set when recipient_id is None"
                )

        # 3. Normalize and validate payload to immutable bytes
        if not isinstance(self.payload, (bytes, bytearray)):
            raise InvalidPacketError(f"Payload must be bytes, got {type(self.payload)}")
        normalized_payload = bytes(self.payload)
        if len(normalized_payload) > 65535:
            raise InvalidPacketError(
                f"Payload length exceeds maximum 16-bit uint (65535), "
                f"got {len(normalized_payload)}"
            )
        object.__setattr__(self, "payload", normalized_payload)

        # 4. Normalize and validate signature to immutable bytes or None
        if self.signature is not None:
            if not isinstance(self.signature, (bytes, bytearray)):
                raise InvalidPacketError(
                    f"Signature must be bytes when present, got {type(self.signature)}"
                )
            normalized_signature = bytes(self.signature)
            if len(normalized_signature) != SIGNATURE_SIZE:
                raise InvalidPacketError(
                    f"Signature must be exactly {SIGNATURE_SIZE} bytes "
                    f"when present, got {len(normalized_signature)}"
                )
            object.__setattr__(self, "signature", normalized_signature)
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
        """Return True if the packet carries an optional wire signature.

        Note: Signature wire placement is implemented; cryptographic signing semantics
        are verified during the cryptographic interoperability phase.
        """
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
