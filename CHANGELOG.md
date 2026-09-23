# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Bluetooth Low Energy (BLE) transport layer (`bitchat.ble`):
  - Service and characteristic discovery matching BitChat UUID specification (`F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C` and `A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`) with case-insensitive matching across platform backends.
  - Asynchronous BLE scanner (`BLEScanner`) filtering for the BitChat service UUID, duplicate address deduplication, and RSSI tracking.
  - Connection lifecycle state machine (`BLEConnection`) with states `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCOVERING_GATT`, `SUBSCRIBING`, `READY`, and `DISCONNECTING`, including unexpected remote disconnect callbacks.
  - GATT discovery manager (`GATTManager`) validating required characteristic properties (`write-without-response`, `notify`).
  - BLE transport (`BLETransport`) handling direct writes (`response=False`), automatic packet fragmentation (>500B) with 20ms inter-fragment pacing matching the reference implementation, decoupled background receive worker, bounded `asyncio.Queue` reception with backpressure protection, and automatic out-of-order fragment reassembly.
  - Central BLE manager (`BLEManager`) coordinating scanner, active multi-peer connections, unicast sending, and broadcast delivery.
  - BLE exception hierarchy (`BLEError`, `BLEScanError`, `BLEConnectionError`, `BLEGATTError`, `BLETransportError`).
  - Hardware-independent mock suite and unit tests (`tests/ble/`) covering scanning, connection transitions, GATT validation, pacing, queue backpressure, malformed packet isolation, and multi-peer dispatch (472 total project tests passing).
- Experimental Nim performance prototype and FFI evaluation (`nim/`):
  - Isolated prototype area implementing byte-level packet encode/decode validation, BitChat random block padding/unpadding, 150-byte chunk slicing, 13-byte fragment header packing, and bounded out-of-order reassembly with sender isolation.
  - Caller-allocated C-ABI FFI boundary (`bitchat_nim.dll` / `.so`) with strict buffer bounds and zero cross-runtime heap allocations.
  - Native unit tests (`test_packet.nim`, `test_fragment.nim`) and comprehensive Python-Nim equivalence test suite (`tests/interoperability/test_nim_equivalence.py`, 445 total project tests passing).
  - Comparative benchmark suite (`bench_native.nim`, `bench_comparison.py`) measuring pure Python, Python+FFI, and native Nim across realistic payloads and fragment topologies.
  - Technical evaluation report and architectural decision documentation (`nim/README.md`) recommending rejection of production Nim integration due to FFI marshalling overhead and Python 3.14's sufficient native performance (400k packets/sec).
- BitChat packet fragmentation and reassembly layer (`bitchat.protocol`):
  - Fragmentation engine (`fragmentation.py`): conditional thresholding at >500 bytes (`FRAGMENTATION_THRESHOLD`), chunk size 150 bytes (`FRAGMENT_CHUNK_SIZE`), 13-byte metadata header encoding (`fragment_id`, `index`, `total`, `original_type`), outer fragment packet generation (`FragmentStart`, `FragmentContinue`, `FragmentEnd`), and strict handling of two-fragment edge case.
  - Reassembly engine (`reassembly.py`): `FragmentReassembler` supporting out-of-order fragment arrivals, per-sender isolation via `(sender_id, fragment_id)` composite keys, LRU active assembly eviction (`MAX_ACTIVE_ASSEMBLIES`), chunk count limits (`MAX_FRAGMENTS_PER_ASSEMBLY`), byte caps (`MAX_REASSEMBLED_BYTES`), duplicate chunk rejection, conflicting metadata validation, and automatic assembly cleanup upon completion.
  - Fragmentation exceptions hierarchy (`FragmentationError`, `InvalidFragmentError`, `FragmentPayloadError`, `FragmentLimitExceededError`).
  - Comprehensive test suite for fragmentation, out-of-order reassembly, resource exhaustion defense, and Rust interoperability (435 total tests passing).
- Cryptographic layer and identity foundation (`bitchat.crypto`):
  - Digital signature module (`ed25519`): raw 32-byte key handling, strict size verification, and signing/verification using `cryptography` hazard-free primitives.
  - Diffie-Hellman key exchange module (`x25519`): shared secret derivation and strict low-order/weak point validation matching the 8 known bad points from the Rust reference.
  - Symmetric encryption (`aes_gcm`): AES-256-GCM authenticated encryption/decryption with OS CSPRNG 96-bit random nonces matching Rust wire format (`nonce || ciphertext+tag`).
  - Key derivation functions (`hkdf`): dual HKDF modules containing `noise_hkdf` (Rust-compatible custom HMAC-SHA256 multi-output chain) and `legacy_hkdf` (standard HKDF-SHA256).
  - Channel key derivation (`pbkdf2`): PBKDF2-HMAC-SHA256 with 100,000 iterations and channel-name salt matching `EncryptionService::derive_channel_key`.
  - Noise protocol (`noise`): complete `Noise_XX_25519_ChaChaPoly_SHA256` implementation including `NoiseCipherState` with 4-byte LE extracted wire nonces, 1024-entry sliding replay window, `NoiseSymmetricState`, and three-stage `NoiseHandshakeState`.
  - Tie-breaking mechanism (`determine_handshake_role`): lexicographic comparison of peer ID hex strings matching `notification_handlers.rs`.
  - Session lifecycle abstraction (`sessions.py`): high-level `NoiseSession` supporting full handshake negotiation, secure state transitions, and transport encryption.
  - Local identity management (`identity.py`): immutable `LocalIdentity` dataclass with safe representation preventing secret exposure in strings or logs.
  - Comprehensive test suite for crypto primitives, invariants, and interoperability vectors (374 total tests passing).
- BitChat binary packet protocol implementation (`bitchat.protocol`):
  - `BitchatPacket` dataclass representing binary packet structures with validation, property flags, and factory method.
  - Wire packet encoder (`encode_packet`, `pad_packet_data`, `get_optimal_block_size`) adhering to big-endian serialization and BitChat random block padding (PKCS#7-style length delimiter).
  - Wire packet decoder (`decode_packet`, `unpad_packet_data`) with defensive bounds checking, version enforcement, and strict padding validation.
  - Protocol constants and full 22-variant `MessageType` IntEnum matching the reference implementation.
  - Protocol exceptions hierarchy (`ProtocolError`, `PacketEncodingError`, `PacketDecodingError`, `UnsupportedProtocolVersionError`, `UnknownMessageTypeError`, `InvalidPacketError`).
  - Comprehensive unit and adversarial test suites with security invariant verification (186 total tests passing).
- Initial repository foundation (Phase 0).
- Application core controller, command parser, peer model, and storage interface (Phase 2).

### Changed
- Hardened `BitchatPacket` immutability by normalizing all binary fields (`sender_id`, `recipient_id`, `payload`, `signature`) to immutable `bytes` on construction, preventing in-place mutations from external `bytearray` sources.
- Hardened integer field validations in `BitchatPacket` to explicitly reject `bool` values.
- Updated block padding terminology throughout documentation and docstrings to "BitChat random block padding (PKCS#7-style length delimiter)".
- Documented intentional defensive parsing difference in Python decoder (strict padding-length consistency verification vs. reference parser's permissive stripping).
- Clarified signature field documentation: wire placement is implemented, while signing semantics are verified in the cryptographic interoperability phase.
