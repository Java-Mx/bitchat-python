# Requirements

All functional and non-functional requirements below are currently marked as **🚧 Planned**.

## Functional Requirements
- **FR-01**: ✅ Implemented - BLE peer discovery (`bitchat.ble.scanner.BLEScanner`, UUID filtering for `F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`, duplicate normalization)
- **FR-02**: ✅ Implemented - BLE connection management (`bitchat.ble`, lifecycle state machine, GATT discovery for `A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`, notification subscription, 20ms fragment pacing, and reassembly integration)
- **FR-03**: ✅ Implemented - Packet encoding/decoding (`bitchat.protocol`)
- **FR-04**: ✅ Implemented - Fragmentation/reassembly (threshold 500B, 150B chunks, 13B header, out-of-order reassembly with sender isolation & bounded memory)
- **FR-05**: ✅ Implemented - Encryption (`bitchat.crypto`, Noise Protocol XX ChaChaPoly SHA256, AES-256-GCM)
- **FR-06**: ✅ Implemented - Identity and authentication (`LocalIdentity`, Ed25519 signatures, X25519 key verification)
- **FR-07**: ✅ Implemented - Noise session management (`NoiseSession`, extracted nonces, 1024 replay window, tie-breaking)
- **FR-08**: 🚧 Planned - Public channels
- **FR-09**: 🚧 Planned - Private messages
- **FR-10**: 🚧 Planned - Mesh routing
- **FR-11**: 🚧 Planned - Delivery acknowledgements
- **FR-12**: 🚧 Planned - Read receipts
- **FR-13**: 🚧 Planned - Message persistence
- **FR-14**: 🚧 Planned - Terminal UI
- **FR-15**: 🚧 Planned - Rust interoperability
- **FR-16**: 🚧 Planned - Windows support
- **FR-17**: 🚧 Planned - Linux support
- **FR-18**: 🚧 Planned - macOS support

## Non-functional Requirements
- **NFR-01**: 🟡 In Progress - Protocol compatibility with reference implementation (Binary packet format, message types, Noise XX crypto, fragmentation wire format, and BLE UUIDs verified)
- **NFR-02**: ✅ Implemented - Separation of concerns (Layered package architecture enforced)
- **NFR-03**: ✅ Implemented - No cryptographic improvisation (standard `cryptography` primitives, reference-matched parameters, explicit boundaries)
- **NFR-04**: ✅ Implemented - Cross-platform BLE abstraction (Bleak integration with dependency injection enabling hardware-independent testing)
- **NFR-05**: ✅ Implemented - Testability (472 unit, crypto, fragmentation, BLE, security invariant, and protocol equivalence tests passing, strict type checking and linting)
- **NFR-06**: ✅ Implemented - Human-readable code (Documented modules, typed dataclasses)
- **NFR-07**: ✅ Evaluated - Performance prototype & FFI evaluation (isolated Nim prototype evaluated; empirical benchmarks demonstrated Python 3.14 handles 400k packets/sec; FFI marshalling overhead confirmed negative ROI; Python retained as authoritative)
