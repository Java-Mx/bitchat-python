"""Application error hierarchy for BitChat."""


class BitChatError(Exception):
    """Base exception for all BitChat errors."""


class ConfigurationError(BitChatError):
    """Raised when configuration loading or saving fails."""


class CommandError(BitChatError):
    """Raised when a command fails to parse or execute."""


class ApplicationError(BitChatError):
    """Raised when an application lifecycle error occurs."""


class ProtocolError(BitChatError):
    """Base exception for BitChat protocol-level errors."""


class PacketEncodingError(ProtocolError):
    """Raised when encoding a packet into binary format fails."""


class PacketDecodingError(ProtocolError):
    """Raised when decoding a binary packet fails."""


class UnsupportedProtocolVersionError(PacketDecodingError):
    """Raised when a packet specifies an unsupported protocol version."""


class UnknownMessageTypeError(PacketDecodingError):
    """Raised when a packet specifies an unknown message type."""


class InvalidPacketError(ProtocolError):
    """Raised when a packet model fails field validation constraints."""
