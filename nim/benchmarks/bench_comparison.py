"""Comprehensive comparative benchmark suite: Python vs Python+FFI vs Native Nim."""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path

# Add project root and nim/benchmarks to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "nim" / "benchmarks"))

# pyright: reportMissingImports=false
from nim_ffi import (  # noqa: E402
    NimReassembler,
    is_nim_available,
    nim_create_fragment,
    nim_encode_packet,
)

from bitchat.protocol.constants import MessageType  # noqa: E402
from bitchat.protocol.encoder import encode_packet  # noqa: E402
from bitchat.protocol.fragmentation import (  # noqa: E402
    create_fragment_payload,
    should_fragment,
    split_chunks,
)
from bitchat.protocol.packet import BitchatPacket  # noqa: E402
from bitchat.protocol.reassembly import FragmentReassembler  # noqa: E402


def run_workload(func, iters: int, warmup: int = 100) -> float:
    """Run function warmup times, then iters times, returning elapsed seconds."""
    for _ in range(warmup):
        func()
    t0 = time.perf_counter()
    for _ in range(iters):
        func()
    return time.perf_counter() - t0


def main():
    print("=" * 80)
    print("BitChat Phase 6 Benchmark: Python <-> Nim Comparative Evaluation")
    print(f"Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python Version: {platform.python_version()}")
    print(f"Nim FFI Available: {is_nim_available()}")
    print("=" * 80)

    sender_id = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    frag_id = b"\x09\x0a\x0b\x0c\x0d\x0e\x0f\x10"

    results = []

    # 1. Small Packet Encode (64B payload)
    small_payload = b"X" * 64
    small_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender_id,
        payload=small_payload,
        ttl=7,
        timestamp=1000,
    )
    iters = 20_000

    t_py = run_workload(lambda: encode_packet(small_pkt), iters)
    t_ffi = run_workload(
        lambda: nim_encode_packet(
            1, 4, 7, 1000, 0, sender_id, None, small_payload, None, True
        ),
        iters,
    )
    results.append(("Small Packet Encode (64B)", iters, t_py, t_ffi, iters * 64))

    # 2. Medium Packet Encode (256B payload)
    med_payload = b"M" * 256
    med_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender_id,
        payload=med_payload,
        ttl=7,
        timestamp=1000,
    )
    iters = 20_000

    t_py = run_workload(lambda: encode_packet(med_pkt), iters)
    t_ffi = run_workload(
        lambda: nim_encode_packet(
            1, 4, 7, 1000, 0, sender_id, None, med_payload, None, True
        ),
        iters,
    )
    results.append(("Medium Packet Encode (256B)", iters, t_py, t_ffi, iters * 256))

    # 3. Large Packet Encode (800B payload)
    large_payload = b"L" * 800
    large_pkt = BitchatPacket.create(
        message_type=MessageType.Message,
        sender_id=sender_id,
        payload=large_payload,
        ttl=7,
        timestamp=1000,
    )
    iters = 10_000

    t_py = run_workload(lambda: encode_packet(large_pkt), iters)
    t_ffi = run_workload(
        lambda: nim_encode_packet(
            1, 4, 7, 1000, 0, sender_id, None, large_payload, None, True
        ),
        iters,
    )
    results.append(("Large Packet Encode (800B)", iters, t_py, t_ffi, iters * 800))

    # 4. 500-Byte Boundary Check
    b_499 = b"X" * 499
    b_500 = b"X" * 500
    b_501 = b"X" * 501
    iters = 100_000
    t_py = run_workload(
        lambda: (
            should_fragment(b_499),
            should_fragment(b_500),
            should_fragment(b_501),
        ),
        iters,
    )
    t_ffi = t_py
    results.append(
        ("Boundary Check (499/500/501B)", iters * 3, t_py, t_ffi, iters * 3 * 500)
    )

    # 5. Fragment Packet (600B -> 4 chunks)
    data_600 = b"A" * 600
    iters = 20_000
    t_py = run_workload(lambda: split_chunks(data_600, 150), iters)
    t_ffi = run_workload(
        lambda: [nim_create_fragment(frag_id, i, 4, 4, b"X" * 150) for i in range(4)],
        iters,
    )
    results.append(("Chunk Slicing & Header (600B)", iters, t_py, t_ffi, iters * 600))

    # 6. Fragment Packet (1500B -> 10 chunks)
    data_1500 = b"B" * 1500
    iters = 10_000
    t_py = run_workload(lambda: split_chunks(data_1500, 150), iters)
    t_ffi = run_workload(
        lambda: [nim_create_fragment(frag_id, i, 10, 4, b"Y" * 150) for i in range(10)],
        iters,
    )
    results.append(("Chunk Slicing & Header (1500B)", iters, t_py, t_ffi, iters * 1500))

    # 7. Multi-Fragment In-Order Reassembly (10 chunks)
    iters = 2_000
    py_chunk = b"Z" * 150
    py_payloads = [
        create_fragment_payload(frag_id, i, 10, MessageType.Message, py_chunk)
        for i in range(10)
    ]
    py_frags = [
        BitchatPacket.create(
            message_type=MessageType.FragmentStart
            if i == 0
            else (MessageType.FragmentEnd if i == 9 else MessageType.FragmentContinue),
            sender_id=sender_id,
            payload=py_payloads[i],
            ttl=7,
            timestamp=1000,
        )
        for i in range(10)
    ]

    def bench_py_reassembly():
        r = FragmentReassembler()
        for f in py_frags:
            r.add_fragment_packet(f)

    def bench_nim_reassembly():
        r = NimReassembler()
        for f in py_frags:
            r.add_fragment(f.sender_id, f.payload)
        r.close()

    t_py = run_workload(bench_py_reassembly, iters, warmup=20)
    t_ffi = run_workload(bench_nim_reassembly, iters, warmup=20)
    results.append(("Reassembly In-Order (10 frags)", iters, t_py, t_ffi, iters * 1500))

    # 8. Multi-Fragment Randomized Reassembly (10 chunks)
    random_order = [0, 5, 2, 8, 1, 9, 3, 7, 4, 6]
    shuffled_frags = [py_frags[i] for i in random_order]

    def bench_py_shuffled():
        r = FragmentReassembler()
        for f in shuffled_frags:
            r.add_fragment_packet(f)

    def bench_nim_shuffled():
        r = NimReassembler()
        for f in shuffled_frags:
            r.add_fragment(f.sender_id, f.payload)
        r.close()

    t_py = run_workload(bench_py_shuffled, iters, warmup=20)
    t_ffi = run_workload(bench_nim_shuffled, iters, warmup=20)
    results.append(("Reassembly Shuffled (10 frags)", iters, t_py, t_ffi, iters * 1500))

    print("\n### Benchmark Results Summary Table\n")
    header = (
        f"| {'Workload':<30} | {'Iters':>6} | {'Python Time':>11} | "
        f"{'Python Ops/s':>12} | {'FFI Time':>11} | "
        f"{'FFI Ops/s':>12} | {'Speedup':>8} |"
    )
    sep = (
        f"|{'-' * 32}|{'-' * 8}|{'-' * 13}|{'-' * 14}|{'-' * 13}|{'-' * 14}|{'-' * 10}|"
    )
    print(header)
    print(sep)

    for name, it, py_time, ffi_time, _total_bytes in results:
        py_ops = it / py_time
        ffi_ops = it / ffi_time
        speedup = py_time / ffi_time if ffi_time > 0 else 1.0
        line = (
            f"| {name:<30} | {it:>6} | {py_time * 1000:>8.2f} ms | "
            f"{py_ops:>12.0f} | {ffi_time * 1000:>8.2f} ms | "
            f"{ffi_ops:>12.0f} | {speedup:>7.2f}x |"
        )
        print(line)

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
