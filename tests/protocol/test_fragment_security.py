"""Security and resource exhaustion tests for fragmentation and reassembly."""

from __future__ import annotations

import struct

import pytest

from bitchat.exceptions import (
    FragmentLimitExceededError,
    FragmentPayloadError,
    InvalidFragmentError,
)
from bitchat.protocol.constants import (
    MAX_ACTIVE_ASSEMBLIES,
    MAX_FRAGMENTS_PER_ASSEMBLY,
    MAX_REASSEMBLED_BYTES,
    MessageType,
)
from bitchat.protocol.fragmentation import (
    create_fragment_payload,
    parse_fragment_payload,
)
from bitchat.protocol.reassembly import FragmentReassembler


class TestResourceExhaustionHardening:
    def test_exceeding_max_fragments_per_assembly_rejected(self) -> None:
        assembler = FragmentReassembler(max_fragments_per_assembly=10)
        payload = create_fragment_payload(
            fragment_id=b"12345678",
            index=0,
            total=11,
            original_message_type=MessageType.Message,
            chunk_data=b"chunk",
        )
        with pytest.raises(FragmentLimitExceededError):
            assembler.add_fragment(b"\x01" * 8, payload)

    def test_default_max_fragments_limit_enforced_in_payload_creation(self) -> None:
        with pytest.raises(FragmentLimitExceededError):
            create_fragment_payload(
                fragment_id=b"12345678",
                index=0,
                total=MAX_FRAGMENTS_PER_ASSEMBLY + 1,
                original_message_type=MessageType.Message,
                chunk_data=b"chunk",
            )

    def test_default_max_fragments_limit_enforced_in_payload_parsing(self) -> None:
        # Construct raw payload bytes with total exceeding limit
        raw = (
            struct.pack(
                ">8sHHB",
                b"12345678",
                0,
                MAX_FRAGMENTS_PER_ASSEMBLY + 1,
                int(MessageType.Message),
            )
            + b"data"
        )
        with pytest.raises(FragmentLimitExceededError):
            parse_fragment_payload(raw)

    def test_exceeding_max_reassembled_bytes_rejected(self) -> None:
        assembler = FragmentReassembler(max_reassembled_bytes=100)
        fid = b"BIGCHUNK"
        p0 = create_fragment_payload(fid, 0, 2, MessageType.Message, b"A" * 60)
        assembler.add_fragment(b"\x01" * 8, p0)
        assert assembler.active_assembly_count == 1

        p1 = create_fragment_payload(fid, 1, 2, MessageType.Message, b"B" * 50)
        # 60 + 50 = 110 > 100 max
        with pytest.raises(FragmentLimitExceededError, match="limit"):
            assembler.add_fragment(b"\x01" * 8, p1)
        assert assembler.active_assembly_count == 0

    def test_max_active_assemblies_eviction(self) -> None:
        # Create an assembler with a capacity of 3 active assemblies
        assembler = FragmentReassembler(max_active_assemblies=3)

        # Add initial fragment for 3 separate IDs
        for i in range(3):
            fid = f"FRAG_{i:03d}".encode()
            p = create_fragment_payload(fid, 0, 2, MessageType.Message, b"data")
            assembler.add_fragment(b"\x01" * 8, p)

        assert assembler.active_assembly_count == 3

        # Adding a 4th assembly should evict the oldest (FRAG_000)
        fid_4 = b"FRAG_004"
        p_4 = create_fragment_payload(fid_4, 0, 2, MessageType.Message, b"data")
        assembler.add_fragment(b"\x01" * 8, p_4)

        assert assembler.active_assembly_count == 3

        # Sending the completion fragment for evicted FRAG_000 starts a new assembly,
        # but since index 1 without index 0 won't complete, it will be pending
        p_old_1 = create_fragment_payload(
            b"FRAG_000", 1, 2, MessageType.Message, b"data"
        )
        res = assembler.add_fragment(b"\x01" * 8, p_old_1)
        assert res is None

    def test_repeated_duplicates_do_not_grow_memory(self) -> None:
        assembler = FragmentReassembler()
        fid = b"DUPCHECK"
        p = create_fragment_payload(fid, 0, 5, MessageType.Message, b"same data")

        for _ in range(50):
            assembler.add_fragment(b"\x01" * 8, p)

        assert assembler.active_assembly_count == 1
        # Internal state should only hold 1 chunk
        key = (b"\x01" * 8, fid)
        assert len(assembler._assemblies[key].chunks) == 1
        assert assembler._assemblies[key].total_bytes == len(b"same data")


class TestExceptionContainment:
    """Ensure malformed or adversarial inputs produce controlled project exceptions."""

    def test_corrupted_header_struct_error_not_leaked(self) -> None:
        # 13 bytes but broken/corrupted
        with pytest.raises((InvalidFragmentError, FragmentPayloadError)):
            parse_fragment_payload(b"\x00" * 5)

    def test_invalid_sender_id_type_raises_project_exception(self) -> None:
        assembler = FragmentReassembler()
        payload = create_fragment_payload(
            b"12345678", 0, 2, MessageType.Message, b"data"
        )
        with pytest.raises(InvalidFragmentError):
            assembler.add_fragment(12345, payload)  # type: ignore[arg-type]

    def test_constants_configured_safely(self) -> None:
        assert MAX_FRAGMENTS_PER_ASSEMBLY == 1000
        assert MAX_ACTIVE_ASSEMBLIES == 100
        assert MAX_REASSEMBLED_BYTES == 150_000
