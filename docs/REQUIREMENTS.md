# Requirements

All functional and non-functional requirements below are currently marked as **🚧 Planned**.

## Functional Requirements
- **FR-01**: 🚧 Planned - BLE peer discovery
- **FR-02**: 🚧 Planned - BLE connection management
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
- **NFR-01**: 🟡 In Progress - Protocol compatibility with reference implementation (Binary packet format, message types, Noise XX crypto, and fragmentation wire format verified)
- **NFR-02**: ✅ Implemented - Separation of concerns (Layered package architecture enforced)
- **NFR-03**: ✅ Implemented - No cryptographic improvisation (standard `cryptography` primitives, reference-matched parameters, explicit boundaries)
- **NFR-04**: 🚧 Planned - Cross-platform BLE abstraction
- **NFR-05**: ✅ Implemented - Testability (435 unit, crypto, fragmentation, and security invariant tests passing, strict type checking and linting)
- **NFR-06**: ✅ Implemented - Human-readable code (Documented modules, typed dataclasses)
