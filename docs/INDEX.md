# BitChat Documentation Index

Welcome to the central documentation index for **BitChat** (`v0.3.1`), a peer-to-peer encrypted terminal messenger powered by a hybrid Python and Rust (`bitchat._bitchat_core`) architecture over Bluetooth Low Energy (BLE) and Local Area Network (LAN) transports.

---

## 1. Getting Started & User Guides

| Document | Description |
| :--- | :--- |
| [`README.md`](../README.md) | Project overview, feature highlights, quick-start installation, TUI/CLI usage, and architecture summary. |
| [`docs/DOWNLOAD.md`](DOWNLOAD.md) | Official download links, SHA-256 verification instructions, and package formats for `v0.3.1`. |
| [`docs/UNINSTALLATION.md`](UNINSTALLATION.md) | Complete guide to uninstalling BitChat across Windows, Linux, and Python environments (`pip`, `uv`, `pipx`), including `PATH` cleanup and optional user-data removal. |
| [`SUPPORT.md`](../SUPPORT.md) | Diagnostic commands (`bitchat --configure`), log file locations, troubleshooting steps, and how to get help. |
| [`Screenshot.md`](../Screenshot.md) | Visual gallery of the BitChat Textual Terminal UI (Home Screen, Chat Screen, Settings, Connection Modal, Help). |
| [`CHANGELOG.md`](../CHANGELOG.md) | Chronological release history and detailed changelog through `v0.3.1`. |

---

## 2. Platform-Specific Guides

| Document | Platform Status & Scope |
| :--- | :--- |
| [`docs/platform/WINDOWS.md`](platform/WINDOWS.md) | **First-Class Support (Windows 10/11 x64):** Standalone Inno Setup installer, WinGet, WinRT BLE Central/Peripheral requirements, Windows Firewall ports, startup management (`--startup`), and uninstallation. |
| [`docs/platform/LINUX.md`](platform/LINUX.md) | **First-Class Support (Linux x86_64):** `.deb`, `AppImage`, `Flatpak`, BlueZ / D-Bus configuration, permissions (`bluetooth` group / capabilities), and firewall configuration. |
| [`docs/platform/MACOS.md`](platform/MACOS.md) | **Experimental / Partial Support (macOS):** Source installation, LAN transport support, and current `CoreBluetooth` BLE Peripheral limitations. |

---

## 3. Architecture, Engineering & Roadmap

| Document | Description |
| :--- | :--- |
| [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | Hybrid Python + Rust (`bitchat._bitchat_core`) system architecture, layer boundaries, threading/asyncio model, and component design. |
| [`docs/ROADMAP.md`](ROADMAP.md) | 7-stage engineering roadmap from the current hybrid Python/Rust core (`v0.3.1`) through the ~60% Rust milestone to a 100% native Rust application. |
| [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) | Functional (`FR-*`) and Non-Functional (`NFR-*`) requirements matrix with current `v0.3.1` implementation status. |
| [`docs/DEVELOPMENT.md`](DEVELOPMENT.md) | Developer environment setup (`uv`, Rust `cargo`, `maturin`), testing, linting, benchmarking, and debugging guide. |
| [`docs/RELEASE_PROCESS.md`](RELEASE_PROCESS.md) | Release engineering workflow, version synchronization checklist, CI/CD pipelines, packaging scripts, and artifact verification. |

---

## 4. Binary Protocol & Mesh Specifications

| Document | Description |
| :--- | :--- |
| [`docs/protocol/OVERVIEW.md`](protocol/OVERVIEW.md) | High-level overview of the BitChat v1 binary wire protocol, BLE GATT UUIDs, LAN framing, and Rust/Python module mapping. |
| [`docs/protocol/PACKET_FORMAT.md`](protocol/PACKET_FORMAT.md) | Byte-level specification of the big-endian `BitchatPacket` header (`FIXED_HEADER_SIZE = 14`, `MINIMUM_PACKET_SIZE = 22`), flags, and PKCS#7-style block padding. |
| [`docs/protocol/MESSAGE_TYPES.md`](protocol/MESSAGE_TYPES.md) | Complete specification of the protocol `MessageType` codes (`0x01`–`0x25`) and their inner payload formats. |
| [`docs/protocol/FRAGMENTATION.md`](protocol/FRAGMENTATION.md) | MTU-aware packet fragmentation (`> 500` bytes), 13-byte fragment headers, inter-fragment pacing, and bounded reassembly (`NativeFragmentReassembler`). |
| [`docs/protocol/ROUTING.md`](protocol/ROUTING.md) | Multi-hop flood routing, TTL bounds, SHA-256 deduplication cache (`NativePacketDeduplicator`), peer rate limiting (`NativePeerRateLimiter`), and Store-and-Forward buffering (`StoreAndForwardQueue`). |
| [`docs/protocol/COMPATIBILITY.md`](protocol/COMPATIBILITY.md) | Interoperability status between BitChat Python/Rust (`v0.3.1`) and external BitChat reference implementations, including post-handshake peer ID binding differences. |

---

## 5. Security, Privacy & Legal Documentation

| Document | Description |
| :--- | :--- |
| [`SECURITY.md`](../SECURITY.md) | Private vulnerability reporting policy, supported versions, audit status, and matrix of implemented protections vs. known limitations. |
| [`docs/security/CRYPTOGRAPHY.md`](security/CRYPTOGRAPHY.md) | Cryptographic primitives (`X25519`, `Ed25519`, `AES-256-GCM`, `HKDF-SHA256`, `PBKDF2-HMAC-SHA256`) and identity key derivation. |
| [`docs/security/NOISE.md`](security/NOISE.md) | `Noise_XX_25519_AESGCM_SHA256` 3-message mutual authentication handshake and transport encryption state machine. |
| [`docs/security/THREAT_MODEL.md`](security/THREAT_MODEL.md) | Adversary threat model, trust boundaries, TOFU vs. `maximum` security mode, and residual risks. |
| [`docs/security/DATA_HANDLING.md`](security/DATA_HANDLING.md) | Technical inventory of local files (`~/.bitchat/`), network broadcasts, in-memory retention, and deletion semantics. |
| [`PRIVACY_POLICY.md`](../PRIVACY_POLICY.md) | Official project Privacy Policy (Draft for publisher/legal review; plain-text installer copy at [`packaging/windows/legal/PRIVACY_POLICY.txt`](../packaging/windows/legal/PRIVACY_POLICY.txt)). |
| [`TERMS_OF_USE.md`](../TERMS_OF_USE.md) | Terms of Use & Operational Notice supplementing the MIT License (Draft for publisher/legal review; plain-text installer copy at [`packaging/windows/legal/TERMS_OF_USE.txt`](../packaging/windows/legal/TERMS_OF_USE.txt)). |
| [`LICENSE`](../LICENSE) | Full text of the MIT License governing the repository. |

---

## 6. Community & Packaging Reference

| Document | Description |
| :--- | :--- |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution workflow, code style, Rust/Python test requirements, and pull request guidelines. |
| [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | Contributor Covenant Code of Conduct and enforcement reporting procedures. |
| [`packaging/linux/flatpak/README.md`](../packaging/linux/flatpak/README.md) | Building and running the Linux Flatpak bundle (`io.github.java_mx.bitchat`). |
| [`packaging/linux/snap/README.md`](../packaging/linux/snap/README.md) | Building and running the Linux Snap package (`snapcraft.yaml`). |
| [`nim/README.md`](../nim/README.md) | Historical note on the archived pre-Rust Nim FFI prototype (superseded by `rust/bitchat-core`). |
