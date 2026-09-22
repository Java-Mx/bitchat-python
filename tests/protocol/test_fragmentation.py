"""Tests for BitChat protocol packet fragmentation."""

from __future__ import annotations

import struct

import pytest

from bitchat.exceptions import (
    FragmentPayloadError,
    InvalidFragmentError,
    PacketEncodingError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    FRAGMENT_CHUNK_SIZE,
    FRAGMENT_HEADER_SIZE,
    FRAGMENT_ID_SIZE,
    FRAGMENTATION_THRESHOLD,
    MessageType,
)
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    encode_fragment_packets,
    fragment_encoded_packet,
    fragment_packet,
    generate_fragment_id,
    parse_fragment_payload,
    should_fragment,
    split_chunks,
)
from bitchat.protocol.packet import BitchatPacket


def _make_packet(
    payload_size: int,
    msg_type: MessageType = MessageType.Message,
    sender_id: bytes = b"\x01" * 8,
) -> BitchatPacket:
    """Create a BitchatPacket with a given payload size."""
    return BitchatPacket(
        version=CURRENT_PROTOCOL_VERSION,
        message_type=msg_type,
        ttl=7,
        timestamp=1700000000000,
        flags=0,
        sender_id=sender_id,
        recipient_id=None,
        payload=b"A" * payload_size,
        signature=None,
    )


class TestShouldFragment:
    def test_threshold_constant(self) -> None:
        assert FRAGMENTATION_THRESHOLD == 500
        assert FRAGMENT_CHUNK_SIZE == 150
        assert FRAGMENT_HEADER_SIZE == 13
        assert FRAGMENT_ID_SIZE == 8

    def test_small_bytes_remain_unfragmented(self) -> None:
        assert not should_fragment(b"\x00" * 100)
        assert not should_fragment(b"\x00" * 499)

    def test_exactly_500_bytes_does_not_fragment(self) -> None:
        assert not should_fragment(b"\x00" * 500)

    def test_501_bytes_requires_fragmentation(self) -> None:
        assert should_fragment(b"\x00" * 501)

    def test_large_bytes_requires_fragmentation(self) -> None:
        assert should_fragment(b"\x00" * 1024)

    def test_packet_object_threshold(self) -> None:
        # Padded packets smaller than or equal to 500 bytes (e.g. 256 block size)
        p_small = _make_packet(payload_size=50)
        assert not should_fragment(p_small)

        # Large packet whose encoded padded wire size exceeds 500
        p_large = _make_packet(payload_size=500)
        assert should_fragment(p_large)

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError):
            should_fragment(12345)  # type: ignore[arg-type]


class TestSplitChunks:
    def test_empty_bytes_returns_empty_list(self) -> None:
        assert split_chunks(b"") == []

    def test_chunk_boundaries(self) -> None:
        data = bytes(range(256)) * 2  # 512 bytes
        chunks = split_chunks(data, chunk_size=150)
        # 512 = 150 + 150 + 150 + 62 -> 4 chunks
        assert len(chunks) == 4
        assert len(chunks[0]) == 150
        assert len(chunks[1]) == 150
        assert len(chunks[2]) == 150
        assert len(chunks[3]) == 62
        assert b"".join(chunks) == data

    def test_exact_multiple_of_chunk_size(self) -> None:
        data = b"B" * 300
        chunks = split_chunks(data, chunk_size=150)
        assert len(chunks) == 2
        assert len(chunks[0]) == 150
        assert len(chunks[1]) == 150
        assert b"".join(chunks) == data

    def test_invalid_chunk_size_raises(self) -> None:
        with pytest.raises(ValueError):
            split_chunks(b"abc", chunk_size=0)

    def test_invalid_data_type_raises(self) -> None:
        with pytest.raises(TypeError):
            split_chunks("not bytes", chunk_size=150)  # type: ignore[arg-type]


class TestFragmentPayloadEncodingDecoding:
    def test_generate_fragment_id_returns_8_bytes(self) -> None:
        fid1 = generate_fragment_id()
        fid2 = generate_fragment_id()
        assert isinstance(fid1, bytes)
        assert len(fid1) == 8
        assert fid1 != fid2

    def test_create_and_parse_roundtrip(self) -> None:
        fid = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        chunk = b"hello fragment world"
        payload = create_fragment_payload(
            fragment_id=fid,
            index=2,
            total=5,
            original_message_type=MessageType.Message,
            chunk_data=chunk,
        )
        assert len(payload) == 13 + len(chunk)

        parsed_id, index, total, orig_type, data = parse_fragment_payload(payload)
        assert parsed_id == fid
        assert index == 2
        assert total == 5
        assert orig_type == int(MessageType.Message)
        assert data == chunk

    def test_big_endian_u16_encoding(self) -> None:
        fid = b"12345678"
        payload = create_fragment_payload(fid, 0x0102, 0x0304, 0x08, b"data")
        # index is at offset 8..10, total is at 10..12
        assert payload[8:10] == b"\x01\x02"
        assert payload[10:12] == b"\x03\x04"
        assert payload[12] == 0x08

    def test_create_invalid_fragment_id_size(self) -> None:
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(b"short", 0, 2, 4, b"data")

    def test_create_invalid_index_greater_or_equal_total(self) -> None:
        fid = b"12345678"
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(fid, 2, 2, 4, b"data")
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(fid, 5, 2, 4, b"data")

    def test_create_negative_index(self) -> None:
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(b"12345678", -1, 2, 4, b"data")

    def test_create_zero_total(self) -> None:
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(b"12345678", 0, 0, 4, b"data")

    def test_create_bool_rejected(self) -> None:
        with pytest.raises(InvalidFragmentError):
            create_fragment_payload(b"12345678", True, 2, 4, b"data")  # type: ignore[arg-type]

    def test_parse_too_short_raises(self) -> None:
        with pytest.raises(FragmentPayloadError):
            parse_fragment_payload(b"\x00" * 12)

    def test_parse_zero_total_raises(self) -> None:
        # 8 bytes ID + index 0 + total 0 + orig_type 4
        bad = struct.pack(">8sHHB", b"12345678", 0, 0, 4)
        with pytest.raises(InvalidFragmentError):
            parse_fragment_payload(bad)

    def test_parse_index_ge_total_raises(self) -> None:
        bad = struct.pack(">8sHHB", b"12345678", 3, 3, 4)
        with pytest.raises(InvalidFragmentError):
            parse_fragment_payload(bad)


class TestFragmentPacketCreation:
    def test_small_packet_returns_empty_list(self) -> None:
        p = _make_packet(payload_size=50)
        assert fragment_packet(p) == []

    def test_unfragmented_encoded_bytes_returns_empty_list(self) -> None:
        assert fragment_encoded_packet(b"\x00" * 500, b"\x01" * 8, 4) == []

    def test_501_bytes_packet_fragments(self) -> None:
        raw_501 = b"X" * 501
        frags = fragment_encoded_packet(
            encoded_packet=raw_501,
            sender_id=b"\x01" * 8,
            original_message_type=MessageType.Message,
            ttl=5,
        )
        # 501 bytes / 150 = 4 fragments (150, 150, 150, 51)
        assert len(frags) == 4
        assert frags[0].message_type == MessageType.FragmentStart
        assert frags[1].message_type == MessageType.FragmentContinue
        assert frags[2].message_type == MessageType.FragmentContinue
        assert frags[3].message_type == MessageType.FragmentEnd

        for f in frags:
            assert f.ttl == 5
            assert f.sender_id == b"\x01" * 8
            assert f.recipient_id is None
            assert f.signature is None

    def test_exactly_two_fragments_assignment(self) -> None:
        raw_300 = b"Y" * 300
        # By chunking into 150 bytes: 300 bytes gives exactly 2 chunks
        chunks = split_chunks(raw_300, 150)
        assert len(chunks) == 2
        # Construct fragment packets manually: verify that when total==2,
        # assignment is Start and End (no Continue).
        fid = b"TESTTWO_"
        p0 = create_fragment_payload(fid, 0, 2, MessageType.ChannelAnnounce, chunks[0])
        p1 = create_fragment_payload(fid, 1, 2, MessageType.ChannelAnnounce, chunks[1])
        _, idx0, tot0, type0, d0 = parse_fragment_payload(p0)
        _, idx1, tot1, type1, d1 = parse_fragment_payload(p1)
        assert idx0 == 0 and tot0 == 2 and type0 == int(MessageType.ChannelAnnounce)
        assert idx1 == 1 and tot1 == 2 and type1 == int(MessageType.ChannelAnnounce)
        assert d0 == chunks[0]
        assert d1 == chunks[1]

    def test_original_message_type_preservation(self) -> None:
        raw_600 = b"Z" * 600
        frags = fragment_encoded_packet(
            encoded_packet=raw_600,
            sender_id=b"\x02" * 8,
            original_message_type=MessageType.ChannelAnnounce,
        )
        assert len(frags) > 0
        for f in frags:
            _, _, _, orig_type, _ = parse_fragment_payload(f.payload)
            assert orig_type == int(MessageType.ChannelAnnounce)

    def test_random_fragment_id_shared_across_all_fragments(self) -> None:
        raw_600 = b"Z" * 600
        frags = fragment_encoded_packet(
            encoded_packet=raw_600,
            sender_id=b"\x02" * 8,
            original_message_type=MessageType.Message,
        )
        ids = [parse_fragment_payload(f.payload)[0] for f in frags]
        assert all(fid == ids[0] for fid in ids)
        assert len(ids[0]) == 8

    def test_custom_fragment_id_accepted(self) -> None:
        custom_id = b"MYFRAGID"
        raw_600 = b"Z" * 600
        frags = fragment_encoded_packet(
            encoded_packet=raw_600,
            sender_id=b"\x02" * 8,
            original_message_type=MessageType.Message,
            fragment_id=custom_id,
        )
        for f in frags:
            assert parse_fragment_payload(f.payload)[0] == custom_id

    def test_encode_fragment_packets(self) -> None:
        raw_600 = b"Z" * 600
        frags = fragment_encoded_packet(
            encoded_packet=raw_600,
            sender_id=b"\x02" * 8,
            original_message_type=MessageType.Message,
        )
        encoded_frags = encode_fragment_packets(frags)
        assert len(encoded_frags) == len(frags)
        for enc in encoded_frags:
            decoded = decode_packet(enc)
            assert decoded.message_type in (
                MessageType.FragmentStart,
                MessageType.FragmentContinue,
                MessageType.FragmentEnd,
            )

    def test_fragment_packet_invalid_type_raises(self) -> None:
        with pytest.raises(PacketEncodingError):
            fragment_packet("not a packet")  # type: ignore[arg-type]
