# BitChat — System Requirements & Feature Status (`v0.3.1`)

## 1. System Overview & Architectural Philosophy

**BitChat** (`bitchat-python` `v0.3.1`) is a peer-to-peer encrypted terminal messenger operating over **Bluetooth Low Energy (BLE)** and **Local Area Network (LAN)** transports. It combines a high-performance **Rust native core (`bitchat._bitchat_core`)** built with PyO3 and Maturin with an asynchronous **Python 3.10+ (`asyncio` + `Textual`)** application and terminal UI layer.

### Core Architectural Principles

1. **Decentralized, Zero-Server Operation:** No central servers, cloud relays, accounts, or telemetry.
2. **Hybrid Python + Rust Architecture (`v0.3.1`):** Performance-critical binary packet framing, MTU fragmentation, bounded fragment reassembly, SHA-256 packet deduplication, and store-and-forward queuing execute in compiled Rust (`rust/bitchat-core`), with automatic pure-Python fallback and differential test verification (see [`docs/ROADMAP.md`](ROADMAP.md) for the 7-stage path to a 100% native Rust application).
3. **Strict Layer Isolation:** UI rendering (`bitchat.tui`), session coordination (`bitchat.app`), transport engines (`bitchat.ble`, `bitchat.network`, `bitchat.transport`), mesh routing (`bitchat.mesh`), cryptography (`bitchat.crypto`), and local storage (`bitchat.storage`) communicate through explicit typed interfaces.
4. **Defensive Resource Bounds:** Every network buffer, fragment reassembly state, deduplication table, store-and-forward queue, and TCP listener enforces strict size, count, and TTL bounds.

---

## 2. Module Responsibilities & Boundaries

### 2.1 `rust/bitchat-core` (`bitchat._bitchat_core`) & `bitchat.protocol`
* **Responsibility:** Wire-level binary serialization, deserialization, header validation, MTU-aware packet fragmentation, and bounded fragment reassembly.
* **Implementation (`v0.3.1`):** Accelerated in Rust (`rust/bitchat-core/src/lib.rs`) exposed via `src/bitchat/_native.py`, with pure-Python reference modules in `src/bitchat/protocol/` (`packet.py`, `encoder.py`, `decoder.py`, `fragmentation.py`, `reassembly.py`, `constants.py`).

### 2.2 `bitchat.mesh`
* **Responsibility:** Multi-hop flood routing (`MeshRouter`), SHA-256 `[:16]` packet deduplication (`NativePacketDeduplicator` / `PacketDeduplicator`), per-peer rate limiting (`NativePeerRateLimiter`), and bounded Store-and-Forward buffering (`StoreAndForwardQueue`).

### 2.3 `bitchat.crypto`
* **Responsibility:** `X25519` key agreement, `Ed25519` digital signatures, `ChaCha20-Poly1305` and `AES-256-GCM` authenticated encryption, `HKDF-SHA256`, `PBKDF2-HMAC-SHA256`, `LocalIdentity` management, and the 3-message `Noise_XX_25519_ChaChaPoly_SHA256` handshake and session cipher state machine.

### 2.4 `bitchat.ble`, `bitchat.network` & `bitchat.transport`
* **Responsibility:**
  * **BLE (`bitchat.ble`, `bitchat.transport.bluetooth`):** Dual-role BLE Central (scanning/GATT client via `bleak`) and BLE Peripheral (GATT server & advertising via Windows WinRT and Linux BlueZ D-Bus) using Service UUID `F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C` and Characteristic UUID `A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`.
  * **LAN (`bitchat.network`):** UDP broadcast peer discovery (default port `41234`, every 3.0s) and length-prefixed TCP stream transport (`NativeStreamFramer` / `StreamFramer`, default port `41235`).
  * **Offline (`bitchat.transport.base.OfflineTransport`):** Zero-radio local mode with all network listeners and scanners stopped.

### 2.5 `bitchat.storage` & `bitchat.logging`
* **Responsibility:** Atomic JSON persistence for `config.json` and `identity.json` (`0600` on POSIX, current-user DACL on Windows), cross-process file locking (`identity.json.lock`), Trust-On-First-Use (TOFU) contact fingerprint pinning, and rotating diagnostic file logging (`bitchat.log`) with automatic secret redaction (`SensitiveDataFilter`).

### 2.6 `bitchat.app`, `bitchat.tui` & `bitchat.platform`
* **Responsibility:** `SessionCoordinator` lifecycle and handshake orchestration, headless CLI (`Application`), Textual TUI (`BitchatApp`, `HomeScreen`, `ChatScreen`, `SettingsScreen`, `ConnectionModal`), hardware capability probing (`bitchat --configure`), Windows startup management (`bitchat --startup`), and cross-platform uninstallation (`bitchat --uninstall`).

---

## 3. Functional Requirements (`FR`)

| ID | Category | Requirement Description | Target Module(s) | Status (`v0.3.1`) |
| :--- | :--- | :--- | :--- | :--- |
| **FR-01** | Protocol | Encode and decode the big-endian `BitchatPacket` header (`FIXED_HEADER_SIZE = 14`, `MINIMUM_PACKET_SIZE = 22`: `version`, `message_type`, `ttl`, `timestamp`, `flags`, `payload_len`, `sender_id`, optional `recipient_id`, `payload`, optional `signature`) and PKCS#7-style block padding. | `rust/bitchat-core`, `bitchat.protocol` | ✅ Implemented |
| **FR-02** | Protocol | Support all 22 `MessageType` codes (`0x01` Announce through `0x25` HandshakeRequest). | `rust/bitchat-core`, `bitchat.protocol` | ✅ Implemented |
| **FR-03** | Protocol | Fragment outbound packets exceeding `FRAGMENTATION_THRESHOLD` (`500` bytes) into `150`-byte chunks with 13-byte fragment headers and reassemble inbound fragments (`MAX_FRAGMENTS_PER_ASSEMBLY = 1000`, `MAX_ACTIVE_ASSEMBLIES = 100`, `MAX_REASSEMBLED_BYTES = 150_000`). | `rust/bitchat-core`, `bitchat.protocol` | ✅ Implemented |
| **FR-04** | Crypto | Generate and persist local `X25519` + `Ed25519` keypairs (`LocalIdentity`), deriving the 64-char SHA-256 `fingerprint` and 8-byte `peer_id`. | `bitchat.crypto.identity`, `bitchat.storage` | ✅ Implemented |
| **FR-05** | Crypto | Execute the 3-message `Noise_XX_25519_ChaChaPoly_SHA256` handshake with mutual authentication and post-handshake `peer_id` binding verification. | `bitchat.crypto.noise`, `bitchat.crypto.sessions` | ✅ Implemented |
| **FR-06** | Crypto | Encrypt and authenticate unicast session payloads using `ChaCha20-Poly1305` (with 1,024-entry replay window) and channel/symmetric payloads using `AES-256-GCM`. | `bitchat.crypto.noise`, `bitchat.crypto.aes_gcm` | ✅ Implemented |
| **FR-07** | BLE | Scan for nearby BitChat BLE peers, manage GATT connections, negotiate ATT MTU, and subscribe to characteristic notifications. | `bitchat.ble` | ✅ Implemented |
| **FR-08** | BLE | Host a local BLE Peripheral GATT server and advertise the BitChat Service UUID on Windows (WinRT) and Linux (BlueZ D-Bus). | `bitchat.ble.server`, `bitchat.ble.bluez` | ✅ Implemented |
| **FR-09** | App / UI | Provide both an interactive Textual TUI (`--tui`, default on TTY) and a deterministic headless CLI (`--cli`) with slash command parsing. | `bitchat.tui`, `bitchat.app`, `bitchat.commands` | ✅ Implemented |
| **FR-10** | Mesh | Multi-hop flood routing with configurable hop limit (`max_hops` 1–7, default 3), loop prevention, and SHA-256 `[:16]` deduplication cache. | `rust/bitchat-core`, `bitchat.mesh` | ✅ Implemented |
| **FR-11** | Protocol | End-to-end delivery acknowledgments (`0x05 DeliveryAck`) on packet receipt. | `bitchat.app.session_coordinator` | ✅ Implemented |
| **FR-12** | Protocol | End-to-end read receipts (`0x06 ReadReceipt`) when messages are viewed. | `bitchat.app.session_coordinator` | ✅ Implemented |
| **FR-13** | Storage | Bounded in-memory Store-and-Forward packet queuing (`StoreAndForwardQueue`) for transient peers; persistent on-disk chat history database remains planned for a future release. | `rust/bitchat-core`, `bitchat.mesh.store_forward` | ⚠️ Partial (In-memory S&F ✅; Disk chat history 📋 Planned) |
| **FR-14** | Security | Out-of-band fingerprint verification (`/fingerprint`, `/verify`, `/trust`, `/untrust`), TOFU contact pinning, and `maximum` security mode blocking unverified peers. | `bitchat.storage.config`, `bitchat.app` | ✅ Implemented |
| **FR-15** | Protocol | Native Rust protocol/mesh core (`bitchat._bitchat_core`) and documented wire compatibility with BitChat v1 framing (see [`docs/protocol/COMPATIBILITY.md`](protocol/COMPATIBILITY.md)). | `rust/bitchat-core`, `bitchat.protocol` | ✅ Implemented |
| **FR-16** | Platform | First-class Windows 10 (1809+) & Windows 11 (x64) support, standalone Inno Setup installer, WinGet manifests, and `--startup` management. | `bitchat.platform`, `packaging/windows` | ✅ Implemented |
| **FR-17** | Platform | First-class Linux (x86_64) support via BlueZ / D-Bus, `.deb`, `AppImage`, and `Flatpak` packages. | `bitchat.ble.bluez`, `packaging/linux` | ✅ Implemented |
| **FR-18** | Network | Local Area Network (LAN) transport with UDP broadcast discovery (default port `41234`), length-prefixed TCP connections (default port `41235`), and live runtime switching (`BLE` ↔ `LAN` ↔ `Offline`). | `bitchat.network`, `bitchat.app` | ✅ Implemented |
| **FR-19** | Uninstaller | Built-in cross-platform uninstaller (`bitchat --uninstall`, `--dry-run`, `--remove-user-data`, `--yes`) cleaning standalone binaries, multi-Python console scripts, shortcuts, registry keys, and BitChat-owned `PATH` entries. | `bitchat.platform.uninstaller` | ✅ Implemented |

---

## 4. Non-Functional Requirements (`NFR`)

| ID | Category | Requirement Description | Verification Method | Status (`v0.3.1`) |
| :--- | :--- | :--- | :--- | :--- |
| **NFR-01** | Security | Cryptographic operations must rely on audited primitives (`cryptography` OpenSSL bindings; Rust `sha2`), never custom math. | Code review, `pip-audit`, `bandit` | ✅ Verified |
| **NFR-02** | Security | Private keys (`LocalIdentity`) must never appear in `__repr__`, `__str__`, exception messages, or `bitchat.log` (`SensitiveDataFilter`). | `tests/unit/test_m5_lifecycle_logging.py`, `tests/crypto/test_identity.py` | ✅ Verified |
| **NFR-03** | Security | `~/.bitchat/identity.json` must enforce `0600` permissions on POSIX and a current-user-only DACL on Windows, with cross-process file locking. | `tests/unit/test_storage.py`, `tests/unit/test_identity_persistence.py` | ✅ Verified |
| **NFR-04** | Reliability | Malformed, truncated, or oversized wire frames must raise typed exceptions without crashing the event loop or exhausting memory. | `tests/protocol/test_defensive_bounds.py`, `tests/e2e/` | ✅ Verified |
| **NFR-05** | Performance | Non-blocking `asyncio` event loop: TUI chat updates are frame-coalesced (16 ms), message history trims in O(1), and Rust hot-path codecs run in microseconds. | `tests/unit/test_native_core.py`, `tests/stress/` | ✅ Verified |
| **NFR-06** | Quality | Strict static typing (`pyright` 0 errors), linting (`ruff` 0 warnings), and Rust `clippy -D warnings` + `cargo fmt --check`. | `.github/workflows/ci.yml` | ✅ Verified |
| **NFR-07** | Testing | Comprehensive automated test suite (1,250+ Python unit/integration/e2e/stress tests + 22 Python/Rust differential equivalence tests + 4 Rust unit tests). | `pytest`, `cargo test` | ✅ Verified |
| **NFR-08** | Portability | First-class support on Windows x64 and Linux x86_64; experimental LAN/CLI support on macOS (`PlatformKind.OTHER`). | Multi-OS CI matrix (`windows-latest`, `ubuntu-latest`) | ✅ Verified |
