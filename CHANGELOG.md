# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Phase 9.1: Full Terminal UI Redesign & Design System (`bitchat.tui`):
  - Cohesive edge-to-edge terminal dashboard composition utilizing 100% of viewport with zero wasted margins.
  - Strict 5-family color palette: Black (`#080a0f`, `#0f121c`, `#141824`), Blue (`#58a6ff`, `#388bfd`), Purple (`#bc8cff`, `#a371f7`), Deterministic Peer Identity Colors (8 curated distinct colors with CRC32 hashing), and Restrained Semantic Status (`#3fb950`, `#d29922`, `#f85149`).
  - Dedicated Textual CSS stylesheet (`src/bitchat/tui/styles/app.tcss`) centralizing layout, spacing, borders, focus states, and scrollbars.
  - Panel borders with inline titles (`border-title: "Peers [BLE Mesh]"`, `border-title: "Conversation [#public]"`).
  - Two-tier message rendering in `ChatView` with sender identity anchor in that peer's deterministic color, muted timestamp, and clear message body.
  - Compact 1-line top header (`HeaderWidget`) with branding, channel indicator, and peer/telemetry badges.
  - IDE-quality floating autocomplete palette (`AutocompletePalette`) anchored right above the input bar with real-time prefix filtering and dynamic contextual completion for `/dm <peer>` and `/connect <address>`.
  - Persistent keyboard footer (`StatusBar`) with monospace shortcut guide and operational telemetry.
  - PageUp / PageDown chat scroll keybindings.
  - Responsive layout verified across standard terminal resolutions (`80x24`, `100x30`, `120x40`, `160x50`).
  - Unit test suite expanded to 523 tests with 100% pass rate.
- Phase 9: Mesh Routing, Store-and-Forward, and Modern Textual TUI with Autocompletion:
  - Multi-hop mesh relay engine (`bitchat.mesh.router.MeshRouter`) featuring TTL decrementing, loop prevention, peer rate-limiting (50 pkts/s), destination filtering, and 10–50ms randomized relay jitter to mitigate BLE broadcast collisions.
  - TTL-invariant packet deduplication (`bitchat.mesh.dedup.PacketDeduplicator`) computing SHA-256 hashes over invariant packet fields (`sender_id`, `timestamp`, `message_type`, `recipient_id`, `payload`), bounded LRU cache (2,000 entries), and 300s TTL expiration window.
  - Offline store-and-forward queue (`bitchat.mesh.store_forward.StoreAndForwardQueue`) with strict per-peer limits (20 packets), global queue cap (100 packets), aggregate byte budget (256 KB), and automatic queue flushing upon peer presence announcement.
  - Central command registry (`bitchat.commands.parser`) with prefix-based suggestion lookup, command metadata, argument specifiers, and contextual peer target completion.
  - Complete Textual TUI redesign (`bitchat.tui`) with modular widget architecture:
    - Pure dark GitHub-inspired theme (`#0d1117`, `#161b22`, `#30363d`, `#58a6ff`).
    - Top header widget (`HeaderWidget`) with dynamic BLE connection pill, peer counter, and local ID.
    - Peer sidebar (`PeerSidebar`) with connected peers, discovered nodes, and identity summary.
    - Message stream (`ChatView`) with timestamps, badges (`[Public]`, `[🔒 DM]`, `[System]`, `[Security]`, `[Error]`), and scrollback log.
    - Message input (`MessageInput`) with command history navigation ($\uparrow/\downarrow$) and autocompletion interception.
    - IDE-style floating autocomplete palette (`AutocompletePalette`) with `/` trigger, prefix filtering, arrow key navigation, Tab/Enter acceptance, and Esc dismissal.
    - Bottom status bar (`StatusBar`) with real-time status and shortcut hint legend.
    - Modal help screen (`HelpScreen`) displaying keyboard shortcuts and command reference table.
  - Multi-hop mesh relay integration test ($A \to B \to C$) in `tests/integration/test_end_to_end.py`.
  - Comprehensive unit test suites for mesh subsystem (`tests/unit/test_mesh.py`) and TUI components (`tests/unit/test_tui.py`), expanding test suite to 515 passing tests.
- Phase 8: Two-PC End-to-End Functional Prototype (`bitchat.app`, `bitchat.tui`, `bitchat.ble.server`):
  - GATT peripheral server and advertising (`bitchat.ble.server.BLEServer`) with native Windows WinRT support and injectable mock backends for testing.
  - Asynchronous session coordinator (`bitchat.app.session_coordinator.SessionCoordinator`) orchestrating peer discovery, presence announce exchange, deterministic Noise XX handshake progression, encrypted direct messages, and 20ms fragment pacing for large messages (>500B).
  - Terminal User Interface (`bitchat.tui.app.BitChatApp`) built with Textual, featuring live scrollable message log, active peer discovery sidebar, local identity/fingerprint display, and full slash command integration (`/connect`, `/disconnect`, `/scan`, `/online`, `/name`, `/dm`, `/large`, `/clear`, `/help`, `/exit`).
  - Dual runtime mode in `bitchat.__main__`: automatic interactive TUI when running in a TTY, and headless/scripted CLI mode (`--cli` or piped stdin).
  - Identity persistence in `StorageInterface` (`load_identity`, `save_identity`) storing `LocalIdentity` in `~/.bitchat/identity.json` with restricted file permissions (`0o600` on POSIX).
  - Comprehensive End-to-End integration suite (`tests/integration/test_end_to_end.py`) validating full two-node handshake, direct messaging, 1500B fragmentation/reassembly, and reconnection.
  - Automated integration test suite expanded to 491 tests with 100% passing rate.
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
