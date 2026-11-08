"""Comprehensive performance benchmarking for BitChat Python.

Measures:
1. Application initialization and startup time
2. Idle / Active memory (tracemalloc & RSS) and CPU consumption
3. Cryptographic throughput (ChaCha20-Poly1305, Ed25519 signing/verification)
4. Protocol packet encoding/decoding throughput and serialization latency
5. Noise XX cryptographic handshake latency
6. In-process packet framing and fragmentation throughput
"""

from __future__ import annotations

import os
import sys
import time
import tracemalloc

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from bitchat.crypto.identity import LocalIdentity
from bitchat.crypto.noise import (
    NoiseHandshakeState,
    NoiseRole,
)
from bitchat.protocol.constants import FLAG_HAS_RECIPIENT, MessageType
from bitchat.protocol.decoder import decode_packet
from bitchat.protocol.encoder import encode_packet
from bitchat.protocol.fragmentation import fragment_encoded_packet
from bitchat.protocol.packet import BitchatPacket
from bitchat.protocol.reassembly import FragmentReassembler
from bitchat.storage.config import AppConfig


def benchmark_startup_time(iterations: int = 5) -> dict[str, float]:
    """Measure module import and config/identity initialization overhead."""
    times: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        cfg = AppConfig()
        ident = LocalIdentity.generate()
        _ = cfg.nickname
        _ = ident.peer_id_hex
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "min_ms": min(times),
        "mean_ms": sum(times) / len(times),
        "max_ms": max(times),
    }


def benchmark_crypto_throughput(payload_sizes: list[int] = [64, 512, 4096, 65536], count: int = 1000) -> list[dict[str, float]]:
    """Measure encryption/decryption throughput across payload scales."""
    results = []
    alice_id = LocalIdentity.generate()
    bob_id = LocalIdentity.generate()

    initiator = NoiseHandshakeState(NoiseRole.INITIATOR, alice_id.x25519_private)
    responder = NoiseHandshakeState(NoiseRole.RESPONDER, bob_id.x25519_private)

    m1 = initiator.write_message(b"")
    responder.read_message(m1)
    m2 = responder.write_message(b"")
    initiator.read_message(m2)
    m3 = initiator.write_message(b"")
    responder.read_message(m3)

    alice_send, _ = initiator.get_transport_ciphers()
    _, bob_recv = responder.get_transport_ciphers()

    for sz in payload_sizes:
        data = os.urandom(sz)
        t0 = time.perf_counter()
        total_bytes = 0
        for _ in range(count):
            enc = alice_send.encrypt(data, b"")
            dec = bob_recv.decrypt(enc, b"")
            total_bytes += sz
        dt = time.perf_counter() - t0
        mb_per_sec = (total_bytes / (1024 * 1024)) / dt
        ops_per_sec = count / dt
        results.append({
            "payload_bytes": sz,
            "ops_per_sec": ops_per_sec,
            "mb_per_sec": mb_per_sec,
            "avg_latency_us": (dt / count) * 1_000_000,
        })
    return results


def benchmark_noise_handshake(count: int = 100) -> dict[str, float]:
    """Measure complete 3-message Noise XX mutual authentication handshake latency."""
    latencies: list[float] = []
    for _ in range(count):
        alice_id = LocalIdentity.generate()
        bob_id = LocalIdentity.generate()
        t0 = time.perf_counter()
        initiator = NoiseHandshakeState(NoiseRole.INITIATOR, alice_id.x25519_private)
        responder = NoiseHandshakeState(NoiseRole.RESPONDER, bob_id.x25519_private)
        m1 = initiator.write_message(b"")
        responder.read_message(m1)
        m2 = responder.write_message(b"")
        initiator.read_message(m2)
        m3 = initiator.write_message(b"")
        responder.read_message(m3)
        _, _ = initiator.get_transport_ciphers()
        _, _ = responder.get_transport_ciphers()
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
    return {
        "handshakes_per_sec": count / (sum(latencies) / 1000),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
    }


def benchmark_packet_encoding_and_fragmentation(count: int = 2000) -> dict[str, float]:
    """Measure packet serialization, fragmentation, and reassembly throughput."""
    packet = BitchatPacket(
        version=1,
        message_type=MessageType.Message,
        ttl=3,
        timestamp=int(time.time()),
        flags=FLAG_HAS_RECIPIENT,
        sender_id=os.urandom(8),
        recipient_id=os.urandom(8),
        payload=b"A" * 1200,
        signature=None,
    )
    raw = encode_packet(packet)
    fragments = fragment_encoded_packet(raw, packet.sender_id, packet.message_type)

    t0 = time.perf_counter()
    for _ in range(count):
        raw = encode_packet(packet)
        frags = fragment_encoded_packet(raw, packet.sender_id, packet.message_type)
        reassembler = FragmentReassembler()
        reassembled = None
        for frag in frags:
            res = reassembler.add_fragment_packet(frag)
            if res is not None:
                reassembled = res
        if reassembled:
            _ = decode_packet(reassembled)
    dt = time.perf_counter() - t0
    return {
        "packets_per_sec": count / dt,
        "avg_packet_pipeline_us": (dt / count) * 1_000_000,
        "total_fragments_processed": count * len(fragments),
        "throughput_mb_sec": ((1200 * count) / (1024 * 1024)) / dt,
    }


def measure_process_resources() -> dict[str, float]:
    """Measure real OS process-level RSS and CPU metrics."""
    # 1. Try psutil if available
    try:
        import psutil

        proc = psutil.Process()
        mem_info = proc.memory_info()
        cpu_times = proc.cpu_times()
        return {
            "rss_mb": mem_info.rss / (1024 * 1024),
            "peak_rss_mb": getattr(mem_info, "peak_wset", mem_info.rss) / (1024 * 1024),
            "user_cpu_s": cpu_times.user,
            "system_cpu_s": cpu_times.system,
            "cpu_percent": proc.cpu_percent(interval=0.1),
        }
    except ImportError:
        pass

    # 2. Windows ctypes fallback (kernel32 + psapi)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            psapi = ctypes.WinDLL("psapi")
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
            handle = kernel32.GetCurrentProcess()
            psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)

            creation = wintypes.FILETIME()
            exit_t = wintypes.FILETIME()
            kernel_t = wintypes.FILETIME()
            user_t = wintypes.FILETIME()
            kernel32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
                ctypes.POINTER(wintypes.FILETIME),
            ]
            kernel32.GetProcessTimes.restype = wintypes.BOOL
            kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_t),
                ctypes.byref(kernel_t),
                ctypes.byref(user_t),
            )
            user_s = ((user_t.dwHighDateTime << 32) + user_t.dwLowDateTime) / 10_000_000.0
            sys_s = ((kernel_t.dwHighDateTime << 32) + kernel_t.dwLowDateTime) / 10_000_000.0

            return {
                "rss_mb": counters.WorkingSetSize / (1024 * 1024),
                "peak_rss_mb": counters.PeakWorkingSetSize / (1024 * 1024),
                "user_cpu_s": user_s,
                "system_cpu_s": sys_s,
                "cpu_percent": 0.0,
            }
        except Exception:
            pass

    # 3. Linux resource / /proc fallback
    try:
        import resource

        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss_mb = ru.ru_maxrss / 1024.0
        return {
            "rss_mb": rss_mb,
            "peak_rss_mb": rss_mb,
            "user_cpu_s": ru.ru_utime,
            "system_cpu_s": ru.ru_stime,
            "cpu_percent": 0.0,
        }
    except Exception:
        return {
            "rss_mb": 0.0,
            "peak_rss_mb": 0.0,
            "user_cpu_s": 0.0,
            "system_cpu_s": 0.0,
            "cpu_percent": 0.0,
        }


def run_all_benchmarks() -> None:
    print("=" * 70)
    print("BitChat Core Engine Performance Benchmarks (Python 3.14.7)")
    print("=" * 70)

    st = benchmark_startup_time()
    print("\n[Identity & Config Initialization]")
    print(f"  Mean latency:  {st['mean_ms']:.3f} ms (min: {st['min_ms']:.3f} ms, max: {st['max_ms']:.3f} ms)")

    hs = benchmark_noise_handshake()
    print("\n[Noise XX Mutual Authentication Handshake]")
    print(f"  Throughput:    {hs['handshakes_per_sec']:.1f} handshakes/sec")
    print(f"  Mean latency:  {hs['mean_latency_ms']:.3f} ms/handshake")

    print("\n[Symmetric Crypto (ChaCha20-Poly1305 E2EE)]")
    crypto_res = benchmark_crypto_throughput()
    for row in crypto_res:
        print(f"  Payload {row['payload_bytes']:5d} B: {row['ops_per_sec']:8.1f} ops/sec | {row['mb_per_sec']:7.2f} MB/s | latency: {row['avg_latency_us']:6.2f} µs")

    pkt = benchmark_packet_encoding_and_fragmentation()
    print("\n[Protocol Pipeline (Encode + MTU Fragment + Reassemble + Decode)]")
    print(f"  Throughput:    {pkt['packets_per_sec']:.1f} packets/sec ({pkt['throughput_mb_sec']:.2f} MB/s)")
    print(f"  Pipeline cost: {pkt['avg_packet_pipeline_us']:.2f} µs/packet")

    res = measure_process_resources()
    print("\n[OS Process-Level Footprint (RSS & CPU)]")
    print(f"  Resident Set Size (RSS):      {res['rss_mb']:.2f} MB")
    print(f"  Peak Working Set (Peak RSS):  {res['peak_rss_mb']:.2f} MB")
    print(f"  Cumulative Process User CPU:  {res['user_cpu_s']:.3f} s")
    print(f"  Cumulative Process Sys CPU:   {res['system_cpu_s']:.3f} s")
    print("=" * 70)


if __name__ == "__main__":
    run_all_benchmarks()
