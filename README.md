<!-- Logo Placeholder -->
<div align="center">
  <h1>BitChat Python</h1>
  <p>Python terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE)</p>
  <p>
    <img src="https://img.shields.io/badge/Status-Phase%209.1%20(Full%20TUI%20Redesign)-blue" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/CI-Passing-brightgreen" alt="CI" />
  </p>
</div>

## Overview
BitChat Python is a terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 9.1 — Full Terminal UI Redesign & Design System implemented and verified. Features an edge-to-edge terminal dashboard composition utilizing 100% of the viewport, a strict 5-family color palette (Black, Blue, Purple, Deterministic Peer Colors, and Restrained Semantic Status), dedicated Textual CSS stylesheet (`styles/app.tcss`), panel borders with inline titles (`border-title: "Peers [BLE Mesh]"`, `border-title: "Conversation [#public]"`), two-tier message typography, IDE-quality anchored command palette with dynamic prefix filtering and contextual `/dm <peer>` peer suggestions, multi-hop mesh routing with store-and-forward delivery, and 523 passing automated tests.

## Goals
- Protocol-compatible Python implementation
- Cross-platform BLE messaging
- Modern, professional terminal UI with IDE-style command completion
- Multi-hop mesh networking with store-and-forward delivery

## Architecture Overview
The project follows a layered architecture to separate concerns:
- **TUI** -> **App Core / Session Coordinator** -> **Mesh Router** -> **Protocol/Crypto/Storage** -> **BLE Transport** -> **OS Bluetooth APIs**

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
- ✅ Implemented: Centralized command registry with prefix matching and argument metadata (`bitchat.commands.parser`)
- ✅ Implemented: BLE peer discovery and connection lifecycle (`bitchat.ble.scanner.BLEScanner`, `bitchat.ble.connection.BLEConnection`)
- ✅ Implemented: BLE GATT characteristic discovery, 20ms pacing, and reassembly transport (`bitchat.ble.transport.BLETransport`)
- ✅ Implemented: BLE GATT peripheral server and advertising (`bitchat.ble.server.BLEServer`)
- ✅ Implemented: Multi-hop mesh routing (`bitchat.mesh.router.MeshRouter`) with TTL decrementing, anti-looping, and 10–50ms randomized jitter
- ✅ Implemented: TTL-invariant packet deduplication (`bitchat.mesh.dedup.PacketDeduplicator`) with bounded 2,000-entry LRU and 300s TTL cache
- ✅ Implemented: Store-and-forward queue (`bitchat.mesh.store_forward.StoreAndForwardQueue`) with per-peer limits, byte budget, and automatic flushing upon peer announce
- ✅ Implemented: Session coordinator integrating Noise XX sessions, mesh routing, and BLE transport (`bitchat.app.session_coordinator.SessionCoordinator`)
- ✅ Implemented: Full Terminal UI Redesign (`bitchat.tui`) with 5-family palette, dark midnight surfaces (`#080a0f`, `#0f121c`), subtle round borders with inline titles, and dedicated stylesheet (`styles/app.tcss`)
- ✅ Implemented: Deterministic peer identity color generator (`get_peer_color`) mapping peer identifiers to stable colors across sidebar, chat, and suggestions
- ✅ Implemented: IDE-style command palette (`AutocompletePalette`) anchored above prompt with `/` trigger, prefix filtering, arrow navigation, Tab/Enter completion, Esc dismissal, and contextual peer suggestions
- ✅ Implemented: Two-tier conversation view (`ChatView`) with sender identity anchors, muted timestamps, and scroll page keybindings
- ✅ Implemented: Modal help screen (`HelpScreen`) displaying command table and keybinding reference
- ✅ Implemented: Multi-hop mesh relay integration test ($A \to B \to C$) and comprehensive TUI unit test suite (523 tests passing)
- 🚧 Planned: Persistent message database (SQLite)
- 🚧 Planned: Full physical multi-PC over-the-air validation on two real Bluetooth machines

## Hardware & Two-PC BLE Validation Status
- **Automated Integration:** 100% automated integration and end-to-end suite passing (523 tests, including two-node Noise XX and three-node multi-hop mesh relay).
- **Windows (WinRT):** GATT Server creation and BLE service advertisement verified on host hardware.
- **Linux / macOS:** Central scanning and client transport implemented via Bleak; peripheral advertising pending platform-specific daemon bindings.
- **Status Statement:** *"Automated integration and simulated multi-node mesh tests are complete, but real two-PC physical BLE validation remains outstanding pending a second physical machine."*

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
