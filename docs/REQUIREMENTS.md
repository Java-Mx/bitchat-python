# Requirements

All functional and non-functional requirements below are currently marked as **🚧 Planned**.

## Functional Requirements
- **FR-01**: 🚧 Planned - BLE peer discovery
- **FR-02**: 🚧 Planned - BLE connection management
- **FR-03**: ✅ Implemented - Packet encoding/decoding (`bitchat.protocol`)
- **FR-04**: 🚧 Planned - Fragmentation/reassembly
- **FR-05**: 🚧 Planned - Encryption (Noise Protocol Framework)
- **FR-06**: 🚧 Planned - Identity and authentication
- **FR-07**: 🚧 Planned - Noise session management
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
- **NFR-01**: 🟡 In Progress - Protocol compatibility with reference implementation (Binary packet format & message types verified)
- **NFR-02**: ✅ Implemented - Separation of concerns (Layered package architecture enforced)
- **NFR-03**: 🚧 Planned - No cryptographic improvisation
- **NFR-04**: 🚧 Planned - Cross-platform BLE abstraction
- **NFR-05**: ✅ Implemented - Testability (112 unit tests passing, strict type checking and linting)
- **NFR-06**: ✅ Implemented - Human-readable code (Documented modules, typed dataclasses)
