"""Tests for TCP stream framing and framing error handling."""

from __future__ import annotations

import pytest

from bitchat.network.framing import (
    FRAME_MAGIC,
    HEADER_SIZE,
    MAX_FRAME_SIZE,
    FramingError,
    StreamFramer,
    encode_frame,
)


def test_encode_frame_valid() -> None:
    payload = b"Hello, BitChat LAN!"
    frame = encode_frame(payload)
    assert len(frame) == HEADER_SIZE + len(payload)
    assert frame[:4] == FRAME_MAGIC
    assert frame[HEADER_SIZE:] == payload


def test_encode_frame_oversized() -> None:
    large_payload = b"A" * (MAX_FRAME_SIZE + 1)
    with pytest.raises(FramingError, match="exceeds maximum frame limit"):
        encode_frame(large_payload)


def test_stream_framer_single_frame() -> None:
    framer = StreamFramer()
    payload = b"Simple packet"
    frame = encode_frame(payload)

    frames = framer.feed(frame)
    assert len(frames) == 1
    assert frames[0] == payload
    assert framer.buffered_bytes == 0


def test_stream_framer_concatenated_frames() -> None:
    framer = StreamFramer()
    p1 = b"Packet 1"
    p2 = b"Packet 2 - slightly longer"
    p3 = b"Packet 3 - final"

    blob = encode_frame(p1) + encode_frame(p2) + encode_frame(p3)
    frames = framer.feed(blob)

    assert len(frames) == 3
    assert frames[0] == p1
    assert frames[1] == p2
    assert frames[2] == p3
    assert framer.buffered_bytes == 0


def test_stream_framer_partial_reads() -> None:
    framer = StreamFramer()
    payload = b"A relatively long packet split across byte-by-byte or partial chunks"
    frame = encode_frame(payload)

    # Feed 1 byte at a time
    all_frames: list[bytes] = []
    for byte in frame:
        res = framer.feed(bytes([byte]))
        all_frames.extend(res)

    assert len(all_frames) == 1
    assert all_frames[0] == payload
    assert framer.buffered_bytes == 0


def test_stream_framer_invalid_magic() -> None:
    framer = StreamFramer()
    bad_frame = b"BAD!" + b"\x00\x00\x00\x05" + b"Hello"
    with pytest.raises(FramingError, match="Invalid frame magic"):
        framer.feed(bad_frame)


def test_stream_framer_oversized_frame_rejected() -> None:
    framer = StreamFramer()
    # Construct a frame header claiming 70,000 bytes
    bad_header = FRAME_MAGIC + (70000).to_bytes(4, "big")
    with pytest.raises(FramingError, match="exceeds limit"):
        framer.feed(bad_header)


def test_stream_framer_clear() -> None:
    framer = StreamFramer()
    framer.feed(FRAME_MAGIC + b"\x00\x00\x00\x10")  # Partial header
    assert framer.buffered_bytes > 0
    framer.clear()
    assert framer.buffered_bytes == 0
