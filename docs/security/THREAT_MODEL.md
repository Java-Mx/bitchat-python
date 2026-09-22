# Threat Model

This document outlines the threat model for `bitchat-python`, covering the network environment, trust assumptions, threat vectors, and defense mechanisms. It specifically details defenses implemented at the binary packet layer (Phase 3 & Hardening) as well as planned defenses for upcoming cryptographic layers (Phase 4).

---

## 1. Network Environment & Assumptions

BitChat operates primarily over Bluetooth Low Energy (BLE) and ad-hoc wireless mesh networks. In this environment:

- **Unauthenticated Physical Broadcast:** Any entity within BLE radio range can passively sniff raw packets or actively inject crafted radio packets.
- **Untrusted Relays:** In mesh routing, intermediate hops forward packets on behalf of other nodes. Relays cannot be assumed to be honest; they may inspect, drop, replay, mutate, or inject packets.
- **Resource Constraints:** Devices running the client may be resource-constrained battery-powered units or mobile terminals vulnerable to CPU or memory exhaustion attacks.

---

## 2. Threat Vectors & Packet Layer Defenses

### 2.1 Adversarial / Malformed Wire Inputs
- **Threat:** An attacker transmits truncated, corrupt, or maliciously crafted binary payloads designed to crash the client, trigger unhandled exceptions, or cause denial of service.
- **Defenses Implemented (Phase 3 Hardened):**
  - **Exhaustive Pre-Slice Bounds Checking:** `decode_packet()` computes exact minimum header lengths (13 bytes basic, 21 with recipient, 77 with signature, 85 with both) and checks `len(data)` before attempting any slicing or decoding.
  - **Strict Integer Validation:** Header fields (`version`, `ttl`, `flags`, `timestamp`, `payload_len`) are validated strictly against their permissible ranges. Python `bool` types are explicitly rejected from integer fields.
  - **Bounded Memory Allocation:** Payload bytes are extracted only up to the declared payload length after validating that sufficient bytes exist. The decoder never allocates unbounded memory based on untrusted length headers.
  - **Defensive Exception Hierarchy:** The decoder never leaks internal Python exceptions (`IndexError`, `KeyError`, `struct.error`, `ValueError`, `TypeError`). All parsing failures are cleanly mapped to `PacketDecodingError` or its subclasses (`InsufficientPacketBytesError`, `InvalidPacketError`, `CorruptPaddingError`).

### 2.2 In-Place Buffer Mutation Leaks
- **Threat:** Callers or other application components pass mutable buffers (such as `bytearray` or `memoryview`) into a `BitchatPacket`. Subsequent mutation of that buffer could alter packet fields post-validation or during transmission, compromising internal state integrity.
- **Defenses Implemented (Phase 3 Hardened):**
  - **Complete Immutability:** `BitchatPacket` is a frozen dataclass (`@dataclass(frozen=True)`). In `__post_init__`, all byte fields (`sender_id`, `recipient_id`, `payload`, `signature`) are explicitly cast to immutable Python `bytes` via `object.__setattr__`.
  - **Defensive Isolation:** In-place mutations on the original source buffer after constructing the packet have zero effect on the internal packet data.

### 2.3 Traffic Analysis & Packet Sizing
- **Threat:** Passive eavesdroppers analyze packet lengths on the wire to infer message types, lengths, or conversation activity even when payloads are encrypted.
- **Defenses Implemented (Phase 3 Hardened):**
  - **BitChat Random Block Padding:** Payloads are padded to pseudo-random block sizes (typically 128-byte increments) using PKCS#7-style length delimiters.
  - **Strict Padding Integrity:** The Python decoder verifies that padding length bytes match expected block alignment and does not permit arbitrary corrupt padding bytes.

### 2.4 Replay & Routing Loop Attacks
- **Threat:** Adversaries resend captured packets to flood the mesh or cause nodes to process redundant data.
- **Defenses Implemented / Architecture:**
  - **TTL Bounds:** Packets enforce a Time-to-Live (`ttl` $\in [0, 255]$). Relays decrement TTL, dropping packets when TTL reaches zero.
  - **Timestamp Integrity:** Packets include a 64-bit millisecond timestamp (`uint64_be`) enabling receivers to reject stale packets outside an acceptance window.
  - **Deduplication:** Upper layers maintain a sliding window of recent message hashes to discard duplicate packets.

### 2.5 Reserved Bits & Protocol Evolution
- **Threat:** Forward-compatibility issues where future protocol features (using reserved flag bits `0x08`, `0x10`, `0x20`, `0x40`, `0x80`) cause clients to crash or reject legitimate traffic.
- **Defenses Implemented (Phase 3 Hardened):**
  - **Reserved Flag Preservation:** Encoder and decoder preserve reserved flag bits rather than masking or rejecting them, allowing forward-compatible interoperability with newer BitChat versions.

---

## 3. Cryptographic Threat Vectors (Phase 4 Roadmap)

The following threats are addressed at the cryptographic layer in Phase 4:

| Threat Vector | Target Protocol Mechanism | Status |
|---|---|---|
| **Eavesdropping on Direct Messages** | Noise XX Handshake & ChaCha20-Poly1305 AEAD | Planned (Phase 4) |
| **Sender Impersonation / Spoofing** | Ephemeral Ed25519 payload signatures (`FLAG_HAS_SIGNATURE`) | Planned (Phase 4) |
| **Channel Message Eavesdropping** | PBKDF2-HMAC-SHA256 (100k iter) + AES-256-GCM | Planned (Phase 4) |
| **Legacy Direct Message Decryption** | X25519 ECDH + HKDF-SHA256 + AES-256-GCM | Planned (Phase 4) |
| **Key Compromise via State Storage** | Identity key-derived AES-256-GCM encryption of stored passwords | Planned (Phase 4) |
