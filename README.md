<!-- Logo Placeholder -->
<div align="center">
  <h1>BitChat Python</h1>
  <p>Python terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE)</p>
  <p>
    <img src="https://img.shields.io/badge/Status-Phase%203%20(Binary%20Packet%20Protocol)-blue" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/CI-Passing-brightgreen" alt="CI" />
  </p>
</div>

## Overview
BitChat Python is a terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 3 — BitChat Binary Packet Layer implemented and hardened (immutable packet data structures with normalized bytes, defensive wire decoding, wire encoding, random block padding with PKCS#7-style length delimiter, protocol constants, and comprehensive security invariant test suite).

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
- ✅ Implemented: Application core controller, command parser, peer model, and storage
- 🚧 Planned: BLE peer discovery and connection (Phase 5)
- 🚧 Planned: Cryptography and Noise Protocol (Phase 4)
- 🚧 Planned: Public channels and private messages
- 🚧 Planned: Mesh routing
- 🚧 Planned: Message persistence (SQLite)
- 🚧 Planned: Terminal UI (Textual)
- 🚧 Planned: Cross-platform BLE support
- 🚧 Planned: Rust interoperability testing

## Supported Platforms
- Windows (🚧 Planned / UNTESTED)
- Linux (🚧 Planned / UNTESTED)
- macOS (🚧 Planned / UNTESTED)

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

## Project Structure
```text
bitchat-python/
├── src/
│   └── bitchat/       # Application code
├── tests/             # Test suite
├── docs/              # Documentation
├── README.md
├── CONTRIBUTING.md
└── pyproject.toml
```

## Reference Implementation
The reference implementation is [bitchat-tui](https://github.com/vaibhav-mattoo/bitchat-tui) written in Rust. This repository aims for protocol compatibility with the Rust implementation but does not copy its code.

## Security Notice
This project is in early development. There has been no security audit. Do not use for sensitive communications.

## Contributing
Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License
MIT
