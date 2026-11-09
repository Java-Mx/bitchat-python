# Technical Data Handling & Storage Inventory (`v0.3.1`)

This document provides the code-verified technical inventory of all data created, stored, transmitted, or deleted by **BitChat (`v0.3.1`)**. It serves as the engineering companion to [`PRIVACY_POLICY.md`](../../PRIVACY_POLICY.md) and [`SECURITY.md`](../../SECURITY.md).

---

## 1. Local Filesystem Storage Inventory

By default, BitChat stores all persistent per-user files inside `~/.bitchat/` (`Path.home() / ".bitchat"`):

- **Windows:** `%USERPROFILE%\.bitchat\` (e.g., `C:\Users\<username>\.bitchat\`)
- **Linux:** `/home/<username>/.bitchat/`
- **macOS:** `/Users/<username>/.bitchat/`

### 1.1 `identity.json` (`src/bitchat/storage/config.py`)

Stores the user's persistent cryptographic identity (`LocalIdentity`).

- **JSON Schema:**
  ```json
  {
    "x25519_private": "<64-char hex string (32 bytes)>",
    "ed25519_private": "<64-char hex string (32 bytes)>",
    "fingerprint": "<64-char hex string: SHA-256(x25519_public)>",
    "peer_id": "<16-char hex string: SHA-256(x25519_public)[:8]>"
  }
  ```
- **Access Controls:**
  - **POSIX (Linux / macOS):** Written via `_atomic_write_json(..., chmod_mode=0o600)` and tightened on load via `os.chmod(path, 0o600)`.
  - **Windows:** Restricted to the current process token user SID via `_restrict_windows_file_acl` using Win32 `SetNamedSecurityInfoW` with a protected DACL granting `FILE_ALL_ACCESS` only to the current user.
- **At-Rest Encryption Status:** Keys are stored as raw hexadecimal strings in JSON and are **not** encrypted with a user passphrase at rest in `v0.3.1`.
- **Corruption Recovery:** If `identity.json` contains malformed JSON or invalid key bytes, `_create_corrupt_identity_backup()` copies the file to `identity.json.corrupt.<unix_timestamp>` before generating a replacement identity.

### 1.2 `identity.json.lock` (`src/bitchat/storage/config.py`)

- **Contents:** 1-byte (`\x00`) advisory lock file used by `_interprocess_lock` (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX) with a 10.0-second timeout to prevent split-brain identity generation when multiple BitChat instances start simultaneously.

### 1.3 `config.json` (`src/bitchat/storage/config.py`)

Stores non-sensitive application preferences and Trust-On-First-Use (TOFU) contact fingerprints (`AppConfig`).

- **JSON Schema & Default Values:**
  ```json
  {
    "nickname": "Anonymous",
    "debug": false,
    "density": "comfortable",
    "show_timestamps": true,
    "accent": "blue",
    "transport": "bluetooth",
    "security_mode": "normal",
    "max_hops": 3,
    "inter_fragment_delay_ms": 20,
    "lan_discovery_port": 41234,
    "lan_tcp_port": 41235,
    "keybindings": {
      "help": "f1",
      "edit_theme": "f2",
      "settings": "f3",
      "peers": "f4",
      "clear_chat": "ctrl+l",
      "quit": "ctrl+q",
      "scroll_up": "pageup",
      "scroll_down": "pagedown"
    },
    "contacts": {
      "<16-char peer_id_hex>": "<64-char sha256 fingerprint_hex>"
    }
  }
  ```

### 1.4 `bitchat.log` and Rotated Backups (`src/bitchat/logging/__init__.py`)

- **Rotation Policy:** `RotatingFileHandler` with `maxBytes = 10,485,760` (10 MB) and `backupCount = 5` (`bitchat.log`, `bitchat.log.1`, ..., `bitchat.log.5`).
- **Sensitive Data Redaction:** Every log record passes through `SensitiveDataFilter`, which replaces:
  - Any standalone 64-character hexadecimal string (`\b[0-9a-fA-F]{64}\b`) with `[REDACTED]`.
  - Key-value patterns matching `private_key`, `priv_key`, `secret_key`, `secret`, `seed`, `session_token`, `token`, `password`, `auth_token`, or `api_key` with `[REDACTED]`.
  - `Bearer <token>` headers with `Bearer [REDACTED]`.

---

## 2. Volatile In-Memory Data Inventory (Never Persisted to Disk)

| Runtime Component | Module | Retention & Bounds |
| :--- | :--- | :--- |
| **Chat Message History** | `src/bitchat/tui/screens/chat.py`, `src/bitchat/tui/widgets/chat_view.py` | Held in memory only (trimmed to `MAX_RENDERED_MESSAGES = 500` in the TUI widget). Cleared on `/clear` or application exit. |
| **Noise XX Sessions** | `src/bitchat/crypto/sessions.py`, `src/bitchat/crypto/noise.py` | Ephemeral X25519 keys, chaining keys `ck`, handshake hashes `h`, and `ChaCha20-Poly1305` `NoiseCipherState` keys (`k`, nonce `n`, 1024-entry replay window). Cleared when a peer disconnects, transport switches, or the process exits. |
| **Packet Deduplication Cache** | `rust/bitchat-core` (`NativePacketDeduplicator`) / `src/bitchat/mesh/dedup.py` | Stores 16-byte truncated SHA-256 packet digests (`max_size = 1000`, `ttl_seconds = 300.0`). |
| **Fragment Reassembly Buffers** | `rust/bitchat-core` (`NativeFragmentReassembler`) / `src/bitchat/protocol/reassembly.py` | Stores partial multi-fragment payloads (`MAX_ACTIVE_ASSEMBLIES = 100`, `MAX_FRAGMENTS_PER_ASSEMBLY = 1000`, `MAX_REASSEMBLED_BYTES = 150_000`, `timeout_seconds = 30.0`). |
| **Store-and-Forward Queue** | `src/bitchat/mesh/store_forward.py` (`StoreAndForwardQueue`) | Buffers outbound packets for temporarily disconnected peers (`max_total_packets = 100`, `max_per_peer = 20`, `max_total_bytes = 262,144` [256 KB], `packet_ttl_seconds = 300.0`). |

---

## 3. Over-the-Air & Local Network Transmission Inventory

When not in `Offline Mode`, BitChat transmits the following protocol structures to nearby devices:

### 3.1 Bluetooth Low Energy (BLE) Transmissions (`src/bitchat/ble/`)

- **GATT Service UUID:** `F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`
- **GATT Characteristic UUID:** `A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`
- **Transmitted Frames:** Binary `BitchatPacket` frames (padded to `256`/`512`/`1024`/`2048` byte blocks and fragmented when exceeding `FRAGMENTATION_THRESHOLD = 500` bytes).

### 3.2 LAN UDP Discovery Beacons (`src/bitchat/network/discovery.py`, `src/bitchat/network/models.py`)

- **Default Port & Interval:** UDP broadcast to `255.255.255.255:41234` and directed subnet broadcast every `3.0` seconds (`MAX_DISCOVERY_PACKET_SIZE = 1024` bytes).
- **Discovery Packet Fields (`DiscoveryPacket` UTF-8 JSON):**
  - `protocol`: `"bitchat"`
  - `version`: `1`
  - `transport`: `"lan"`
  - `peer_id`: 16-character hex string (8-byte peer ID)
  - `nickname`: UTF-8 string (up to 32 characters)
  - `port`: Inbound TCP listening port (default `41235`)
  - `ssid`: Detected Wi-Fi SSID string (up to 64 characters, or `""` if unavailable/Ethernet)
  - `instance_id`: Random per-process instance identifier (up to 32 characters)

### 3.3 LAN TCP Stream Framing (`src/bitchat/network/framing.py`, `src/bitchat/network/server.py`)

- **Default Port:** TCP `41235` (falls back to an OS-assigned ephemeral port if `41235` is in use).
- **Wire Frame:** 8-byte header (`FRAME_MAGIC = b"BC\x01\x00"` + 4-byte big-endian `uint32` length prefix, up to `MAX_FRAME_SIZE = 65,536` bytes) followed by the serialized `BitchatPacket`.

### 3.4 Binary `BitchatPacket` Header (`src/bitchat/protocol/packet.py`, `rust/bitchat-core/src/protocol.rs`)

Every packet transmitted over BLE or LAN begins with a 14-byte fixed big-endian header (`FIXED_HEADER_SIZE = 14`) followed by an 8-byte `sender_id` (`MINIMUM_PACKET_SIZE = 22`), optional `recipient_id`, `payload`, and optional `signature`:

| Offset | Size | Field | Description |
| :--- | :--- | :--- | :--- |
| `0` | `1 B` | `version` | Protocol version (`0x01`) |
| `1` | `1 B` | `message_type` | `MessageType` enum (`0x01`–`0x25`) |
| `2` | `1 B` | `ttl` | Remaining hop count (`0`–`7`, default `3`) |
| `3..10` | `8 B` | `timestamp` | 64-bit unsigned millisecond timestamp |
| `11` | `1 B` | `flags` | Bitmask (`0x01` `HAS_RECIPIENT`, `0x02` `HAS_SIGNATURE`, `0x04` `IS_COMPRESSED`) |
| `12..13` | `2 B` | `payload_len` | Big-endian `uint16` length of `payload` (`0`–`65535`) |
| `14..21` | `8 B` | `sender_id` | 8-byte sender Peer ID (`SHA-256(x25519_pub)[:8]`) |
| `22..29` | `0 or 8 B` | `recipient_id` | Present when `FLAG_HAS_RECIPIENT` (`0x01`) is set (`ffffffffffffffff` for broadcast) |
| `var` | `payload_len B` | `payload` | Inner message, fragment, or Noise ciphertext payload |
| `tail` | `0 or 64 B` | `signature` | Present when `FLAG_HAS_SIGNATURE` (`0x02`) is set (64-byte Ed25519 signature) |

---

## 4. Data Deletion Behavior Across Lifecycle Operations

| Operation | Application Binaries & Launchers | `~/.bitchat/` (`identity.json`, `config.json`, `bitchat.log`) |
| :--- | :--- | :--- |
| **Application Exit (`Ctrl+Q` / `/exit`)** | Preserved | Preserved; all RAM chat history and session keys discarded |
| **Application Upgrade** | Replaced with new version | Preserved intact |
| **`bitchat --uninstall`** *(Normal)* | Deleted across standalone & Python installs | **Preserved** |
| **`bitchat --uninstall --remove-user-data --yes`** | Deleted across standalone & Python installs | **Permanently Deleted** |
| **Windows `unins000.exe` (Interactive)** | Deleted | Prompts user: **No** preserves `~/.bitchat/`; **Yes** permanently deletes `~/.bitchat/` |
| **Windows `unins000.exe /VERYSILENT`** | Deleted | **Preserved** |
