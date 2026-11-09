# Architecture

BitChat Python follows a strict layered architecture to maintain separation of concerns and testability.

## Layered Architecture

```
TUI (Textual — bitchat.tui) / Headless CLI (bitchat.app)
 ↓
Application Core / Session Coordinator (bitchat.app)
 ↓
Mesh Router (Relay, Dedup, Rate Limit, Store & Forward — bitchat.mesh + _bitchat_core)
 ↓
Protocol / Crypto / Storage (bitchat.protocol + _bitchat_core, bitchat.crypto, bitchat.storage)
 ↓
Transport Abstraction Layer (BaseTransport — bitchat.transport)
 ├── Bluetooth Low Energy (BLEManager, BLEServer via Bleak / WinRT / BlueZ D-Bus)
 ├── LAN / Wi-Fi (UDP Discovery 41234 + Framed TCP Streaming 41235 via _bitchat_core)
 └── Offline Mode (OfflineTransport — zero radio / zero socket operation)
```

## Native Rust Core (`rust/bitchat-core` / `bitchat._bitchat_core`)

In `v0.3.1`, performance-critical wire, framing, fragmentation, reassembly, deduplication, and rate-limiting operations are implemented in Rust (`rust/bitchat-core/src/`) and compiled into the `bitchat._bitchat_core` extension via PyO3 (`abi3-py312`) and Maturin (`src/bitchat/_native.py`):

- **`protocol.rs`**: `encode_packet_raw`, `decode_packet_raw`, `pad_packet_data`, `unpad_packet_data`, `get_optimal_block_size`, `peer_id_to_hex`, `peer_id_from_hex`.
- **`fragmentation.rs`**: `should_fragment_bytes`, `split_chunks`, `create_fragment_payload`, `parse_fragment_payload`, `fragment_encoded_packet_raw`, and `NativeFragmentReassembler`.
- **`framing.rs`**: `encode_frame_bytes` and `NativeStreamFramer` (8-byte `BC\x01\x00` + length-prefixed TCP stream assembly).
- **`mesh.rs`**: `compute_packet_id_raw`, `NativePacketDeduplicator` (SHA-256 `[:16]` LRU/TTL cache), and `NativePeerRateLimiter`.
- **Automatic Fallback & Differential Parity**: Every Rust function and class has a pure-Python counterpart in `src/bitchat/` with tagged exception translation (`raise_mapped_error`), verified by differential equivalence tests (`tests/unit/test_native_core.py`). See [`docs/ROADMAP.md`](ROADMAP.md) for the 7-stage migration roadmap toward ~60% Rust and ultimately a 100% native Rust application.

## Module Responsibilities

- **`tui/`**: Professional full-screen terminal user interface (`bitchat.tui.app.BitChatApp`). Must NOT directly implement BLE or cryptography. Built with Textual as an edge-to-edge dashboard canvas using a strict 5-family color system (Black, Blue, Purple, Deterministic Peer Colors, and Restrained Semantic Status):
  - `styles/app.tcss`: Centralized Textual stylesheet defining full-viewport layout, panel borders, inline border titles, focus states, custom scrollbars, and modal styling.
  - `theme.py`: Design tokens, color constants, and deterministic peer identity color generator (`get_peer_color`) mapping peer identifiers to stable colors.
  - `widgets/header.py`: Compact 1-line top header displaying branding, channel indicator, peer count, and local identity fingerprint.
  - `widgets/sidebar.py`: `PeerSidebar` with `border-title: "Peers [BLE Mesh]"`, displaying connected and discovered nodes with deterministic peer colors and local identity card.
  - `widgets/chat_view.py`: `ChatView` with `border-title: "Conversation [#public]"`, two-tier message typography (sender anchor + timestamp, body), status tags (`[Public]`, `[🔒 DM]`, `[System]`, `[Security]`, `[Error]`), and scroll controls (`PageUp`/`PageDown`).
  - `widgets/message_input.py`: `MessageInput` prompt with sharp borders, focused blue accent, command history navigation ($\uparrow/\downarrow$), and autocomplete event delegation.
  - `widgets/autocomplete.py`: `AutocompletePalette` IDE-style floating menu anchored above input with synchronous `OptionList`, real-time prefix filtering, and contextual peer suggestions for `/dm ` and `/connect `.
  - `widgets/status_bar.py`: Action bar with stacked operational telemetry (Mesh readiness, Noise XX encryption, and truthful target status with offline awareness) alongside a balanced 2:2:2 button grid (Row 1: `Edit`, `Settings`, `Peers`; Row 2: `Commands`, `Help`, `Quit`).
  - `screens/help.py`: Responsive `HelpScreen` modal dialog (90% width, up to 120 columns) displaying a full-width `DataTable` of commands and shortcuts, with a centered bottom `[ Close (Esc) ]` button.
  - `screens/peer_info.py`: `PeerInfoModal` presenting full 64-char public fingerprint, 64-char peer ID, transport diagnostics, and Noise XX security state, while strictly protecting private secrets.
  - `screens/settings.py`: `SettingsModal` for live configuration of nickname, max mesh relay hops (TTL), and inter-fragment transmission delay.
  - `screens/edit_theme.py`: `EditThemeModal` for toggling display density (comfortable vs compact) and timestamp visibility.
  - `screens/ble_error.py`: `BLEErrorModal` for hardware diagnostic guidance and automated `[Retry Adapter]` recovery.
- **`platform/`**: Operating-system detection, capability diagnostics, and OS-specific recovery guidance. This is the only place that decides *which OS* BitChat is running on; BLE, network, and TUI code ask it instead of branching on the OS themselves.
  - `detection.py`: `detect_platform()` (from `sys.platform`, read at call time so tests can mock it), `is_windows()`/`is_linux()`, `probe_ble_backend()` (are the platform's Python BLE modules importable?) and `peripheral_backend_implemented()`. Imports nothing else from `bitchat`, and never imports another platform's packages.
  - `capabilities.py`: Hardware/network diagnostics behind `/configure` and `bitchat --configure` (including socket-binding probes on default diagnostic ports UDP `24024` and TCP `24025`).
  - `recovery.py`: OS-specific Bluetooth remediation text shown by `BLEErrorModal`; widgets contain no OS branching.
  - `startup.py`: Per-user Windows Startup shortcut management (`--startup enable|disable|status`) and single-instance mutex guard (`SingleInstanceGuard`).
  - `uninstaller.py`: Cross-platform uninstallation engine (`bitchat --uninstall`, `--dry-run`, `--remove-user-data`, `--yes`) discovering and cleaning standalone binaries, multi-Python console scripts (`Python3XX\Scripts\bitchat.exe`), shortcuts, registry entries, and BitChat-owned `PATH` entries while protecting developer Git checkouts.
  - Operating system, BLE backend, adapter hardware, GATT/advertising success, LAN availability, and the *active* transport are separate facts: knowing the OS never implies Bluetooth works. Adapter state is determined at runtime by `BLEAdapterManager`; role state by `BluetoothTransport.get_telemetry()`.
  - Platform behaviour: Windows uses WinRT for adapter discovery, radio monitoring, the GATT server, and advertising; Linux uses BlueZ over D-Bus (via `dbus-fast`) for adapter capability discovery, GATT server (`GattManager1`), and connectable LE advertising (`LEAdvertisingManager1`), alongside Bleak for central scanning. Both share `BLEManager`, `BLEServer`, `BluetoothTransport`, and `SessionCoordinator`.
- **`mesh/`**: Multi-hop mesh routing, deduplication, and store-and-forward (depends on `protocol`).
  - `dedup.py`: `PacketDeduplicator` utilizing TTL-invariant SHA-256 hashing `[:16]` over `(sender_id + timestamp + message_type + recipient_id + payload)`, bounded LRU cache (capped at 1,000 entries), and 300s TTL cache.
  - `store_forward.py`: `StoreAndForwardQueue` with per-peer limits (20 packets), global cap (100 packets), aggregate byte budget (256 KB), and automatic flushing upon peer announce/connect.
  - `router.py`: `MeshRouter` handling origin loop prevention, peer rate-limiting (50 pkts/s), deduplication, strict TTL boundary verification (drop TTL <= 0, clamp oversized TTL to `max_relay_ttl`, enforce monotonic decrement with forward >= 1), 10–50ms randomized collision-mitigation jitter, and destination evaluation.
- **`app/`**: Application logic, command handling, state (depends on `protocol`, `crypto`, `storage`, `mesh`, `ble`).
  - `session_coordinator.py`: `SessionCoordinator` orchestrating `dict[str, NoiseSession]`, peer address resolution, deterministic Noise XX handshake progression, encrypted direct messages, presence announcements, mesh routing/relaying with collision jitter, store-and-forward queueing/flushing, and fragmentation pacing.
  - `application.py`: `Application` core controller managing startup/shutdown, command dispatching, and background task lifecycle.
- **`protocol/`**: Packet encoding/decoding, wire models, message types, fragmentation (independent). Must remain independent from presentation.
  - `constants.py`: Wire format sizes, UUIDs, bitmask flags, block sizes, fragmentation limits, and `MessageType` enum.
  - `packet.py`: Immutable `BitchatPacket` dataclass with normalized immutable `bytes` fields, property accessors, flags, and hex conversion.
  - `encoder.py`: Binary big-endian packet serialization (`encode_packet`) and BitChat random block padding (`pad_packet_data`).
  - `decoder.py`: Strict wire packet deserialization (`decode_packet`) and padding removal (`unpad_packet_data`) with defensive bounds validation.
  - `fragmentation.py`: Packet fragmentation splitting wire-encoded packets exceeding 500 bytes into <=150-byte chunks with 13-byte headers (`FragmentStart`, `FragmentContinue`, `FragmentEnd`).
  - `reassembly.py`: Out-of-order `FragmentReassembler` with sender isolation (`(sender_id, fragment_id)` key), LRU assembly eviction, bounded buffer limits, and strict full-range validation.
- **`crypto/`**: Cryptographic primitives, Noise protocol, key management, and identity (independent). Must NOT depend on TUI or BLE.
  - `identity.py`: `LocalIdentity` dataclass managing Ed25519 & X25519 key pairs with safe string representation and 64-char hex fingerprint calculation.
  - `ed25519.py`: Ed25519 digital signature signing and verification with strict size checks.
  - `x25519.py`: X25519 Diffie-Hellman key exchange with Curve25519 low-order point validation.
  - `aes_gcm.py`: AES-256-GCM encryption with 96-bit OS CSPRNG nonces matching the Rust legacy wire layout (`nonce || ciphertext+tag`).
  - `hkdf.py`: Noise custom HMAC-SHA256 multi-output expansion and standard HKDF-SHA256 for legacy exchange.
  - `pbkdf2.py`: PBKDF2-HMAC-SHA256 (100k iterations) for channel password key derivation.
  - `noise.py`: `Noise_XX_25519_ChaChaPoly_SHA256` handshake state machine, symmetric transcript hashing, extracted wire nonces, and 1024-entry replay window.
  - `sessions.py`: `NoiseSession` orchestrating per-peer handshake progression, role assignment, and transport encryption.
- **`storage/`**: Message persistence, identity storage (independent).
- **`ble/`**: BLE scanning, connection lifecycle, GATT discovery, fragment pacing, and packet routing via Bleak (depends on `protocol`). Must NOT depend on TUI.
  - `models.py`: `BLEConnectionState` lifecycle enum and `DiscoveredPeer` metadata dataclass.
  - `scanner.py`: `BLEScanner` filtering for BitChat Service UUID (`F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`), duplicate normalization, and peer tracking.
  - `gatt.py`: `GATTManager` resolving service and characteristic (`A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D`) with property validation (`write-without-response`, `notify`).
  - `connection.py`: `BLEConnection` state machine managing peer connection, GATT discovery, notification subscription, and disconnect callbacks.
  - `transport.py`: `BLETransport` integrating packet serialization, conditional fragmentation (>500B), 20ms pacing, bounded reception queue, and fragment reassembly.
  - `server.py`: `BLEServer` GATT peripheral server advertising BitChat service UUID, receiving write-without-response frames, and sending notifications.
  - `manager.py`: `BLEManager` high-level coordinator managing scanner lifecycle, multiple active peer connections, direct sending, and broadcast.
- **`transport/`**: Common transport abstraction (`BaseTransport`, `TransportType`, `TransportState`, `TransportPeer`). Establishes a uniform interface for all network backends, enabling zero-duplication protocol handling and seamless runtime transport switching.
  - `base.py`: Abstract `BaseTransport` contract defining discovery, messaging, telemetry, and connection lifecycles.
  - `bluetooth.py`: `BluetoothTransport` bridging existing `BLEManager` and `BLEServer` to `BaseTransport`.
- **`network/`**: High-performance Local Area Network (LAN / Wi-Fi) transport backend.
  - `discovery.py`: `LANDiscovery` UDP broadcast daemon on port 41234 transmitting and receiving `BC_DISCOVER_V1` beacons with per-IP rate limiting and TTL pruning.
  - `framing.py`: Length-prefixed stream framer (`StreamFramer`, `encode_frame`) with 8-byte header (`BC\x01\x00` magic + 4-byte payload length) and chunk assembly.
  - `connection.py`: `LANConnection` handling async TCP peer connections, dedicated send queues, reader loops, and graceful teardown.
  - `server.py`: `LANServer` asynchronous TCP listener supporting up to 32 concurrent links with dynamic port fallback.
  - `adapter.py`: `NetworkAdapterManager` detecting active Windows interfaces, local IPv4 addresses, and Wi-Fi SSIDs (`netsh wlan show interfaces`).
  - `transport.py`: `LANTransport` unifying discovery, server listening, and connection management into a single `BaseTransport` implementation.
- **`models/`**: Shared data types (independent, leaf dependency).
- **`utils/`**: Shared utilities (independent, leaf dependency).
- **`commands/`**: CLI command definitions (depends on `app`).

## BLE Transport Architecture

The `bitchat.ble` package bridges the high-level application and the underlying Bluetooth Low Energy hardware using Bleak:

```
Application Layer
       │  ▲
       ▼  │ (Packets / Events)
   BLEManager
   ├── BLEScanner (Filters BitChat UUID F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C)
   └── dict[address, BLETransport]
            │
            ├── BLEConnection (Lifecycle: Disconnected -> Connecting -> Connected
            │                  -> Discovering GATT -> Subscribing -> Ready)
            ├── GATTManager (Characteristic A1B2C3D4-E5F6-4A5B-8C9D-0E1F2A3B4C5D)
            ├── Outbound Transmission:
            │     - If wire size <= 500B: direct write (response=False)
            │     - If wire size > 500B: fragment into 150B chunks, pace at 20ms interval
            └── Inbound Reception:
                  - Bounded asyncio.Queue (backpressure / drop-on-full protection)
                  - Background worker pulls raw notification bytes
                  - Decodes packet & routes fragments to FragmentReassembler
                  - Delivers reassembled BitchatPacket to application callback
```

### Connection State Machine

1. **`DISCONNECTED`**: No active BLE link.
2. **`CONNECTING`**: Bleak client connecting to peer peripheral.
3. **`CONNECTED`**: Link established; preparing for service discovery.
4. **`DISCOVERING_GATT`**: Validating BitChat Service and Characteristic UUIDs with required properties.
5. **`SUBSCRIBING`**: Subscribing to GATT notifications via `start_notify`.
6. **`READY`**: Fully initialized and bidirectional packet transmission enabled.
7. **`DISCONNECTING`**: Teardown in progress (unsubscribing and disconnecting client).

## Protocol Wire Architecture

The `bitchat.protocol` layer provides a decoupled wire encoding and decoding pipeline accelerated by `rust/bitchat-core` (`bitchat._bitchat_core`) with automatic pure-Python fallback:

```
BitchatPacket (Data Model)
  │
  ▼ [encode_packet]
Raw Unpadded Wire Bytes (Fixed Header 14B + Sender 8B [+ Recipient 8B] + Payload [+ Signature 64B])
  │
  ▼ [pad_packet_data]
Padded Packet Buffer (Padded to 256 / 512 / 1024 / 2048 bytes with trailing padding count)
  │
  ▼ (If wire size > 500 bytes)
[fragment_encoded_packet]
  │
  ▼
N Fragment Packets (<=150B data chunks + 13B headers; Start/Continue/End)
  │
  ▼ [encode_packet + pad_packet_data per fragment]
Serialized Wire Fragments for BLE transmission
```

The reverse flow decodes wire bytes, handling both single packets and fragmented packets:

```
Wire Bytes Received
  │
  ▼ [unpad_packet_data + decode_packet]
Fragment Packet (0x05, 0x06, 0x07) or Regular BitchatPacket
  │
  ├─► Regular Packet: Process directly
  │
  └─► Fragment Packet:
        │
        ▼ [reassembler.add_fragment(packet)]
      Accumulate chunk by index under (sender_id, fragment_id)
        │
        ▼ (When all 0..total-1 indices present)
      Reassembled Wire Bytes
        │
        ▼ [unpad_packet_data + decode_packet]
      Original BitchatPacket (Validated Data Model)
```

## Storage & Configuration Architecture

Persistent node configuration and user preferences are decoupled into `bitchat.storage`:
- **`AppConfig`**: Strongly typed data model with strict invariant validation and defensive deserialization (graceful fallback on corrupted keys or unexpected types).
- **`StorageInterface` / `FileConfigStorage`**: Atomic JSON persistence under `~/.bitchat/config.json`.
- **Decoupled Appearance Settings**: Appearance parameters (`density: "comfortable" | "compact"`, `show_timestamps: bool`, `accent: "blue" | "cyan" | "emerald" | "purple"`) and node operational parameters (`nickname`, `max_hops`, `inter_fragment_delay_ms`) are saved to storage without storing sensitive keys.
- **TUI Synchronization**: TUI screens (`EditThemeModal`, `SettingsModal`) post typed messages to the application root, which updates reactive CSS classes, triggers structured history re-rendering in `ChatView`, and updates persistent storage.

## Transport Abstraction & Dual-Transport Architecture

BitChat decouples high-level messaging, routing, and cryptography from network transport media through `BaseTransport`:

```
                           SessionCoordinator
                                   │
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
      BluetoothTransport                           LANTransport
      (BLEManager + BLEServer)             (Discovery + TCP Server)
              │                                         │
        Bleak / WinRT                        Asyncio UDP + Framed TCP
              │                                         │
     Bluetooth 4.2+ Mesh                     LAN / Wi-Fi (802.11 / Eth)
```

### Transport Contract
All transports implement `BaseTransport` (`bitchat.transport.base`):
- **Lifecycle**: `start()`, `stop()`, `start_discovery()`, `stop_discovery()`
- **Transmission**: `send_to_peer(address, packet)`, `broadcast_packet(packet, exclude_address)`
- **Connections**: `connect_peer(address)`, `disconnect_peer(address)`
- **Identity & Resolution**: `update_identity(peer_id, nickname)`, `resolve_peer_id_to_address(target)`
- **Telemetry**: `get_telemetry() -> dict[str, Any]`

### LAN / Wi-Fi Backend Protocol
1. **UDP Discovery (Default Port 41234)**:
   - Nodes broadcast compact UTF-8 JSON discovery beacons (`DiscoveryPacket`: `protocol="bitchat"`, `version=1`, `transport="lan"`, `peer_id`, `nickname`, `port`, `ssid`, `instance_id`) every 3.0 seconds.
   - Packets are bounded to 1,024 bytes (`MAX_DISCOVERY_PACKET_SIZE`) with strict schema validation.
   - Per-IP rate limiting (10 beacons/s) prevents amplification or discovery flooding.
   - Discovered peers expire automatically after 30 seconds without beacon refresh.
2. **Framed TCP Streaming (Default Port 41235)**:
   - Connections use 8-byte length-prefixed streaming frames (`NativeStreamFramer` / `StreamFramer`):
     `[ 4B Magic (0x42 0x43 0x01 0x00 = "BC\x01\x00") ] [ 4B Big-Endian Length ] [ Payload ]`
   - Bounded buffer limits (65,536 bytes) and connection caps (`MAX_CONCURRENT_CONNECTIONS = 32`) prevent memory exhaustion.
   - Handles TCP segmentation, chunk fragmentation, and concatenated frame delivery transparently.
3. **Transport Switching & Persistent Device Identity**:
   - Switching between `Bluetooth LE`, `Local Network (LAN)`, and `Offline Mode` (`/transport`, Connection Modal, or Settings screen `F3`) cleanly stops the outgoing transport, closes active sockets/GATT links, and tears down ephemeral `NoiseSession` cipher states.
   - Your persistent device identity (`LocalIdentity` stored in `~/.bitchat/identity.json`) is **preserved** across transport switches and application restarts so your `peer_id` and 64-character SHA-256 fingerprint remain stable for trusted contacts.
   - `~/.bitchat/identity.json` stores private keys as hexadecimal strings protected by OS file permissions (POSIX mode `0600`; protected current-user Windows DACL) and cross-process file locking (`identity.json.lock`); keys are not encrypted with a user passphrase at rest in `v0.3.1`.

## Dependency Rules
- Higher layers depend on lower layers, never the reverse.
- The TUI must remain a purely presentational layer (with 16 ms frame-coalesced chat batching, O(1) message history trimming, and background worker thread offloading for blocking I/O).
- Core logic (`rust/bitchat-core`, `protocol`, `crypto`, `mesh`) must be isolated and unit-testable without relying on OS-level BLE abstractions.

## Historical Prototype Area (`nim/`)

An archived pre-Rust evaluation directory exists under `nim/` (`nim/README.md`):
- **Status**: Superseded in production by `rust/bitchat-core` (`bitchat._bitchat_core`) in `v0.3.1`.
- **Runtime Dependency**: `nim/` is strictly an archived historical prototype and is **not** compiled, packaged, or imported at runtime by BitChat.
