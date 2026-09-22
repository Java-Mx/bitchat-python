# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
