<!-- Logo Placeholder -->
<div align="center">
  <h1>BitChat Python</h1>
  <p>Python terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE)</p>
  <p>
    <img src="https://img.shields.io/badge/Status-Phase%2010%20(TUI%20Harden%20%26%20Integration)-blue" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/Tests-563%20Passing-brightgreen" alt="Tests" />
    <img src="https://img.shields.io/badge/Type%20Check-Pyright%20Strict-blue" alt="Type Check" />
  </p>
</div>

## Overview
BitChat Python is an asynchronous terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 10 — Strict Functional Repair, TUI Interaction Hardening, and Full-System Integration complete and verified. Features an edge-to-edge terminal dashboard composition utilizing 100% of the viewport, an authoritative dynamic keybinding subsystem with atomic configuration persistence, runtime appearance customization (density, timestamps, accent palettes), centered panel titles, non-shifting borderless buttons, standard IDE-style command completion, natural `@peer` direct messaging / context switching, multi-hop mesh routing with store-and-forward delivery, and 563 passing automated tests.

## Goals
- Protocol-compatible Python implementation with Noise XX handshake and binary packet wire spec
- Cross-platform BLE messaging (central client + peripheral GATT server)
- Modern, professional terminal UI with dynamic keybindings and appearance customization
- Multi-hop mesh networking with deduplication, jitter, and store-and-forward delivery
- Full verification through automated execution traces (Action -> Event -> State -> UI -> Persistence)

## Architecture Overview
The project follows a modular layered architecture:
```text
TUI Layer (Textual App, Widgets, Modals, Autocomplete Palette)
  │
  ▼
Application Core (SessionCoordinator, CommandParser, AppConfig, FileStorage)
  │
  ▼
Mesh Layer (MeshRouter, PacketDeduplicator, StoreAndForwardQueue)
  │
  ▼
Security & Cryptography (Noise XX, Ed25519, X25519, AES-256-GCM, HKDF)
  │
  ▼
Protocol Layer (BitchatPacket, Encoder, Decoder, Fragmenter, Reassembler)
  │
  ▼
BLE Transport (BLEManager, BLEScanner, BLEConnection, BLETransport, BLEServer)
  │
  ▼
Operating System Bluetooth APIs (WinRT / Bleak)
```

## Feature Status
- ✅ Implemented: Binary packet model (`BitchatPacket`) with immutability, validation, and byte normalization
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
- ✅ Implemented: Centralized command registry with prefix matching and argument metadata (`bitchat.commands.parser`)
- ✅ Implemented: BLE peer discovery and connection lifecycle (`bitchat.ble.scanner.BLEScanner`, `bitchat.ble.connection.BLEConnection`)
- ✅ Implemented: BLE GATT characteristic discovery, 20ms pacing, and reassembly transport (`bitchat.ble.transport.BLETransport`)
- ✅ Implemented: BLE GATT peripheral server and advertising (`bitchat.ble.server.BLEServer`)
- ✅ Implemented: Multi-hop mesh routing (`bitchat.mesh.router.MeshRouter`) with TTL decrementing, anti-looping, and 10–50ms randomized jitter
- ✅ Implemented: TTL-invariant packet deduplication (`bitchat.mesh.dedup.PacketDeduplicator`) with bounded 2,000-entry LRU and 300s TTL cache
- ✅ Implemented: Store-and-forward queue (`bitchat.mesh.store_forward.StoreAndForwardQueue`) with per-peer limits, byte budget, and automatic flushing upon peer announce
- ✅ Implemented: Session coordinator integrating Noise XX sessions, mesh routing, and BLE transport (`bitchat.app.session_coordinator.SessionCoordinator`)
- ✅ Implemented: Full Terminal UI (`bitchat.tui`) with dark midnight surfaces (`#080a0f`, `#0f121c`), centered panel titles (`border-title-align: center;`), and dedicated stylesheet (`styles/app.tcss`)
- ✅ Implemented: Authoritative dynamic keybinding system (`apply_keybindings`) with live duplicate conflict detection, empty-key rejection, and default key restoration
- ✅ Implemented: Atomic configuration persistence (`AppConfig`, `FileConfigStorage`) saving identity, appearance, and custom keymaps to `~/.bitchat/config.json`
- ✅ Implemented: Appearance & theme customization screen (`EditThemeModal`) supporting density switching (comfortable / compact), timestamp toggling, and 4 accent palettes (Midnight Blue, Cyber Cyan, Terminal Emerald, Amethyst Purple)
- ✅ Implemented: Modal screen stack manager with toggle behavior (`F1`, `F2`, `F3`), clean modal context swapping, and deduplication of repeated BLE error dialogues
- ✅ Implemented: IDE-style anchored command palette (`AutocompletePalette`) with non-submitting Tab/Enter completion, prefix filtering, and contextual peer suggestions
- ✅ Implemented: Conversation context switching (`@peer` with no message) and direct encrypted messaging (`@peer <message>`)
- ✅ Implemented: Safe peer address and nickname resolution supporting 16-hex peer IDs and BLE MAC prefixes
- ✅ Implemented: 563 automated test cases covering protocol, crypto, fragmentation, mesh routing, store-and-forward, BLE mocks, and full interactive TUI lifecycle
- 🚧 Planned: Persistent message database (SQLite)
- 🚧 Planned: Physical multi-PC over-the-air validation on two real Bluetooth machines

## Hardware & Two-PC BLE Validation Status
- **Automated Integration:** 100% automated integration and end-to-end suite passing (563 tests, including two-node Noise XX and three-node multi-hop mesh relay).
- **Windows (WinRT):** GATT Server creation and BLE service advertisement verified on host hardware.
- **Linux / macOS:** Central scanning and client transport implemented via Bleak; peripheral advertising pending platform-specific daemon bindings.
- **Physical Hardware Status:** *"Automated integration, simulated multi-node mesh tests, and interactive TUI lifecycle probes are 100% passing. Real two-PC physical over-the-air BLE validation remains UNVERIFIED pending availability of a second physical machine."*

## Quickstart

Run with interactive Textual TUI:
```bash
uv run bitchat
```

Run in headless / scripted CLI mode:
```bash
uv run bitchat --cli
```

### Keyboard Shortcuts (Default)
| Key | Action | Description |
|---|---|---|
| `F1` | Show Help | Open help dialogue and command list (toggle) |
| `F2` | Appearance / Theme | Open appearance, density, and accent editor (toggle) |
| `F3` | Settings | Open node parameters and keybinding editor (toggle) |
| `Ctrl+L` | Clear Chat | Clear current conversation history |
| `Ctrl+Q` | Quit | Gracefully shut down BitChat |
| `PageUp` | Scroll Up | Scroll conversation history up |
| `PageDown`| Scroll Down | Scroll conversation history down |
| `Escape` | Dismiss | Close any open modal or dismiss autocomplete palette |

*All keybindings can be customized in the Settings screen (`F3` or `/settings`) and are saved to `~/.bitchat/config.json`.*

### Available Commands
- `/connect [address|peer]`: Connect to peer BLE address or list discovered peers
- `/disconnect [address]`: Disconnect from peer or all peers
- `/scan`: Discover nearby BitChat BLE nodes
- `/online`: List connected and discovered peers
- `/name <nickname>`: Change nickname and broadcast announce
- `/dm <peer> <message>`: Send end-to-end encrypted Noise XX direct message
- `@<peer> <message>`: Inline direct message syntax
- `@<peer>`: Switch active conversation context to direct chat with peer
- `/public`: Switch active conversation context back to `#public`
- `/settings`: Open node settings and keybinding manager
- `/edit`: Open appearance & theme editor
- `/status`: Show network & security diagnostics
- `/info <peer>`: Inspect peer public key fingerprint and crypto state
- `/large <peer>`: Send 1000B test message to verify fragmentation and reassembly
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
This project is in active development. There has been no formal security audit. Do not use for high-risk communications.

## License
MIT
