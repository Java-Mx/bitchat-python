# Architecture

BitChat Python follows a strict layered architecture to maintain separation of concerns and testability.

## Layered Architecture

```
TUI (Textual)
 ↓
Application Core
 ↓
Protocol / Crypto / Storage
 ↓
BLE Transport (Bleak)
 ↓
OS Bluetooth APIs
```

## Module Responsibilities

- **`tui/`**: Terminal UI, display, user input (depends on `app`). Must NOT directly implement BLE or cryptography.
- **`app/`**: Application logic, command handling, state (depends on `protocol`, `crypto`, `storage`, `ble`).
- **`protocol/`**: Packet encoding/decoding, wire models, message types, fragmentation (independent). Must remain independent from presentation.
  - `constants.py`: Wire format sizes, UUIDs, bitmask flags, block sizes, and `MessageType` enum.
  - `packet.py`: Immutable `BitchatPacket` dataclass with normalized immutable `bytes` fields, property accessors, flags, and hex conversion.
  - `encoder.py`: Binary big-endian packet serialization (`encode_packet`) and BitChat random block padding (`pad_packet_data`).
  - `decoder.py`: Strict wire packet deserialization (`decode_packet`) and padding removal (`unpad_packet_data`) with defensive bounds validation.
- **`crypto/`**: Cryptographic primitives, Noise protocol, key management, and identity (independent). Must NOT depend on TUI or BLE.
  - `identity.py`: `LocalIdentity` dataclass managing Ed25519 & X25519 key pairs with safe string representation and 64-char hex fingerprint calculation.
  - `ed25519.py`: Ed25519 digital signature signing and verification with strict size checks.
  - `x25519.py`: X25519 Diffie-Hellman key exchange with Curve25519 low-order point validation.
  - `aes_gcm.py`: AES-256-GCM encryption with 96-bit OS CSPRNG nonces matching the Rust legacy wire layout (`nonce || ciphertext+tag`).
  - `hkdf.py`: Noise custom HMAC-SHA256 multi-output expansion and standard HKDF-SHA256 for legacy exchange.
  - `pbkdf2.py`: PBKDF2-HMAC-SHA256 (100k iterations) for channel password key derivation.
  - `noise.py`: `Noise_XX_25519_ChaChaPoly_SHA256` handshake state machine, symmetric transcript hashing, extracted wire nonces, and 1024-entry replay window.
  - `sessions.py`: `NoiseSession` orchestrating per-peer handshake progression, role assignment, and transport encryption.
- **`storage/`**: Message persistence, identity storage (independent).
- **`ble/`**: BLE scanning, connections, GATT operations (depends on `protocol`). Must NOT depend on TUI.
- **`models/`**: Shared data types (independent, leaf dependency).
- **`utils/`**: Shared utilities (independent, leaf dependency).
- **`commands/`**: CLI command definitions (depends on `app`).

## Protocol Wire Architecture

The `bitchat.protocol` layer provides a decoupled, pure-Python wire encoding and decoding pipeline:

```
BitchatPacket (Data Model)
  │
  ▼ [encode_packet]
Raw Unpadded Wire Bytes (Fixed Header 14B + Sender 8B [+ Recipient 8B] + Payload [+ Signature 64B])
  │
  ▼ [pad_packet_data]
Padded Packet Buffer (Padded to 256 / 512 / 1024 / 2048 bytes with trailing padding count)
```

The reverse flow decodes wire bytes:

```
Wire Bytes Received
  │
  ▼ [unpad_packet_data]
Raw Unpadded Wire Bytes
  │
  ▼ [decode_packet]
BitchatPacket (Validated Data Model)
```

## Dependency Rules
- Higher layers depend on lower layers, never the reverse.
- The TUI must remain a purely presentational layer.
- Core logic (`protocol`, `crypto`) must be isolated and unit-testable without relying on OS-level BLE abstractions.
