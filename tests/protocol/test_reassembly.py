"""Tests for BitChat protocol packet reassembly."""

from __future__ import annotations

import random

import pytest

from bitchat.exceptions import (
    FragmentPayloadError,
    InvalidFragmentError,
)
from bitchat.protocol.constants import (
    CURRENT_PROTOCOL_VERSION,
    MessageType,
)
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    fragment_encoded_packet,
)
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler


def _build_test_fragments(
    raw_data: bytes,
    sender_id: bytes = b"\x01" * 8,
    msg_type: MessageType = MessageType.Message,
    frag_id: bytes = b"TESTFRAG",
) -> list[BitchatPacket]:
    """Fragment raw_data into BitchatPacket fragment instances."""
    return fragment_encoded_packet(
        encoded_packet=raw_data,
        sender_id=sender_id,
        original_message_type=msg_type,
        fragment_id=frag_id,
    )


class TestReassemblerBasics:
    def test_ordered_reassembly(self) -> None:
        raw_data = b"Hello from BitChat fragmentation!" * 20  # 660 bytes
        frags = _build_test_fragments(raw_data)
        assert len(frags) == 5

        assembler = FragmentReassembler()
        for _i, frag in enumerate(frags[:-1]):
            result = assembler.add_fragment_packet(frag)
            assert result is None
            assert assembler.active_assembly_count == 1

        final_result = assembler.add_fragment_packet(frags[-1])
        assert final_result == raw_data
        assert assembler.active_assembly_count == 0

    def test_reverse_order_reassembly(self) -> None:
        raw_data = bytes(range(256)) * 3  # 768 bytes
        frags = _build_test_fragments(raw_data)
        assert len(frags) > 1

        assembler = FragmentReassembler()
        for frag in reversed(frags[1:]):
            assert assembler.add_fragment_packet(frag) is None

        # Deliver the first fragment last
        result = assembler.add_fragment_packet(frags[0])
        assert result == raw_data
        assert assembler.active_assembly_count == 0

    def test_random_order_reassembly(self) -> None:
        raw_data = b"Random order reassembly test string with entropy." * 25
        frags = _build_test_fragments(raw_data)
        shuffled = list(frags)
        random.seed(42)
        random.shuffle(shuffled)

        assembler = FragmentReassembler()
        result = None
        for frag in shuffled:
            res = assembler.add_fragment_packet(frag)
            if res is not None:
                result = res

        assert result == raw_data
        assert assembler.active_assembly_count == 0

    def test_missing_fragment_keeps_assembly_pending(self) -> None:
        raw_data = b"X" * 600
        frags = _build_test_fragments(raw_data)
        assert len(frags) == 4

        assembler = FragmentReassembler()
        # Feed all except index 2
        assembler.add_fragment_packet(frags[0])
        assembler.add_fragment_packet(frags[1])
        result = assembler.add_fragment_packet(frags[3])

        assert result is None
        assert assembler.active_assembly_count == 1

        # Now feed the missing fragment
        result2 = assembler.add_fragment_packet(frags[2])
        assert result2 == raw_data
        assert assembler.active_assembly_count == 0


class TestDuplicateHandling:
    def test_identical_duplicate_is_ignored(self) -> None:
        raw_data = b"D" * 600
        frags = _build_test_fragments(raw_data)

        assembler = FragmentReassembler()
        # Feed frag 0 twice
        assert assembler.add_fragment_packet(frags[0]) is None
        assert assembler.add_fragment_packet(frags[0]) is None

        # Feed remaining fragments
        for f in frags[1:-1]:
            assert assembler.add_fragment_packet(f) is None

        result = assembler.add_fragment_packet(frags[-1])
        assert result == raw_data

    def test_conflicting_duplicate_at_same_index_raises(self) -> None:
        raw_data = b"C" * 600
        frags = _build_test_fragments(raw_data)

        assembler = FragmentReassembler()
        assembler.add_fragment_packet(frags[0])

        # Create a conflicting fragment with the same index (0) but different data
        conflicting_payload = create_fragment_payload(
            fragment_id=b"TESTFRAG",
            index=0,
            total=len(frags),
            original_message_type=MessageType.Message,
            chunk_data=b"CONFLICTING DATA HERE",
        )
        conflicting_pkt = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.FragmentStart,
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=conflicting_payload,
            signature=None,
        )

        with pytest.raises(InvalidFragmentError, match="Conflicting"):
            assembler.add_fragment_packet(conflicting_pkt)
        # Corrupted assembly should be dropped
        assert assembler.active_assembly_count == 0


class TestMetadataConsistencyRejection:
    def test_inconsistent_total_raises(self) -> None:
        fid = b"METADATA"
        assembler = FragmentReassembler()

        # Fragment 0 says total = 3
        p0 = create_fragment_payload(fid, 0, 3, MessageType.Message, b"chunk0")
        assembler.add_fragment(b"\x01" * 8, p0)

        # Fragment 1 says total = 4
        p1 = create_fragment_payload(fid, 1, 4, MessageType.Message, b"chunk1")
        with pytest.raises(InvalidFragmentError, match="total"):
            assembler.add_fragment(b"\x01" * 8, p1)
        assert assembler.active_assembly_count == 0

    def test_inconsistent_original_type_raises(self) -> None:
        fid = b"METADATA"
        assembler = FragmentReassembler()

        p0 = create_fragment_payload(fid, 0, 3, MessageType.Message, b"chunk0")
        assembler.add_fragment(b"\x01" * 8, p0)

        p1 = create_fragment_payload(fid, 1, 3, MessageType.ChannelAnnounce, b"chunk1")
        with pytest.raises(InvalidFragmentError, match="original_message_type"):
            assembler.add_fragment(b"\x01" * 8, p1)
        assert assembler.active_assembly_count == 0


class TestSenderIsolation:
    def test_identical_fragment_id_from_different_senders_do_not_collide(self) -> None:
        """Two senders picking the same fragment ID must remain separate."""
        fid = b"COLLIDE_"
        data_a = b"Sender A payload data"
        data_b = b"Sender B payload data"

        assembler = FragmentReassembler()

        # Sender A sends frag 0 of 2
        p_a0 = create_fragment_payload(fid, 0, 2, MessageType.Message, data_a[:10])
        assert assembler.add_fragment(b"SENDER_A", p_a0) is None
        assert assembler.active_assembly_count == 1

        # Sender B sends frag 0 of 2 with the same fragment ID
        p_b0 = create_fragment_payload(fid, 0, 2, MessageType.Message, data_b[:10])
        assert assembler.add_fragment(b"SENDER_B", p_b0) is None
        # Must create a separate assembly
        assert assembler.active_assembly_count == 2

        # Complete Sender B
        p_b1 = create_fragment_payload(fid, 1, 2, MessageType.Message, data_b[10:])
        res_b = assembler.add_fragment(b"SENDER_B", p_b1)
        assert res_b == data_b
        # Sender A still active
        assert assembler.active_assembly_count == 1

        # Complete Sender A
        p_a1 = create_fragment_payload(fid, 1, 2, MessageType.Message, data_a[10:])
        res_a = assembler.add_fragment(b"SENDER_A", p_a1)
        assert res_a == data_a
        assert assembler.active_assembly_count == 0


class TestValidationAndMalformedInputs:
    def test_non_fragment_packet_type_raises(self) -> None:
        p = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.Message,
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=b"not a fragment",
            signature=None,
        )
        assembler = FragmentReassembler()
        with pytest.raises(InvalidFragmentError, match="not a fragment type"):
            assembler.add_fragment_packet(p)

    def test_mismatched_start_type_for_index_raises(self) -> None:
        # MessageType is FragmentContinue but index is 0
        fid = b"BADTYPE_"
        payload = create_fragment_payload(fid, 0, 3, MessageType.Message, b"chunk0")
        pkt = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.FragmentContinue,  # Wrong! Should be Start
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=payload,
            signature=None,
        )
        assembler = FragmentReassembler()
        with pytest.raises(InvalidFragmentError, match="FragmentStart"):
            assembler.add_fragment_packet(pkt)

    def test_mismatched_end_type_for_index_raises(self) -> None:
        fid = b"BADTYPE_"
        payload = create_fragment_payload(fid, 2, 3, MessageType.Message, b"chunk2")
        pkt = BitchatPacket(
            version=CURRENT_PROTOCOL_VERSION,
            message_type=MessageType.FragmentContinue,  # Wrong! Should be End
            ttl=7,
            timestamp=1700000000000,
            flags=0,
            sender_id=b"\x01" * 8,
            recipient_id=None,
            payload=payload,
            signature=None,
        )
        assembler = FragmentReassembler()
        with pytest.raises(InvalidFragmentError, match="FragmentEnd"):
            assembler.add_fragment_packet(pkt)

    def test_truncated_fragment_payload_raises(self) -> None:
        assembler = FragmentReassembler()
        with pytest.raises(FragmentPayloadError):
            assembler.add_fragment(b"\x01" * 8, b"\x00" * 10)

    def test_prune_stale_assemblies(self) -> None:
        assembler = FragmentReassembler()
        fid = b"STALEFRG"
        payload = create_fragment_payload(fid, 0, 3, MessageType.Message, b"chunk")
        assembler.add_fragment(b"\x01" * 8, payload)
        assert assembler.active_assembly_count == 1

        # Prune with 0 timeout removes all
        pruned = assembler.prune_stale(max_age_seconds=0.0)
        assert pruned == 1
        assert assembler.active_assembly_count == 0

    def test_clear_assemblies(self) -> None:
        assembler = FragmentReassembler()
        fid = b"CLEARFRG"
        payload = create_fragment_payload(fid, 0, 3, MessageType.Message, b"chunk")
        assembler.add_fragment(b"\x01" * 8, payload)
        assert assembler.active_assembly_count == 1
        assembler.clear()
        assert assembler.active_assembly_count == 0
