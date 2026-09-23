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


class InsufficientPacketBytesError(PacketDecodingError):
    """Raised when the byte buffer is too short to decode a complete packet."""


class CorruptPaddingError(PacketDecodingError):
    """Raised when padding length delimiter is inconsistent with packet size."""


# ---------------------------------------------------------------------------
# Fragmentation error hierarchy
# ---------------------------------------------------------------------------


class FragmentationError(ProtocolError):
    """Base exception for fragmentation and reassembly errors."""


class InvalidFragmentError(FragmentationError):
    """Raised when a fragment fails structural or metadata validation."""


class FragmentPayloadError(InvalidFragmentError):
    """Raised when a fragment payload cannot be parsed or is too short."""


class FragmentLimitExceededError(FragmentationError):
    """Raised when fragment counts or assembly sizes exceed resource limits."""


# ---------------------------------------------------------------------------
# Cryptographic error hierarchy
# ---------------------------------------------------------------------------


class CryptoError(BitChatError):
    """Base exception for all cryptographic errors in BitChat."""


class InvalidKeyError(CryptoError):
    """Raised when a cryptographic key is malformed, wrong size, or invalid."""


class InvalidSignatureError(CryptoError):
    """Raised when a signature value is malformed or wrong size."""


class SignatureVerificationError(CryptoError):
    """Raised when Ed25519 signature verification fails."""


class KeyExchangeError(CryptoError):
    """Raised when an X25519 Diffie-Hellman exchange fails."""


class EncryptionError(CryptoError):
    """Raised when AEAD encryption fails."""


class DecryptionError(CryptoError):
    """Raised when AEAD decryption or authentication fails."""


class InvalidNonceError(CryptoError):
    """Raised when a nonce is invalid, reused, or out of bounds."""


class NoiseError(CryptoError):
    """Base exception for Noise protocol errors."""


class NoiseStateError(NoiseError):
    """Raised on an invalid Noise session state transition or illegal operation."""


class ReplayError(NoiseError):
    """Raised when a replayed or duplicate Noise transport message is detected."""


class AuthenticationError(NoiseError):
    """Raised when Noise handshake authentication fails."""


# ---------------------------------------------------------------------------
# BLE transport error hierarchy
# ---------------------------------------------------------------------------


class BLEError(BitChatError):
    """Base exception for Bluetooth Low Energy transport errors."""


class BLEScanError(BLEError):
    """Raised when starting, stopping, or executing BLE scanning fails."""


class BLEConnectionError(BLEError):
    """Raised when establishing, maintaining, or closing a BLE connection fails."""


class BLEGATTError(BLEError):
    """Raised when BitChat GATT service or characteristic discovery fails."""


class BLETransportError(BLEError):
    """Raised when sending, receiving, or subscribing to BLE data fails."""
