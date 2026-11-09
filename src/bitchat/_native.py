"""Native Rust/PyO3 core loader and exception mapper for BitChat."""

from __future__ import annotations

from typing import NoReturn

from bitchat.exceptions import (
    CorruptPaddingError,
    FragmentationError,
    FragmentLimitExceededError,
    FragmentPayloadError,
    FramingError,
    InsufficientPacketBytesError,
    InvalidFragmentError,
    InvalidPacketError,
    PacketDecodingError,
    PacketEncodingError,
    ProtocolError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)

try:
    from bitchat import _bitchat_core as _core

    HAS_NATIVE_CORE: bool = True
except ImportError:
    _core = None  # type: ignore[assignment]
    HAS_NATIVE_CORE = False

_ERROR_PREFIX = "__BITCHAT_ERR__:"

_ERROR_MAP: dict[str, type[Exception]] = {
    "InvalidPacketError": InvalidPacketError,
    "PacketEncodingError": PacketEncodingError,
    "PacketDecodingError": PacketDecodingError,
    "UnsupportedProtocolVersionError": UnsupportedProtocolVersionError,
    "UnknownMessageTypeError": UnknownMessageTypeError,
    "InsufficientPacketBytesError": InsufficientPacketBytesError,
    "CorruptPaddingError": CorruptPaddingError,
    "FragmentationError": FragmentationError,
    "InvalidFragmentError": InvalidFragmentError,
    "FragmentPayloadError": FragmentPayloadError,
    "FragmentLimitExceededError": FragmentLimitExceededError,
    "FramingError": FramingError,
    "ProtocolError": ProtocolError,
    "ValueError": ValueError,
}


def raise_mapped_error(exc: ValueError) -> NoReturn:
    """Translate a tagged Rust ValueError into a BitChat exception."""
    msg = str(exc)
    if msg.startswith(_ERROR_PREFIX):
        rest = msg[len(_ERROR_PREFIX) :]
        sep_idx = rest.find("::")
        if sep_idx > 0:
            tag = rest[:sep_idx]
            body = rest[sep_idx + 2 :]
            exc_cls = _ERROR_MAP.get(tag)
            if exc_cls is not None:
                raise exc_cls(body) from None
    raise exc


__all__ = [
    "HAS_NATIVE_CORE",
    "_core",
    "raise_mapped_error",
]
