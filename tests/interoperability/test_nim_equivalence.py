"""Tests verifying exact byte-for-byte protocol equivalence between Python and Nim."""

import random
import sys
from pathlib import Path

import pytest

from bitchat.protocol.constants import (
    FLAG_HAS_RECIPIENT,
    FLAG_HAS_SIGNATURE,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet, unpad_packet_data
from bitchat.protocol.encoder import encode_packet, pad_packet_data
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    fragment_encoded_packet,
    parse_fragment_payload,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler

# Ensure nim/benchmarks is on sys.path for importing isolated FFI adapter
_NIM_BENCHMARKS_DIR = str(
    Path(__file__).resolve().parent.parent.parent / "nim" / "benchmarks"
)
if _NIM_BENCHMARKS_DIR not in sys.path:
    sys.path.insert(0, _NIM_BENCHMARKS_DIR)

from nim_ffi import (  # noqa: E402 # pyright: ignore[reportMissingImports]
    NimReassembler,
    is_nim_available,
    nim_create_fragment,
    nim_decode_packet,
    nim_encode_packet,
    nim_pad_packet,
    nim_parse_fragment,
    nim_unpad_packet,
)

pytestmark = pytest.mark.skipif(
    not is_nim_available(),
    reason="Nim dynamic library (bitchat_nim.dll / .so) is not compiled or available",
)


def test_unpad_equivalence():
    """Verify Python and Nim unpadding produce identical output."""
    raw = b"BitChat protocol payload data for testing equivalence"
    padded = pad_packet_data(raw, 256)

    py_unpadded = unpad_packet_data(padded)
    nim_unpadded = nim_unpad_packet(padded)

    assert py_unpadded == raw
    assert nim_unpadded == raw
    assert py_unpadded == nim_unpadded


def test_pad_length_equivalence():
    """Verify Python and Nim pad to identical optimal block sizes."""
    # Sizes where padding is applied (target - size <= 255 and size + 16 <= target)
    for size in [10, 64, 150, 200, 240, 300, 450, 490]:
        data = b"X" * size

        py_padded = pad_packet_data(data)
        nim_padded = nim_pad_packet(data)

        assert len(py_padded) == len(nim_padded)
        assert unpad_packet_data(nim_padded) == data
        assert nim_unpad_packet(py_padded) == data


def test_unpadded_packet_encode_byte_equivalence():
    """Verify unpadded packet encoding produces 100% byte-for-byte identical output."""
    sender = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    recip = b"\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"
    payload = b"Exact byte comparison test message"
    sig = bytes(range(64))
    timestamp = 1700000000123

    py_pkt = BitchatPacket(
        version=1,
        message_type=MessageType.Message,
        ttl=7,
        timestamp=timestamp,
        flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
        sender_id=sender,
        recipient_id=recip,
        payload=payload,
        signature=sig,
    )

    py_encoded = encode_packet(py_pkt, add_padding=False)
    nim_encoded = nim_encode_packet(
        version=1,
        msg_type=int(MessageType.Message),
        ttl=7,
        timestamp=timestamp,
        flags=FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE,
        sender_id=sender,
        recipient_id=recip,
        payload=payload,
        signature=sig,
        add_padding=False,
    )

    assert py_encoded == nim_encoded


def test_cross_decode_python_to_nim():
    """Verify packet encoded in Python is correctly decoded in Nim."""
    sender = b"\xaa\xbb\xcc\xdd\x11\x22\x33\x44"
    payload = b"Cross-decode payload Python -> Nim"
    py_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender,
        payload=payload,
        ttl=5,
        timestamp=999888777,
    )
    wire_bytes = encode_packet(py_pkt, add_padding=True)

    nim_res = nim_decode_packet(wire_bytes)
    assert nim_res["version"] == 1
    assert nim_res["msg_type"] == int(MessageType.Message)
    assert nim_res["ttl"] == 5
    assert nim_res["timestamp"] == 999888777
    assert nim_res["flags"] == 0
    assert nim_res["sender_id"] == sender
    assert nim_res["recipient_id"] is None
    assert nim_res["payload"] == payload
    assert nim_res["signature"] is None


def test_cross_decode_nim_to_python():
    """Verify packet encoded in Nim is correctly decoded in Python."""
    sender = b"\x10\x20\x30\x40\x50\x60\x70\x80"
    recip = b"\xff\xff\xff\xff\xff\xff\xff\xff"
    payload = b"Cross-decode payload Nim -> Python"
    flags = FLAG_HAS_RECIPIENT

    nim_wire = nim_encode_packet(
        version=1,
        msg_type=int(MessageType.ChannelAnnounce),
        ttl=4,
        timestamp=1234567890,
        flags=flags,
        sender_id=sender,
        recipient_id=recip,
        payload=payload,
        signature=None,
        add_padding=True,
    )

    py_pkt = decode_packet(nim_wire)
    assert py_pkt.version == 1
    assert py_pkt.message_type == MessageType.ChannelAnnounce
    assert py_pkt.ttl == 4
    assert py_pkt.timestamp == 1234567890
    assert py_pkt.sender_id == sender
    assert py_pkt.recipient_id == recip
    assert py_pkt.payload == payload


def test_fragment_payload_byte_equivalence():
    """Verify 13-byte fragment header packing is 100% byte-for-byte identical."""
    frag_id = b"\x01\x03\x05\x07\x02\x04\x06\x08"
    chunk = b"Fragment chunk test data"

    py_payload = create_fragment_payload(
        frag_id,
        index=3,
        total=10,
        original_message_type=MessageType.Message,
        chunk_data=chunk,
    )
    nim_payload = nim_create_fragment(
        frag_id, index=3, total=10, orig_type=int(MessageType.Message), chunk_data=chunk
    )

    assert py_payload == nim_payload

    # Cross parse
    f_py, idx_py, tot_py, t_py, data_py = parse_fragment_payload(nim_payload)
    f_nim, idx_nim, tot_nim, t_nim, data_nim = nim_parse_fragment(py_payload)

    assert f_py == f_nim == frag_id
    assert idx_py == idx_nim == 3
    assert tot_py == tot_nim == 10
    assert t_py == t_nim == int(MessageType.Message)
    assert data_py == data_nim == chunk


def test_cross_reassembly_python_frags_to_nim():
    """Verify Nim reassembler accurately reconstructs fragments generated by Python."""
    sender = b"\x11\x22\x33\x44\x55\x66\x77\x88"
    orig_payload = b"Large payload test for cross-reassembly: " + (
        b"0123456789ABCDEF" * 50
    )
    large_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender,
        payload=orig_payload,
        ttl=7,
        timestamp=1700000000,
    )
    encoded_large = encode_packet(large_pkt)
    assert len(encoded_large) > 500

    frag_packets = fragment_encoded_packet(
        encoded_large, sender_id=sender, original_message_type=MessageType.Message
    )
    assert len(frag_packets) > 1

    # Reassemble using NimReassembler
    nim_r = NimReassembler()
    reassembled: bytes | None = None
    for fp in frag_packets:
        reassembled = nim_r.add_fragment(fp.sender_id, fp.payload)

    assert reassembled is not None
    assert reassembled == encoded_large

    # Decode reassembled bytes with Python decoder
    decoded = decode_packet(reassembled)
    assert decoded.payload == orig_payload
    nim_r.close()


def test_cross_reassembly_out_of_order():
    """Verify Nim reassembler supports reversed and randomized fragment delivery."""
    sender = b"\x99\x88\x77\x66\x55\x44\x33\x22"
    orig_payload = b"Out-of-order test: " + (b"XYZ-12345-" * 60)
    large_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender,
        payload=orig_payload,
        ttl=7,
        timestamp=1700000000,
    )
    encoded_large = encode_packet(large_pkt)
    frag_packets = fragment_encoded_packet(
        encoded_large, sender_id=sender, original_message_type=MessageType.Message
    )

    # 1. Reverse order
    nim_r1 = NimReassembler()
    rev_frags = list(reversed(frag_packets))
    res1: bytes | None = None
    for fp in rev_frags:
        res1 = nim_r1.add_fragment(fp.sender_id, fp.payload)
    assert res1 == encoded_large
    nim_r1.close()

    # 2. Randomized order
    nim_r2 = NimReassembler()
    shuffled_frags = list(frag_packets)
    random.Random(42).shuffle(shuffled_frags)
    res2: bytes | None = None
    for fp in shuffled_frags:
        res2 = nim_r2.add_fragment(fp.sender_id, fp.payload)
    assert res2 == encoded_large
    nim_r2.close()


def test_cross_reassembly_nim_frags_to_python():
    """Verify Python reassembler accurately reconstructs fragments generated in Nim."""
    sender = b"\x12\x34\x56\x78\x9a\xbc\xde\xf0"
    raw_data = b"Testing Python reassembly with Nim-created fragment headers: " + (
        b"ABC" * 200
    )

    # Split into 150-byte chunks and create fragment payloads using Nim
    frag_id = b"\xaa\xbb\xcc\xdd\xee\xff\x00\x11"
    chunk_size = 150
    chunks = [raw_data[i : i + chunk_size] for i in range(0, len(raw_data), chunk_size)]
    total = len(chunks)

    py_reassembler = FragmentReassembler()
    res: bytes | None = None

    for idx, c in enumerate(chunks):
        nim_payload = nim_create_fragment(
            frag_id,
            index=idx,
            total=total,
            orig_type=int(MessageType.Message),
            chunk_data=c,
        )
        msg_type = (
            MessageType.FragmentStart
            if idx == 0
            else (
                MessageType.FragmentEnd
                if idx == total - 1
                else MessageType.FragmentContinue
            )
        )
        pkt = BitchatPacket.create(
            message_type=msg_type,
            sender_id=sender,
            payload=nim_payload,
            ttl=7,
            timestamp=1000,
        )
        res = py_reassembler.add_fragment_packet(pkt)

    assert res == raw_data


def test_ffi_error_handling():
    """Verify FFI rejects invalid, corrupted, or truncated inputs."""
    # Corrupt packet input
    with pytest.raises(ValueError):
        nim_decode_packet(b"\x01\x02\x03")  # too small

    # Corrupt fragment payload
    with pytest.raises(ValueError):
        nim_parse_fragment(b"\x00" * 5)  # smaller than 13 bytes
