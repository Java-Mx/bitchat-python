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
- **`protocol/`**: Packet encoding/decoding, message types, fragmentation (independent). Must remain independent from presentation.
- **`crypto/`**: Encryption, Noise protocol, key management (independent). Must NOT depend on TUI.
- **`storage/`**: Message persistence, identity storage (independent).
- **`ble/`**: BLE scanning, connections, GATT operations (depends on `protocol`). Must NOT depend on TUI.
- **`models/`**: Shared data types (independent, leaf dependency).
- **`utils/`**: Shared utilities (independent, leaf dependency).
- **`commands/`**: CLI command definitions (depends on `app`).

## Dependency Rules
- Higher layers depend on lower layers, never the reverse.
- The TUI must remain a purely presentational layer.
- Core logic (`protocol`, `crypto`) must be isolated and unit-testable without relying on OS-level BLE abstractions.
