# Nim Performance Prototype & FFI Evaluation

This directory contains the experimental Nim prototype and Foreign Function Interface (FFI) evaluation for the BitChat protocol.

> [!IMPORTANT]
> **Authoritative Implementation**: The Python implementation under `src/bitchat/` remains authoritative for all protocol, cryptographic, fragmentation, and session behavior. This directory is strictly an isolated technical evaluation and is **not** a runtime or packaging dependency of `bitchat`.

---

## 1. Prototype Scope

The prototype evaluates low-level byte manipulation for performance-sensitive BitChat protocol layers:
1. **Wire Packet Encoding & Strict Decoding**: Big-endian fixed header packing (14B), Sender/Recipient handling, and payload slicing.
2. **Random Block Padding & Strict Unpadding**: BitChat random block padding (PKCS#7-style delimiter to 256/512/1024/2048 bytes).
3. **Fragmentation**: >500-byte threshold detection, 150-byte MTU chunk slicing, 13-byte fragment metadata header packing/unpacking (`FragmentStart`, `FragmentContinue`, `FragmentEnd`).
4. **Out-of-Order Reassembly**: Sparse assembly collection keyed by `(sender_id, fragment_id)` with sender isolation, duplicate suppression, conflicting fragment rejection, and DoS limits (`MAX_ACTIVE_ASSEMBLIES = 100`, `MAX_FRAGMENTS_PER_ASSEMBLY = 1000`, `MAX_REASSEMBLED_BYTES = 150_000`).
5. **C-ABI FFI Boundary**: Caller-allocated buffer architecture exposed via dynamic library (`bitchat_nim.dll` / `.so`).

---

## 2. Directory Structure

```text
nim/
├── README.md                      # This evaluation report
├── src/
│   ├── bitchat_types.nim          # Protocol constants, MessageType enum, C-ABI error codes
│   ├── bitchat_padding.nim        # Block padding and unpadding implementations
│   ├── bitchat_packet.nim         # Raw packet encoding, decoding, validation
│   ├── bitchat_fragment.nim       # 150B chunking and 13B header packing
│   ├── bitchat_reassembly.nim     # Bounded out-of-order reassembler with sender isolation
│   └── bitchat_ffi.nim            # Exported C-ABI dynamic library entry points
├── tests/
│   ├── test_packet.nim            # Native Nim unit tests for packet and padding
│   └── test_fragment.nim          # Native Nim unit tests for chunking and reassembly
└── benchmarks/
    ├── nim_ffi.py                 # Isolated ctypes adapter for Python integration
    ├── bench_native.nim           # Pure native Nim standalone benchmark binary
    └── bench_comparison.py        # Python vs Python+FFI vs Native Nim comparative runner
```

---

## 3. Build & Test Reproducibility

### Toolchain Requirements
- **Nim Compiler**: `>= 2.0.0` (evaluated on `Nim 2.2.12 [Windows: amd64]`)
- **C Compiler**: GCC / MinGW-w64 (`gcc 11.1.0`) or Clang
- **Python**: `>= 3.12` (evaluated on `Python 3.14.7`)

### Running Native Nim Tests
```bash
nim c -r --nimcache:nim/build/nimcache_packet nim/tests/test_packet.nim
nim c -r --nimcache:nim/build/nimcache_frag nim/tests/test_fragment.nim
```

### Compiling Native FFI Dynamic Library
```bash
# Windows
nim c -d:release --app:lib --opt:speed --passL:-static --nimcache:nim/build/nimcache_dll --out:nim/bin/bitchat_nim.dll nim/src/bitchat_ffi.nim

# Linux / macOS
nim c -d:release --app:lib --opt:speed --nimcache:nim/build/nimcache_dll --out:nim/bin/libbitchat_nim.so nim/src/bitchat_ffi.nim
```

### Running Native Benchmarks
```bash
nim c -d:release --opt:speed --nimcache:nim/build/nimcache_bench --out:nim/bin/bench_native.exe nim/benchmarks/bench_native.nim
./nim/bin/bench_native.exe
```

### Running Comparative Benchmarks
```bash
uv run python nim/benchmarks/bench_comparison.py
```

### Running Python Equivalence Tests
```bash
uv run pytest tests/interoperability/test_nim_equivalence.py -v
```

---

## 4. FFI Architecture & Memory Ownership Model

The Foreign Function Interface is designed to prevent cross-allocator bugs, buffer overflows, and memory leaks:

| Concern | Design Choice | Rationale |
|---|---|---|
| **Input Buffers** | `const uint8_t* in_data, size_t in_len` | Borrowed by Nim; caller retains ownership and buffer lifetime. |
| **Output Buffers** | `uint8_t* out_buf, size_t out_cap, size_t* out_len` | **Caller-allocated**: Nim writes into caller memory. No cross-allocator `malloc`/`free` calls between GCC and Python runtimes. |
| **Stateful Handles** | Opaque pointer (`pointer`) with paired `_new` and `_free` | Reassembler object is managed explicitly by Nim's runtime (`GC_ref` / `GC_unref`). |
| **Error Handling** | Integer status codes (`int32_t`) | `0` = OK, negative values define strict errors (`ERR_BUFFER_TOO_SMALL = -1`, `ERR_INVALID_INPUT = -2`, etc.). |
| **Bounds Checking** | Guarded pointer arithmetic | Every slice is validated against explicit length bounds before copying. |

---

## 5. Protocol Equivalence & Interoperability Results

The test suite in [`tests/interoperability/test_nim_equivalence.py`](file:///d:/bitchat-python/tests/interoperability/test_nim_equivalence.py) verifies 100% byte-for-byte fidelity:
- **Encoding Equivalence**: `encode_packet` (Python) and `nim_encode_packet` (Nim) produce bit-identical wire bytes.
- **Decoding Cross-Compatibility**: Packets encoded in Python decode without error in Nim; packets encoded in Nim decode without error in Python.
- **Header Packing**: The 13-byte fragment metadata header is identical chunk-for-chunk.
- **Cross-Reassembly**: Fragments produced in Python are correctly reassembled by Nim's `NimReassembler`; fragments produced in Nim are correctly reassembled by Python's `FragmentReassembler`.
- **Out-of-Order Support**: Reverse-order and pseudo-random fragment delivery reconstruct identical payloads across both implementations.

---

## 6. Benchmark Methodology & Results

### Environment
- **Platform**: Windows 11 Enterprise (AMD64)
- **CPU**: AMD64 Multi-Core Processor
- **Python**: 3.14.7 (CPython 64-bit)
- **Nim**: 2.2.12 (`-d:release --opt:speed mm:orc threads:on`)
- **C Compiler**: MinGW-w64 GCC 11.1.0 (`-static`)
- **Methodology**: 100 warm-up runs discarded before timing; repeated over 2,000 to 100,000 iterations per workload.

### 1. Pure Native Nim Standalone Performance (`bench_native.exe`)
| Workload | Iterations | Elapsed Time | Ops/sec | Throughput |
|---|---|---|---|---|
| **Small Packet Encode (64B)** | 50,000 | 39.49 ms | 1,266,050 | 77.27 MB/s |
| **Medium Packet Encode (256B)** | 50,000 | 48.11 ms | 1,039,216 | 253.71 MB/s |
| **Large Packet Encode (800B)** | 20,000 | 15.52 ms | 1,288,593 | 983.12 MB/s |
| **Boundary Evaluation (499/500/501B)** | 600,000 | 1.44 ms | 417,740,026 | 199,193 MB/s |
| **Chunk Slicing (600B -> 4 chunks)** | 20,000 | 8.52 ms | 2,347,418 | 1,343.20 MB/s |
| **Chunk Slicing (1500B -> 10 chunks)** | 10,000 | 12.81 ms | 780,500 | 1,116.51 MB/s |
| **Reassembly In-Order (10 chunks)** | 5,000 | 37.67 ms | 132,719 | 189.86 MB/s |
| **Reassembly Randomized (10 chunks)** | 5,000 | 32.03 ms | 156,111 | 223.32 MB/s |

### 2. Python vs. Python + Nim FFI Comparative Performance (`bench_comparison.py`)
| Workload | Iterations | Pure Python Time (Ops/s) | Python+FFI Time (Ops/s) | Speedup (FFI vs Python) |
|---|---|---|---|---|
| **Small Packet Encode (64B)** | 20,000 | 49.59 ms (403,339 ops/s) | 117.57 ms (170,107 ops/s) | **0.42x** (2.4x slower) |
| **Medium Packet Encode (256B)** | 20,000 | 58.27 ms (343,210 ops/s) | 157.00 ms (127,388 ops/s) | **0.37x** (2.7x slower) |
| **Large Packet Encode (800B)** | 10,000 | 27.76 ms (360,210 ops/s) | 85.41 ms (117,085 ops/s) | **0.33x** (3.0x slower) |
| **Chunk Slicing & Header (600B)** | 20,000 | 22.60 ms (884,952 ops/s) | 334.49 ms (59,792 ops/s) | **0.07x** (14.3x slower) |
| **Chunk Slicing & Header (1500B)** | 10,000 | 18.95 ms (527,713 ops/s) | 407.50 ms (24,540 ops/s) | **0.05x** (20.0x slower) |
| **Reassembly In-Order (10 frags)** | 2,000 | 66.15 ms (30,236 ops/s) | 804.77 ms (2,485 ops/s) | **0.08x** (12.5x slower) |
| **Reassembly Shuffled (10 frags)** | 2,000 | 54.10 ms (36,966 ops/s) | 727.74 ms (2,748 ops/s) | **0.07x** (14.3x slower) |

---

## 7. FFI Overhead & Performance Analysis

The benchmark data yields a clear technical finding:
1. **Pure Native Nim is Fast**: In standalone native compilation, Nim processes over 1.2 million packet encodings/sec and over 130,000 reassembly cycles/sec.
2. **Pure Python is Already Extremely Fast**: Python's native binary processing using `struct.pack`, slicing, and hash dictionaries achieves 340,000–400,000 packet encodings/sec and 30,000–37,000 reassemblies/sec.
3. **FFI Call Marshalling Eliminates All Gains**: Calling Nim from Python across `ctypes` incurs an overhead of ~1.5–2.0 microseconds per call (boxing/unboxing C parameters, creating buffer pointers, crossing foreign function boundaries).
4. **Fine-Grained Operations Suffer Worst**: In fragmentation and reassembly, where an operation requires 4 to 10 separate chunk calls, the cumulative FFI overhead reduces performance by **93% to 95%** compared to pure Python.

---

## 8. Physical Layer Context (BLE Throughput)

BitChat operates over Bluetooth Low Energy (BLE):
- Typical BLE GATT notification transfer rate: **10 to 100 packets per second**.
- BitChat specification mandates a **20 ms inter-fragment sleep delay** between consecutive fragment transmissions, capping transmission throughput at a maximum of **50 fragments per second** per connection.
- At 50 packets per second, Python's existing wire protocol implementation consumes less than **0.015%** of a single CPU core.
- Wire packet processing is not a bottleneck in BitChat. The real physical bottlenecks are BLE radio bandwidth, GATT MTU negotiation, OS Bluetooth daemon latency, and connection intervals.

---

## 9. Production Decision & Recommendation

### Recommendation: Do NOT adopt Nim in production.

**Technical Rationale:**
1. **Negative Performance Impact via FFI**: Introducing Nim via FFI into the Python application makes packet encoding and reassembly **2.4x to 20x slower** due to foreign function boundary crossing costs.
2. **No Real-World Bottleneck**: Python already encodes 400,000 packets/sec—four orders of magnitude faster than the BLE transport layer can transmit them (50 packets/sec).
3. **Packaging & Portability Burden**: Requiring Nim and a C compiler (GCC/Clang) creates huge cross-compilation friction for Windows, macOS, and Linux wheels, breaking pure-Python `uv pip install` simplicity.
4. **Dual Maintenance Cost**: Maintaining protocol logic in both Nim and Python creates synchronization risk and double maintenance overhead without any user-facing benefit.

**Conclusion**: Keep Python as the 100% authoritative, unified implementation for BitChat. The Nim prototype has served its purpose as an objective, empirical evaluation and should remain archived in `nim/` for future reference.
