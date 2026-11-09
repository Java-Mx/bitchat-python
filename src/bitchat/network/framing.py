"""TCP stream packet framing with strict bounds and validation."""

from __future__ import annotations

import struct

from bitchat._native import HAS_NATIVE_CORE, _core, raise_mapped_error
from bitchat.exceptions import FramingError

FRAME_MAGIC: bytes = b"BC\x01\x00"
HEADER_SIZE: int = 8  # 4 bytes magic + 4 bytes length
MAX_FRAME_SIZE: int = 65536  # 64 KB safety ceiling


def py_encode_frame(payload: bytes) -> bytes:
    """Pure-Python reference implementation of encode_frame."""
    length = len(payload)
    if length > MAX_FRAME_SIZE:
        raise FramingError(
            f"Payload size {length} exceeds maximum frame limit of "
            f"{MAX_FRAME_SIZE} bytes"
        )
    return FRAME_MAGIC + struct.pack(">I", length) + payload


def encode_frame(payload: bytes) -> bytes:
    """Wrap raw packet bytes in an 8-byte length-prefixed frame."""
    if HAS_NATIVE_CORE:
        raw = payload if type(payload) is bytes else bytes(payload)
        try:
            return _core.encode_frame_bytes(raw, MAX_FRAME_SIZE)
        except ValueError as exc:
            raise_mapped_error(exc)
    return py_encode_frame(payload)


class PyStreamFramer:
    """Pure-Python reference implementation of StreamFramer."""

    def __init__(self, max_frame_size: int = MAX_FRAME_SIZE) -> None:
        self.max_frame_size = max_frame_size
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, chunk: bytes) -> list[bytes]:
        """Feed incoming bytes into buffer and return all complete payloads."""
        self._buffer.extend(chunk)
        frames: list[bytes] = []

        while len(self._buffer) >= HEADER_SIZE:
            magic = bytes(self._buffer[:4])
            if magic != FRAME_MAGIC:
                raise FramingError(
                    f"Invalid frame magic: {magic.hex()} (expected {FRAME_MAGIC.hex()})"
                )

            (payload_length,) = struct.unpack(">I", self._buffer[4:8])
            if payload_length > self.max_frame_size:
                raise FramingError(
                    f"Frame length {payload_length} exceeds limit of "
                    f"{self.max_frame_size}"
                )

            total_frame_len = HEADER_SIZE + payload_length
            if len(self._buffer) < total_frame_len:
                break

            payload = bytes(self._buffer[HEADER_SIZE:total_frame_len])
            del self._buffer[:total_frame_len]
            frames.append(payload)

        return frames

    def clear(self) -> None:
        """Clear internal stream buffer."""
        self._buffer.clear()


class StreamFramer:
    """Accumulates incoming TCP stream bytes and extracts bounded framed packets."""

    def __init__(self, max_frame_size: int = MAX_FRAME_SIZE) -> None:
        self._max_frame_size = max_frame_size
        if HAS_NATIVE_CORE:
            self._native = _core.NativeStreamFramer(max_frame_size=max_frame_size)
            self._py: PyStreamFramer | None = None
        else:
            self._native = None
            self._py = PyStreamFramer(max_frame_size=max_frame_size)

    @property
    def max_frame_size(self) -> int:
        return self._max_frame_size

    @max_frame_size.setter
    def max_frame_size(self, value: int) -> None:
        self._max_frame_size = value
        if self._native is not None:
            self._native.max_frame_size = value
        elif self._py is not None:
            self._py.max_frame_size = value

    @property
    def buffered_bytes(self) -> int:
        if self._native is not None:
            return self._native.buffered_bytes
        assert self._py is not None
        return self._py.buffered_bytes

    def feed(self, chunk: bytes) -> list[bytes]:
        """Feed incoming bytes into buffer and return all complete payloads."""
        if self._native is not None:
            raw = chunk if type(chunk) is bytes else bytes(chunk)
            try:
                return self._native.feed(raw)
            except ValueError as exc:
                raise_mapped_error(exc)
        assert self._py is not None
        return self._py.feed(chunk)

    def clear(self) -> None:
        """Clear internal stream buffer."""
        if self._native is not None:
            self._native.clear()
            return
        assert self._py is not None
        self._py.clear()
