# BitChat Privacy Policy

> **DRAFT — LEGAL REVIEW REQUIRED:** This document is a technical privacy disclosure draft prepared for the open-source BitChat project (`v0.3.1`). It describes the actual data-handling behavior of the software as implemented in the repository and must be reviewed by the project publisher or qualified legal counsel before any commercial, enterprise, or regulated deployment.

**Effective Date:** November 9, 2026  
**Applicable Release:** BitChat `v0.3.1`  
**Repository:** [https://github.com/Java-Mx/bitchat-python](https://github.com/Java-Mx/bitchat-python)

---

## 1. Overview & Architecture Philosophy

BitChat is a local-first, peer-to-peer (P2P) terminal messenger operating over Bluetooth Low Energy (BLE) and Local Area Network (LAN) transports.

- **No Central Servers:** BitChat operates without central messaging servers, cloud relays, or developer-operated backend infrastructure.
- **No Accounts or Registration:** BitChat does not collect names, email addresses, phone numbers, or account credentials.
- **No Telemetry or Analytics:** The application contains no analytics SDKs, crash-reporting beacons, usage trackers, advertising identifiers, or automatic update checks that phone home.

Because BitChat is a decentralized peer-to-peer tool, data stays on your device unless you actively enable a radio/network transport (Bluetooth LE or LAN) to discover and communicate with nearby peers.

---

## 2. Information We Do Not Collect

The BitChat developers and maintainers do **not** collect, receive, store, or process:

1. Your IP address, Bluetooth MAC address, or Wi-Fi SSID on any remote server.
2. Your cryptographic keys, peer ID, fingerprint, or chosen nickname.
3. The contents, metadata, or timing of your messages.
4. Diagnostic logs, crash dumps, or system hardware reports (unless you voluntarily attach them to a public GitHub issue).

---

## 3. Information Stored Locally on Your Device

By default, BitChat stores local state inside the `.bitchat` directory in your user home folder:

- **Windows:** `%USERPROFILE%\.bitchat\` (for example, `C:\Users\<username>\.bitchat\`)
- **Linux & macOS:** `~/.bitchat/` (for example, `/home/<username>/.bitchat/`)

### 3.1 Local Files Created and Used by BitChat

| File | Purpose & Contents | Protection & Lifecycle |
| :--- | :--- | :--- |
| `identity.json` | Stores your persistent local cryptographic identity in JSON format: 32-byte X25519 private key (`x25519_private`), 32-byte Ed25519 signing seed (`ed25519_private`), 64-character SHA-256 public key `fingerprint`, and 16-character hex `peer_id`. | Created with `0600` permissions on POSIX (`Linux`/`macOS`) and a protected current-user-only DACL (`SetNamedSecurityInfoW`) on Windows. Keys are stored as hex strings on disk and are **not** encrypted with a user passphrase at rest. |
| `identity.json.lock` | 1-byte cross-process advisory lock file (`msvcrt` on Windows, `fcntl` on POSIX) used to prevent concurrent processes from generating conflicting identities on first launch. | Remains in `~/.bitchat/` while the application manages identity access. |
| `identity.json.corrupt.<timestamp>` | Automatic backup copy created only if `identity.json` is detected as unreadable or corrupted prior to generating a replacement keypair. | Retained locally until manually deleted or purged during complete uninstallation. |
| `config.json` | Stores non-sensitive user preferences: `nickname` (default `"Anonymous"`, max 32 chars), `debug`, `density`, `show_timestamps`, `accent`, `transport` (`"bluetooth"`, `"lan"`, or `"offline"`), `security_mode` (`"normal"` or `"maximum"`), `max_hops` (`1`–`7`), `inter_fragment_delay_ms`, `lan_discovery_port` (default `41234`), `lan_tcp_port` (default `41235`), `keybindings`, and your Trust-On-First-Use (TOFU) `contacts` map (`peer_id` → `fingerprint`). | Standard user file permissions; updated atomically via temporary file replacement. |
| `bitchat.log` (and `.1`–`.5`) | Rotating diagnostic log files (up to 10 MB per file, max 5 backups) when file logging is active. | Filtered through `SensitiveDataFilter` to redact 64-character hex keys, bearer tokens, and secret key-value patterns before writing to disk. |

### 3.2 Ephemeral In-Memory Data (Not Written to Disk)

The following runtime structures exist **only in volatile memory (RAM)** while BitChat is running and are discarded when you exit the application:

- **Chat Message History:** Sent and received chat messages displayed in the terminal UI are held in memory only and are **not** saved to disk in `v0.3.1`.
- **Noise XX Session State:** Ephemeral X25519 handshake keys, HMAC-SHA256 chaining keys, and ChaCha20-Poly1305 / AES-256-GCM symmetric cipher states (`NoiseSession`).
- **Mesh & Reassembly Buffers:** The `PacketDeduplicator` (`NativePacketDeduplicator`) cache, `FragmentReassembler` (`NativeFragmentReassembler`) state for multi-part packets, and the `StoreAndForwardQueue` (bounded to at most 100 packets / 256 KB total, 20 packets per peer, with a 300-second time-to-live).

For a complete field-level technical specification, see [`docs/security/DATA_HANDLING.md`](docs/security/DATA_HANDLING.md).

---

## 4. Information Shared Over Peer-to-Peer Networks

When BitChat is not in `Offline Mode`, your device transmits protocol packets directly to nearby devices over the active transport. **Anyone within radio range (BLE) or connected to the same local network (LAN) can observe these network transmissions.**

### 4.1 Bluetooth Low Energy (BLE) Transport

When the `Bluetooth LE` transport is active:

- **GATT Identifiers:** BitChat advertises and scans for the BitChat BLE Service UUID `F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C` and transfers frames via Characteristic UUID `A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`.
- **Visible Metadata:** Nearby Bluetooth scanners can observe that a device in range is running BitChat, inspect OS-level BLE advertisement metadata (such as adapter address and signal strength / RSSI), and read outer BitChat packet headers.

### 4.2 Local Area Network (LAN) Transport

When the `Local Network (LAN)` transport is active:

- **UDP Discovery Beacons:** BitChat periodically broadcasts UTF-8 JSON UDP discovery packets (default port `41234`, every 3.0 seconds) to `255.255.255.255` and the active interface's directed subnet broadcast address.
- **Beacon Contents:** Each UDP discovery packet contains `"protocol": "bitchat"`, `"version": 1`, `"transport": "lan"`, your 16-character hex `peer_id`, your configured `nickname`, your inbound TCP listening port (default `41235`), a random per-process `instance_id`, and (when detected by the OS) your current Wi-Fi `ssid`.
- **TCP Transport Connections:** Peer-to-peer packets are exchanged over direct 8-byte framed TCP connections (`BC\x01\x00` + 4-byte length prefix, default port `41235`, or an ephemeral fallback port if `41235` is busy). Other hosts on the same LAN segment can see your local IPv4 address, port numbers, and UDP broadcast beacons.

### 4.3 Packet Headers, Broadcasts, and Multi-Hop Mesh Routing

- **Unencrypted Outer Wire Headers:** Every BitChat binary packet header (`version`, `message_type`, `ttl`, `timestamp`, `flags`, `payload_len`, 8-byte `sender_id`, and optional 8-byte `recipient_id`, minimum 22 bytes) is transmitted in the clear so that peers and mesh relays can route, deduplicate, and reassemble packets.
- **Private / Unicast Messages (`0x12 NoiseEncrypted`):** Direct peer-to-peer messages encrypted inside an established `Noise_XX_25519_ChaChaPoly_SHA256` session have their payload encrypted with ChaCha20-Poly1305. However, the outer header (`sender_id`, `recipient_id`, `timestamp`, `ttl`, packet size, and timing) remains visible to intermediate mesh nodes.
- **Public Broadcast Messages (`0x04 Message` to `ffffffffffffffff`):** General room chat messages addressed to the broadcast peer ID (`ffffffffffffffff`) are not encrypted for a specific recipient and can be read by any connected peer receiving the broadcast.
- **Multi-Hop Forwarding:** When `max_hops` / `ttl` is greater than `1` (default `3`, maximum `7`), connected BitChat peers may relay packets across multiple hops. You cannot control how remote peers log, store, or display messages and metadata after those packets leave your device.
- **Persistent Identity Across Transports:** By default, BitChat uses your persistent `LocalIdentity` (`~/.bitchat/identity.json`) across both BLE and LAN transports and across application restarts. Switching between BLE and LAN tears down active transport sockets and ephemeral Noise session keys, but preserves your underlying `peer_id` and public key fingerprint unless you delete or regenerate `identity.json`.

---

## 5. Data Retention, Uninstallation, and Complete Removal

You have full local control over the retention and deletion of all BitChat data on your computer:

1. **Application Upgrades:** Installing a newer version of BitChat over an existing installation preserves `~/.bitchat/` (`identity.json`, `config.json`, and logs) so your identity and trusted contacts are retained.
2. **Standard Uninstallation (Preserves User Data by Default):** Running `bitchat --uninstall` (without `--remove-user-data`) or running a standard package uninstall removes BitChat executables, console-script launchers, shortcuts, startup entries, and BitChat-owned `PATH` entries, while **preserving** `~/.bitchat/` to prevent accidental loss of your cryptographic identity keys.
3. **Complete Removal (Deletes All User Data and Keys):**
   - **CLI Command:** Run `bitchat --uninstall --remove-user-data --yes` (or `bitchat --uninstall --purge --yes`) to remove both the application and the entire `~/.bitchat/` directory.
   - **Windows Uninstaller:** When running the Windows uninstaller interactively (`unins000.exe` or Windows *Installed Apps*), choose **Yes** when prompted whether to remove your `~/.bitchat` user data directory.
   - **Manual Deletion:** You may also delete `~/.bitchat/` (or `%USERPROFILE%\.bitchat\`) at any time while BitChat is closed. Deleting `identity.json` permanently destroys your static private keys; a new identity will be generated on next launch.

See [`docs/UNINSTALLATION.md`](docs/UNINSTALLATION.md) for platform-by-platform removal instructions.

---

## 6. Third-Party Services & Distribution Channels

- **Runtime Operation:** BitChat makes no requests to third-party web APIs or cloud services during execution.
- **Software Distribution:** If you download BitChat from GitHub Releases, the Python Package Index (PyPI), Microsoft WinGet, or Flathub, those distribution platforms collect standard network request logs under their respective privacy policies.

---

## 7. Policy Updates & Contact

This Privacy Policy is maintained in the BitChat source repository at [`PRIVACY_POLICY.md`](PRIVACY_POLICY.md) (and mirrored in plain text at [`packaging/windows/legal/PRIVACY_POLICY.txt`](packaging/windows/legal/PRIVACY_POLICY.txt) for the Windows installer). Material changes to how BitChat handles local or network data must be documented here alongside the corresponding code changes.

For questions or corrections regarding this policy or BitChat's data handling:

- **Documentation & Privacy Issues:** Open an issue at [https://github.com/Java-Mx/bitchat-python/issues](https://github.com/Java-Mx/bitchat-python/issues)
- **Security-Sensitive Reports:** Follow the private reporting instructions in [`SECURITY.md`](SECURITY.md) via [GitHub Security Advisories](https://github.com/Java-Mx/bitchat-python/security/advisories/new)
