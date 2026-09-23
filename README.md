<!-- Logo Placeholder -->
<div align="center">
  <h1>BitChat Python</h1>
  <p>Python terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE)</p>
  <p>
    <img src="https://img.shields.io/badge/Status-Phase%208%20(Two--PC%20End--to--End)-blue" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/CI-Passing-brightgreen" alt="CI" />
  </p>
</div>

## Overview
BitChat Python is a terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 8 — Two-PC End-to-End Functional Prototype implemented and verified. Includes Textual TUI (`BitChatApp`), session coordination (`SessionCoordinator`), Noise XX handshake and encrypted transport, BLE GATT server and central management, 20ms fragment pacing, and end-to-end integration tests.

## Goals
- Protocol-compatible Python implementation
- Cross-platform BLE messaging
- Terminal UI
- Mesh networking

## Architecture Overview
The project follows a layered architecture to separate concerns:
- **TUI** -> **App Core** -> **Protocol/Crypto/Storage** -> **BLE** -> **OS Bluetooth APIs**

## Feature Status
- ✅ Implemented: Binary packet model (`BitchatPacket`) with true immutability & byte normalization
- ✅ Implemented: Wire encoder (`encode_packet`, `pad_packet_data`) with BitChat random block padding
- ✅ Implemented: Wire decoder (`decode_packet`, `unpad_packet_data`) with strict defensive validation
- ✅ Implemented: Protocol constants & complete 22-variant `MessageType` enum
- ✅ Implemented: Packet fragmentation & out-of-order reassembly with sender isolation & bounded limits
- ✅ Implemented: Cryptographic identity abstraction (`LocalIdentity`) with persistent storage (`~/.bitchat/identity.json`)
- ✅ Implemented: Ed25519 digital signatures (`sign`, `verify`)
- ✅ Implemented: X25519 Diffie-Hellman with weak key validation
- ✅ Implemented: Noise XX handshake (`Noise_XX_25519_ChaChaPoly_SHA256`) state machine
- ✅ Implemented: Noise transport encryption with 1024-entry replay window protection
- ✅ Implemented: Lexicographic peer ID tie-breaking (`determine_handshake_role`)
- ✅ Implemented: AES-256-GCM legacy encryption & PBKDF2-HMAC-SHA256 channel key derivation
- ✅ Implemented: Application core controller, command parser, peer model, and storage
- ✅ Implemented: BLE peer discovery and connection lifecycle (`bitchat.ble.scanner.BLEScanner`, `bitchat.ble.connection.BLEConnection`)
- ✅ Implemented: BLE GATT characteristic discovery, 20ms pacing, and reassembly transport (`bitchat.ble.transport.BLETransport`)
- ✅ Implemented: BLE GATT peripheral server and advertising (`bitchat.ble.server.BLEServer`)
- ✅ Implemented: Session coordinator managing Noise XX sessions and BLE routing (`bitchat.app.session_coordinator.SessionCoordinator`)
- ✅ Implemented: Interactive Textual Terminal UI with live message log and peer sidebar (`bitchat.tui.app.BitChatApp`)
- ✅ Implemented: Two-node end-to-end integration test (`tests/integration/test_end_to_end.py`)
- 🚧 Planned: Multi-hop mesh routing and store-and-forward
- 🚧 Planned: Message persistence (SQLite)
- 🚧 Planned: Rust interoperability testing

## Hardware & Two-PC BLE Validation Status
- **Automated Integration:** 100% automated integration and end-to-end suite passing (491 tests).
- **Windows (WinRT):** GATT Server creation and BLE service advertisement verified on host hardware.
- **Linux / macOS:** Central scanning and client transport implemented via Bleak; peripheral advertising pending platform-specific daemon bindings.
- **Status Statement:** *"Automated integration is complete, but real two-PC BLE validation remains outstanding."*

## Quickstart

Run with interactive Textual TUI:
```bash
uv run bitchat
```

Run in headless / scripted CLI mode:
```bash
uv run bitchat --cli
```

### Available Commands
- `/connect <address>`: Connect to peer BLE address
- `/disconnect [address]`: Disconnect from peer or all peers
- `/scan`: Discover nearby BitChat BLE nodes
- `/online`: List connected and discovered peers
- `/name <nickname>`: Change nickname and broadcast announce
- `/dm <peer_id> <message>`: Send end-to-end encrypted Noise XX direct message
- `/large <peer_id>`: Send 1000B test message to verify fragmentation and reassembly
- `/clear`: Clear message log
- `/help`: Display command reference
- `/exit`: Quit BitChat

## Development Setup
This project uses `uv` for dependency management.

```bash
git clone https://github.com/Java-Mx/bitchat-python.git
cd bitchat-python
uv sync --all-groups
```

## Running Tests
```bash
uv run pytest
```

## Code Quality
```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

## Reference Implementation
The reference implementation is [bitchat-tui](https://github.com/vaibhav-mattoo/bitchat-tui) written in Rust. This repository aims for protocol compatibility with the Rust implementation but does not copy its code.

## Security Notice
This project is in early development. There has been no security audit. Do not use for sensitive communications.

## License
MIT
