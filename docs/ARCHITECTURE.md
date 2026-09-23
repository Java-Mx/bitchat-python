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
  - `constants.py`: Wire format sizes, UUIDs, bitmask flags, block sizes, fragmentation limits, and `MessageType` enum.
  - `packet.py`: Immutable `BitchatPacket` dataclass with normalized immutable `bytes` fields, property accessors, flags, and hex conversion.
  - `encoder.py`: Binary big-endian packet serialization (`encode_packet`) and BitChat random block padding (`pad_packet_data`).
  - `decoder.py`: Strict wire packet deserialization (`decode_packet`) and padding removal (`unpad_packet_data`) with defensive bounds validation.
  - `fragmentation.py`: Packet fragmentation splitting wire-encoded packets exceeding 500 bytes into <=150-byte chunks with 13-byte headers (`FragmentStart`, `FragmentContinue`, `FragmentEnd`).
  - `reassembly.py`: Out-of-order `FragmentReassembler` with sender isolation (`(sender_id, fragment_id)` key), LRU assembly eviction, bounded buffer limits, and strict full-range validation.
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
- **`ble/`**: BLE scanning, connection lifecycle, GATT discovery, fragment pacing, and packet routing via Bleak (depends on `protocol`). Must NOT depend on TUI.
  - `models.py`: `BLEConnectionState` lifecycle enum and `DiscoveredPeer` metadata dataclass.
  - `scanner.py`: `BLEScanner` filtering for BitChat Service UUID (`F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`), duplicate normalization, and peer tracking.
  - `gatt.py`: `GATTManager` resolving service and characteristic (`A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`) with property validation (`write-without-response`, `notify`).
  - `connection.py`: `BLEConnection` state machine managing peer connection, GATT discovery, notification subscription, and disconnect callbacks.
  - `transport.py`: `BLETransport` integrating packet serialization, conditional fragmentation (>500B), 20ms pacing, bounded reception queue, and fragment reassembly.
  - `manager.py`: `BLEManager` high-level coordinator managing scanner lifecycle, multiple active peer connections, direct sending, and broadcast.
- **`models/`**: Shared data types (independent, leaf dependency).
- **`utils/`**: Shared utilities (independent, leaf dependency).
- **`commands/`**: CLI command definitions (depends on `app`).

## BLE Transport Architecture

The `bitchat.ble` package bridges the high-level application and the underlying Bluetooth Low Energy hardware using Bleak:

```
Application Layer
       │  ▲
       ▼  │ (Packets / Events)
   BLEManager
   ├── BLEScanner (Filters BitChat UUID F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C)
   └── dict[address, BLETransport]
            │
            ├── BLEConnection (Lifecycle: Disconnected -> Connecting -> Connected
            │                  -> Discovering GATT -> Subscribing -> Ready)
            ├── GATTManager (Characteristic A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D)
            ├── Outbound Transmission:
            │     - If wire size <= 500B: direct write (response=False)
            │     - If wire size > 500B: fragment into 150B chunks, pace at 20ms interval
            └── Inbound Reception:
                  - Bounded asyncio.Queue (backpressure / drop-on-full protection)
                  - Background worker pulls raw notification bytes
                  - Decodes packet & routes fragments to FragmentReassembler
                  - Delivers reassembled BitchatPacket to application callback
```

### Connection State Machine

1. **`DISCONNECTED`**: No active BLE link.
2. **`CONNECTING`**: Bleak client connecting to peer peripheral.
3. **`CONNECTED`**: Link established; preparing for service discovery.
4. **`DISCOVERING_GATT`**: Validating BitChat Service and Characteristic UUIDs with required properties.
5. **`SUBSCRIBING`**: Subscribing to GATT notifications via `start_notify`.
6. **`READY`**: Fully initialized and bidirectional packet transmission enabled.
7. **`DISCONNECTING`**: Teardown in progress (unsubscribing and disconnecting client).

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
  │
  ▼ (If wire size > 500 bytes)
[fragment_encoded_packet]
  │
  ▼
N Fragment Packets (<=150B data chunks + 13B headers; Start/Continue/End)
  │
  ▼ [encode_packet + pad_packet_data per fragment]
Serialized Wire Fragments for BLE transmission
```

The reverse flow decodes wire bytes, handling both single packets and fragmented packets:

```
Wire Bytes Received
  │
  ▼ [unpad_packet_data + decode_packet]
Fragment Packet (0x05, 0x06, 0x07) or Regular BitchatPacket
  │
  ├─► Regular Packet: Process directly
  │
  └─► Fragment Packet:
        │
        ▼ [reassembler.add_fragment(packet)]
      Accumulate chunk by index under (sender_id, fragment_id)
        │
        ▼ (When all 0..total-1 indices present)
      Reassembled Wire Bytes
        │
        ▼ [unpad_packet_data + decode_packet]
      Original BitchatPacket (Validated Data Model)
```

## Dependency Rules
- Higher layers depend on lower layers, never the reverse.
- The TUI must remain a purely presentational layer.
- Core logic (`protocol`, `crypto`) must be isolated and unit-testable without relying on OS-level BLE abstractions.

## Isolated Prototype Area (`nim/`)

An isolated evaluation area exists under `nim/` to benchmark low-level native performance:
- **Authoritative Core**: Python (`src/bitchat/`) remains the authoritative implementation.
- **FFI Boundary**: Minimal C-ABI dynamic library with caller-allocated memory buffers.
- **Runtime Dependency**: Nim is strictly an experimental evaluation prototype and is **not** a runtime or packaging dependency of `bitchat`.
- **Findings**: Micro-benchmarks confirmed pure Python 3.14 processes 340k–400k packets/sec (4 orders of magnitude above BLE bandwidth); FFI marshalling overhead made hybrid Python+Nim slower than pure Python. Production adoption is rejected in favor of pure-Python portability.
