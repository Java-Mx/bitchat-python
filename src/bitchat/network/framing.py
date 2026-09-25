"""TCP stream packet framing with strict bounds and validation."""

from __future__ import annotations

import struct

FRAME_MAGIC: bytes = b"BC\x01\x00"
HEADER_SIZE: int = 8  # 4 bytes magic + 4 bytes length
MAX_FRAME_SIZE: int = 65536  # 64 KB safety ceiling


class FramingError(Exception):
    """Raised when framing magic is invalid or frame size exceeds safety bounds."""


def encode_frame(payload: bytes) -> bytes:
    """Wrap raw packet bytes in an 8-byte length-prefixed frame."""
    length = len(payload)
    if length > MAX_FRAME_SIZE:
        raise FramingError(
            f"Payload size {length} exceeds maximum frame limit of "
            f"{MAX_FRAME_SIZE} bytes"
        )
    return FRAME_MAGIC + struct.pack(">I", length) + payload


class StreamFramer:
    """Accumulates incoming TCP stream bytes and extracts bounded framed packets.

    Properly handles:
    - Partial reads (chunk smaller than frame header or payload)
    - Multiple concatenated frames in a single read
    - Frame split across multiple reads
    - Malformed magic or oversized frames (raises FramingError)
    """

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
            # 1. Validate magic bytes
            magic = bytes(self._buffer[:4])
            if magic != FRAME_MAGIC:
                raise FramingError(
                    f"Invalid frame magic: {magic.hex()} (expected {FRAME_MAGIC.hex()})"
                )

            # 2. Extract payload length
            (payload_length,) = struct.unpack(">I", self._buffer[4:8])
            if payload_length > self.max_frame_size:
                raise FramingError(
                    f"Frame length {payload_length} exceeds limit of "
                    f"{self.max_frame_size}"
                )

            # 3. Check if full frame has arrived
            total_frame_len = HEADER_SIZE + payload_length
            if len(self._buffer) < total_frame_len:
                break  # Wait for remaining frame bytes

            # 4. Extract frame payload and advance buffer
            payload = bytes(self._buffer[HEADER_SIZE:total_frame_len])
            del self._buffer[:total_frame_len]
            frames.append(payload)

        return frames

    def clear(self) -> None:
        """Clear internal stream buffer."""
        self._buffer.clear()
