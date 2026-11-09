"""Differential and unit tests for the Rust/PyO3 native core (bitchat._bitchat_core)."""

from __future__ import annotations

import os

import pytest

from bitchat._native import HAS_NATIVE_CORE, _core
from bitchat.exceptions import (
    FragmentLimitExceededError,
    FramingError,
    InvalidFragmentError,
    PacketDecodingError,
    UnknownMessageTypeError,
    UnsupportedProtocolVersionError,
)
from bitchat.mesh.dedup import (
    PacketDeduplicator,
    PyPacketDeduplicator,
    compute_packet_id,
    py_compute_packet_id,
)
from bitchat.network.framing import (
    PyStreamFramer,
    StreamFramer,
    encode_frame,
    py_encode_frame,
)
from bitchat.protocol.constants import (
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    FLAG_IS_COMPRESSED,
    MessageType,
)
from bitchat.protocol.decoder import (
    decode_packet,
    py_decode_packet,
    py_unpad_packet_data,
    unpad_packet_data,
)
from bitchat.protocol.encoder import (
    encode_packet,
    get_optimal_block_size,
    pad_packet_data,
    py_encode_packet,
    py_get_optimal_block_size,
)
from bitchat.protocol.fragmentation import (
    fragment_encoded_packet,
    parse_fragment_payload,
    py_fragment_encoded_packet,
    py_parse_fragment_payload,
    py_split_chunks,
    split_chunks,
)
from bitchat.protocol.packet import (
    BitchatPacket,
    peer_id_from_hex,
    peer_id_to_hex,
    py_peer_id_from_hex,
    py_peer_id_to_hex,
)
from bitchat.protocol.reassembly import FragmentReassembler, PyFragmentReassembler


def test_native_core_is_loaded_and_version_matches() -> None:
    """Verify the compiled Rust extension module is loaded and reports version 0.3.1."""
    from bitchat import __version__

    assert HAS_NATIVE_CORE is True
    assert _core is not None
    assert _core.native_core_version() == __version__
    assert _core.native_core_version() == "0.3.1"


@pytest.mark.parametrize(
    ("msg_type", "flags", "ttl", "payload", "recipient", "signature"),
    [
        (MessageType.Announce, 0, 7, b"alice-announce", None, None),
        (
            MessageType.Message,
            FLAG_HAS_RECIPIENT,
            5,
            b"hello mesh world!",
            b"\xaa" * 8,
            None,
        ),
        (
            MessageType.NoiseHandshakeInit,
            FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
            3,
            os.urandom(96),
            b"\xbb" * 8,
            b"\xcc" * 64,
        ),
        (
            MessageType.DeliveryAck,
            FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE | FLAG_IS_COMPRESSED,
            1,
            os.urandom(512),
            b"\xdd" * 8,
            b"\xee" * 64,
        ),
    ],
)
def test_differential_packet_encode_decode_and_id(
    msg_type: MessageType,
    flags: int,
    ttl: int,
    payload: bytes,
    recipient: bytes | None,
    signature: bytes | None,
) -> None:
    """Rust and pure-Python packet encoding, decoding, and SHA-256 ID match byte-for-byte."""
    pkt = BitchatPacket(
        version=1,
        message_type=msg_type,
        ttl=ttl,
        timestamp=1_730_000_123_456,
        flags=flags,
        sender_id=b"\x11\x22\x33\x44\x55\x66\x77\x88",
        recipient_id=recipient,
        payload=payload,
        signature=signature,
    )

    rust_unpadded = encode_packet(pkt, add_padding=False)
    py_unpadded = py_encode_packet(pkt, add_padding=False)
    assert rust_unpadded == py_unpadded

    rust_padded = encode_packet(pkt, add_padding=True)
    py_padded = py_encode_packet(pkt, add_padding=True)
    assert len(rust_padded) == len(py_padded)

    assert decode_packet(rust_padded) == py_decode_packet(rust_padded) == pkt
    assert decode_packet(py_padded) == py_decode_packet(py_padded) == pkt

    rust_id = compute_packet_id(pkt)
    py_id = py_compute_packet_id(pkt)
    assert rust_id == py_id


def test_differential_peer_id_hex_and_block_padding() -> None:
    """Rust and Python peer ID hex conversion and block padding match."""
    raw_peer = b"\x01\x23\x45\x67\x89\xab\xcd\xef"
    assert peer_id_to_hex(raw_peer) == py_peer_id_to_hex(raw_peer) == "0123456789abcdef"
    assert (
        peer_id_from_hex("0123456789ABCDEF")
        == py_peer_id_from_hex("0123456789ABCDEF")
        == raw_peer
    )

    for sz in (0, 1, 15, 63, 64, 240, 256, 300, 500, 900, 1024, 1900, 2048, 4096):
        assert get_optimal_block_size(sz) == py_get_optimal_block_size(sz)
        sample = bytes(i % 251 for i in range(sz))
        padded = pad_packet_data(sample)
        assert unpad_packet_data(padded) == py_unpad_packet_data(padded)
        if len(padded) > len(sample):
            assert unpad_packet_data(padded) == sample


def test_differential_decode_error_parity() -> None:
    """Rust and Python packet decoders raise identical BitChat exception subclasses."""
    # 1. Insufficient bytes
    with pytest.raises(PacketDecodingError):
        decode_packet(b"\x01\x02\x03")
    with pytest.raises(PacketDecodingError):
        py_decode_packet(b"\x01\x02\x03")

    base_pkt = BitchatPacket.create(
        message_type=MessageType.Announce,
        sender_id=b"\x01" * 8,
        payload=b"hello",
    )

    # 2. Unsupported protocol version
    bad_ver = bytearray(encode_packet(base_pkt, add_padding=False))
    bad_ver[0] = 99
    with pytest.raises(UnsupportedProtocolVersionError):
        decode_packet(bytes(bad_ver))
    with pytest.raises(UnsupportedProtocolVersionError):
        py_decode_packet(bytes(bad_ver))

    # 3. Unknown message type
    bad_type = bytearray(encode_packet(base_pkt, add_padding=False))
    bad_type[1] = 0xFE
    with pytest.raises(UnknownMessageTypeError):
        decode_packet(bytes(bad_type))
    with pytest.raises(UnknownMessageTypeError):
        py_decode_packet(bytes(bad_type))

    # 4. Malformed padding byte
    bad_pad = bytearray(encode_packet(base_pkt, add_padding=False) + b"\x00\x00\x99")
    with pytest.raises(PacketDecodingError):
        decode_packet(bytes(bad_pad))
    with pytest.raises(PacketDecodingError):
        py_decode_packet(bytes(bad_pad))


def test_differential_fragmentation_and_reassembly() -> None:
    """Rust and Python fragmentation and reassembly match across multi-chunk payloads."""
    raw_packet = os.urandom(4096)
    sender_id = b"\xaa\xbb\xcc\xdd\x11\x22\x33\x44"
    frag_id = b"\xca\xfe\xba\xbe\x00\x01\x02\x03"

    assert split_chunks(raw_packet, 469) == py_split_chunks(raw_packet, 469)

    rust_frags = fragment_encoded_packet(
        raw_packet,
        sender_id=sender_id,
        original_message_type=MessageType.Message,
        fragment_id=frag_id,
        ttl=5,
        timestamp=1_730_000_000_000,
    )
    py_frags = py_fragment_encoded_packet(
        raw_packet,
        sender_id=sender_id,
        original_message_type=MessageType.Message,
        fragment_id=frag_id,
        ttl=5,
        timestamp=1_730_000_000_000,
    )
    assert rust_frags == py_frags
    assert len(rust_frags) > 2

    for rf, pf in zip(rust_frags, py_frags, strict=True):
        assert parse_fragment_payload(rf.payload) == py_parse_fragment_payload(
            pf.payload
        )

    # Out-of-order reassembly parity
    rust_reasm = FragmentReassembler()
    py_reasm = PyFragmentReassembler()

    shuffled = list(reversed(rust_frags))
    for i, frag in enumerate(shuffled):
        r_out = rust_reasm.add_fragment_packet(frag)
        p_out = py_reasm.add_fragment_packet(frag)
        assert r_out == p_out
        if i < len(shuffled) - 1:
            assert r_out is None
        else:
            assert r_out == raw_packet


def test_differential_reassembly_security_errors() -> None:
    """Rust and Python reassemblers enforce identical security limits and error types."""
    sender_id = b"\x01" * 8
    raw = os.urandom(1500)
    frag_id = b"\x10" * 8
    frags = fragment_encoded_packet(
        raw,
        sender_id=sender_id,
        original_message_type=MessageType.Message,
        fragment_id=frag_id,
        ttl=4,
        timestamp=1000,
    )
    assert len(frags) >= 3

    r_reasm = FragmentReassembler()
    p_reasm = PyFragmentReassembler()
    assert r_reasm.add_fragment_packet(frags[0]) is None
    assert p_reasm.add_fragment_packet(frags[0]) is None

    # Exact duplicate is ignored cleanly
    assert r_reasm.add_fragment_packet(frags[0]) is None
    assert p_reasm.add_fragment_packet(frags[0]) is None

    # Mutate payload byte at the end to create conflicting chunk content
    bad_payload = bytearray(frags[0].payload)
    bad_payload[-1] ^= 0xFF
    conflicting = BitchatPacket(
        version=frags[0].version,
        message_type=frags[0].message_type,
        ttl=frags[0].ttl,
        timestamp=frags[0].timestamp,
        flags=frags[0].flags,
        sender_id=frags[0].sender_id,
        recipient_id=None,
        payload=bytes(bad_payload),
        signature=None,
    )
    with pytest.raises(InvalidFragmentError):
        r_reasm.add_fragment_packet(conflicting)
    with pytest.raises(InvalidFragmentError):
        p_reasm.add_fragment_packet(conflicting)

    # Max reassembled bytes exceeded
    r_small = FragmentReassembler(max_reassembled_bytes=100)
    p_small = PyFragmentReassembler(max_reassembled_bytes=100)
    with pytest.raises(FragmentLimitExceededError):
        r_small.add_fragment_packet(frags[0])
    with pytest.raises(FragmentLimitExceededError):
        p_small.add_fragment_packet(frags[0])


def test_differential_stream_framer() -> None:
    """Rust StreamFramer and PyStreamFramer behave identically on arbitrary TCP chunks."""
    r_framer = StreamFramer(max_frame_size=1024)
    p_framer = PyStreamFramer(max_frame_size=1024)

    payloads = [b"alpha", b"bravo" * 40, b"charlie", os.urandom(512)]
    for p in payloads:
        assert encode_frame(p) == py_encode_frame(p)
    stream = b"".join(encode_frame(p) for p in payloads)

    # Feed in irregular chunk sizes (e.g., 7 bytes at a time)
    r_out: list[bytes] = []
    p_out: list[bytes] = []
    step = 7
    for i in range(0, len(stream), step):
        chunk = stream[i : i + step]
        r_frames = r_framer.feed(chunk)
        p_frames = p_framer.feed(chunk)
        assert r_frames == p_frames
        r_out.extend(r_frames)
        p_out.extend(p_frames)

    assert r_out == p_out == payloads
    assert r_framer.buffered_bytes == p_framer.buffered_bytes == 0

    # Invalid magic raises FramingError in both
    with pytest.raises(FramingError):
        r_framer.feed(b"BADMAGIC\x00\x00\x00\x04test")
    with pytest.raises(FramingError):
        p_framer.feed(b"BADMAGIC\x00\x00\x00\x04test")


def test_differential_packet_deduplicator() -> None:
    """Rust PacketDeduplicator and PyPacketDeduplicator maintain identical LRU + TTL semantics."""
    r_dedup = PacketDeduplicator(max_entries=4, entry_ttl_seconds=10.0)
    py_dedup = PyPacketDeduplicator(max_entries=4, entry_ttl_seconds=10.0)

    packets = [
        BitchatPacket.create(
            message_type=MessageType.Message,
            sender_id=b"\x01" * 8,
            payload=f"msg-{idx}".encode(),
            timestamp=1000 + idx,
        )
        for idx in range(6)
    ]

    for idx, pkt in enumerate(packets):
        assert r_dedup.is_duplicate(pkt, now=100.0 + idx) == py_dedup.is_duplicate(
            pkt, now=100.0 + idx
        )
        assert r_dedup.check_and_record(
            pkt, now=100.0 + idx
        ) == py_dedup.check_and_record(pkt, now=100.0 + idx)
        assert r_dedup.is_duplicate(pkt, now=100.0 + idx) == py_dedup.is_duplicate(
            pkt, now=100.0 + idx
        )
        assert len(r_dedup) == len(py_dedup)

    # First two packets were evicted due to max_entries=4
    assert r_dedup.is_duplicate(packets[0], now=106.0) is False
    assert py_dedup.is_duplicate(packets[0], now=106.0) is False
    assert r_dedup.is_duplicate(packets[5], now=106.0) is True
    assert py_dedup.is_duplicate(packets[5], now=106.0) is True

    # Expiry after entry_ttl_seconds=10.0s
    assert r_dedup.prune_expired(now=200.0) == py_dedup.prune_expired(now=200.0) == 4
    assert len(r_dedup) == len(py_dedup) == 0
