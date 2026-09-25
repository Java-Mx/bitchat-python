<!-- Logo Placeholder -->
<div align="center">
  <h1>BitChat Python</h1>
  <p>Python terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE) and Local Area Network (LAN / Wi-Fi)</p>
  <p>
    <img src="https://img.shields.io/badge/Status-Phase%2011%20(Transport%20Abstraction%20%26%20LAN%20Chat)-blue" alt="Status" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
    <img src="https://img.shields.io/badge/Tests-594%20Passing-brightgreen" alt="Tests" />
    <img src="https://img.shields.io/badge/Type%20Check-Pyright%20Strict-blue" alt="Type Check" />
  </p>
</div>

## Table of Contents
- [Overview](#overview)
- [Architecture Overview](#architecture-overview)
- [Transport Architecture: Bluetooth & LAN / Wi-Fi](#transport-architecture-bluetooth--lan--wi-fi)
- [Prerequisites & System Requirements](#prerequisites--system-requirements)
- [Download & Installation](#download--installation)
  - [Method 1: Fast Setup with `uv` (Recommended)](#method-1-fast-setup-with-uv-recommended)
  - [Method 2: Standard Python Virtualenv & `pip`](#method-2-standard-python-virtualenv--pip)
- [How to Run BitChat](#how-to-run-bitchat)
  - [Interactive Terminal UI (TUI)](#interactive-terminal-ui-tui)
  - [Headless / Scripted CLI Mode](#headless--scripted-cli-mode)
- [Step-by-Step Usage Guide](#step-by-step-usage-guide)
  - [1. User Interface Layout](#1-user-interface-layout)
  - [2. Setting Your Nickname](#2-setting-your-nickname)
  - [3. Switching Network Transports (Bluetooth / LAN)](#3-switching-network-transports-bluetooth--lan)
  - [4. Discovering Nearby BLE / LAN Nodes](#4-discovering-nearby-ble--lan-nodes)
  - [5. Connecting to a Peer](#5-connecting-to-a-peer)
  - [6. Public Mesh Broadcasting](#6-public-mesh-broadcasting)
  - [7. Encrypted Direct Messaging (Noise XX)](#7-encrypted-direct-messaging-noise-xx)
  - [8. Switching Conversation Contexts](#8-switching-conversation-contexts)
  - [9. Command Palette & Autocomplete](#9-command-palette--autocomplete)
  - [10. Appearance & Theme Customization (F2)](#10-appearance--theme-customization-f2)
  - [11. Dynamic Keybindings & Settings (F3)](#11-dynamic-keybindings--settings-f3)
- [Keyboard Shortcuts Reference](#keyboard-shortcuts-reference)
- [Slash Commands Reference](#slash-commands-reference)
- [OS-Specific Bluetooth & Network Setup](#os-specific-bluetooth--network-setup)
  - [Windows](#windows)
  - [Linux (Ubuntu / Debian / Arch)](#linux-ubuntu--debian--arch)
  - [macOS](#macos)
- [Feature Status](#feature-status)
- [Hardware & Two-PC Validation Status](#hardware--two-pc-validation-status)
- [Development & Testing](#development--testing)
- [Reference Implementation](#reference-implementation)
- [Security Notice](#security-notice)
- [License](#license)

---

## Overview
BitChat Python is an asynchronous terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE) and Local Area Network (LAN / Wi-Fi). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 11 — Transport Abstraction Layer & LAN/Wi-Fi Chat complete and verified. Introduces an abstract transport boundary (`BaseTransport`) enabling seamless runtime switching between Bluetooth Low Energy and high-performance local network sockets (UDP broadcast discovery on port 41234 + framed TCP streaming on port 41235). Features transport-independent Noise XX encryption, multi-hop mesh routing, automatic Windows adapter & Wi-Fi SSID telemetry, fresh ephemeral identity generation upon transport change to preserve cryptographic unlinkability, and 594 passing automated tests with zero linter or type-checking diagnostics.

---

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
Transport Abstraction Layer (BaseTransport)
  ├── Bluetooth Low Energy (BLEManager, BLEServer via Bleak/WinRT)
  └── LAN / Wi-Fi (UDP Discovery 41234 + Framed TCP Streaming 41235)
```

---

## Transport Architecture: Bluetooth & LAN / Wi-Fi

BitChat implements a pluggable transport architecture under `bitchat.transport.base.BaseTransport`, enabling zero-duplication protocol and crypto operations across distinct communication media:

1. **Bluetooth Low Energy (BLE)**:
   * **GATT Peripheral Server & Advertiser**: Advertises BitChat service UUID (`F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`) and receives inbound framed writes.
   * **Central Scanner & Client**: Discovers nearby BitChat nodes and establishes point-to-point BLE links.
   * **Automatic MTU Fragmentation & Pacing**: Splits packets >500 bytes into <=150-byte fragments paced at 20ms intervals.

2. **Local Area Network (LAN / Wi-Fi)**:
   * **Zero-Config UDP Discovery (Port 41234)**: Broadcasts compact JSON beacons (`BC_DISCOVER_V1`) carrying node nickname, peer ID, TCP port, and Wi-Fi SSID. Includes 10 pkts/s per-IP rate limiting and 30-second TTL peer table pruning.
   * **Framed TCP Streaming (Port 41235)**: Direct point-to-point peer links framed with an 8-byte header (`BC\x01\x00` magic + 4-byte big-endian payload length) and bounded 64KB frame limits.
   * **Adapter & Wi-Fi Telemetry**: Detects active network interfaces, local non-loopback IPv4 addresses, and real-time Windows Wi-Fi SSIDs (`netsh wlan show interfaces`).

3. **Runtime Transport Switching & Privacy Guarantees**:
   * Switch transports instantly using `/transport [bluetooth|lan]` or via the **Settings Modal (`F3`)**.
   * **Fresh Ephemeral Identity**: Switching transport completely terminates active connections, tears down open Noise XX sessions, clears in-memory peer routing tables, and generates a **fresh transport-scoped identity** (`LocalIdentity.generate()`).
   * Permanent disk storage (`~/.bitchat/identity.json`) is never modified or leaked across transports, preventing identity tracking across Bluetooth and Wi-Fi networks.

---

## Prerequisites & System Requirements

Before downloading and installing BitChat Python, ensure your system satisfies:

1. **Python 3.12 or Higher:**
   - Check with: `python --version` or `python3 --version`.
2. **Network or Bluetooth Adapter:**
   - **LAN / Wi-Fi Mode:** Any standard Wi-Fi or Ethernet adapter connected to a local subnet. (No Bluetooth required!)
   - **Bluetooth Mode:** Bluetooth 4.2+ / 5.0+ adapter supporting BLE Central and Peripheral roles.
3. **Operating System Support:**
   - **Windows 10 / 11:** Native WinRT APIs for BLE; native async sockets for LAN.
   - **Linux:** BlueZ (`bluez`, `dbus`, `bluetoothd`) for BLE; native sockets for LAN.
   - **macOS (12+):** Terminal Bluetooth permission for BLE; native sockets for LAN.
4. **Git:**
   - Check with: `git --version`.

---

## Download & Installation

### Method 1: Fast Setup with `uv` (Recommended)

[`uv`](https://github.com/astral-sh/uv) is an extremely fast Python package manager that handles Python versions, virtual environments, and dependencies automatically.

1. **Install `uv` (if not already installed):**
   * **Windows (PowerShell):**
     ```powershell
     powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
     ```
   * **macOS / Linux:**
     ```bash
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```

2. **Clone the Repository:**
   ```bash
   git clone https://github.com/Java-Mx/bitchat-python.git
   cd bitchat-python
   ```

3. **Install Dependencies:**
   ```bash
   # Synchronize standard application dependencies:
   uv sync

   # Or synchronize all dependencies including test and linting tools:
   uv sync --all-groups
   ```

---

### Method 2: Standard Python Virtualenv & `pip`

If you prefer standard Python tooling without `uv`:

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/Java-Mx/bitchat-python.git
   cd bitchat-python
   ```

2. **Create and Activate a Virtual Environment:**
   * **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   * **Windows (CMD):**
     ```cmd
     python -m venv .venv
     .venv\Scripts\activate.bat
     ```
   * **macOS / Linux:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install the Package in Editable Mode:**
   ```bash
   # Production runtime dependencies:
   pip install -e .

   # Or with development & testing dependencies:
   pip install -e ".[dev]"
   ```

---

## How to Run BitChat

### Interactive Terminal UI (TUI)
This is the default and recommended mode. It launches the full dashboard with the peer list, conversation log, action buttons, command palette, and status bar.

* With `uv`:
  ```bash
  uv run bitchat
  ```
* With standard virtualenv:
  ```bash
  bitchat
  ```
* Alternatively, run as a module:
  ```bash
  python -m bitchat
  ```

### Headless / Scripted CLI Mode
If you are running over a headless SSH session, in automated scripts, or prefer a minimal command-line stream:

```bash
uv run bitchat --cli
```

### Command-Line Arguments
```text
options:
  -h, --help  show this help message and exit
  --cli       Run in headless / CLI mode instead of interactive TUI
  --tui       Force interactive TUI mode even if stdin is not a TTY
```

---

## Step-by-Step Usage Guide

### 1. User Interface Layout
When BitChat launches, the terminal displays an edge-to-edge dashboard:
* **Top Header & Action Strip:** Shows the application logo, connection indicator, and quick-action buttons (`Edit Theme [F2]`, `Settings [F3]`, `Help [F1]`).
* **Left Panel (`Peers (BLE Mesh)`):** Displays your local node ID, active nickname, and a list of all discovered and connected BLE mesh nodes with deterministic color tags and RSSI signal indicators.
* **Center / Right Panel (`Conversation [#public]`):** Displays incoming and outgoing chat messages, delivery status, muted timestamps, and system announcements.
* **Bottom Strip:** Autocomplete popup palette, input prompt (`#public >`), and live status bar showing node ID, active channel, and BLE hardware status.

### 2. Setting Your Nickname
Your initial identity generates a cryptographic Ed25519 keypair and a default nickname. To change your nickname:
* **Option A (Command):** Type `/name Alice` and press `Enter`.
* **Option B (Settings Modal):** Press `F3`, edit the **Nickname** input field, and click **Save Settings**.
* Your new nickname is broadcast over the BLE mesh to announce your node to neighbors.

### 3. Switching Network Transports (Bluetooth / LAN)
You can switch between Bluetooth Low Energy and Local Area Network (Wi-Fi / Ethernet) modes at any time:
* **Option A (Command):**
  ```text
  /transport lan        # Switch to Local Area Network (Wi-Fi) mode
  /transport bluetooth  # Switch to Bluetooth Low Energy mode
  ```
* **Option B (Settings Modal):**
  Press `F3` (or click `Settings`), scroll to **Transport Selection**, select **Bluetooth** or **LAN / Wi-Fi**, and click **Save Settings**.
* When switching transport, BitChat displays:
  `Switched transport to LAN / WI-FI. New secure chat session created. New peer identity: <new_peer_id>`
  The sidebar header dynamically changes to `Peers (LAN / Wi-Fi)` or `Peers (BLE Mesh)`.

### 4. Discovering Nearby BLE / LAN Nodes
* BitChat runs discovery continuously in the background upon launch.
* In **LAN / Wi-Fi mode**, nodes multicast UDP discovery beacons (`BC_DISCOVER_V1`) on port `41234`.
* In **Bluetooth mode**, nodes scan for the BitChat GATT service UUID.
* To explicitly trigger a discovery cycle, type:
  ```text
  /scan
  ```
* Discovered nodes will automatically appear in the left sidebar with their nickname, network endpoint (`ip:port`), or RSSI signal strength.

### 5. Connecting to a Peer
* To list discovered peers in the active transport:
  ```text
  /connect
  ```
* To establish a direct connection:
  ```text
  # Connect by nickname:
  /connect Bob

  # Connect by LAN IP and port:
  /connect 192.168.1.45:41235

  # Connect by BLE MAC address:
  /connect 11:22:33:44:55:66
  ```

### 6. Public Mesh Broadcasting
* To broadcast a message across the entire local mesh room:
  ```text
  Hello everyone on the mesh!
  ```
* Messages sent to `#public` are relayed hop-by-hop up to TTL 7 with anti-looping deduplication and 10–50ms randomized jitter. If intermediate nodes are offline, the Store-and-Forward queue holds packets until routes become available.

### 7. Encrypted Direct Messaging (Noise XX)
Send private, end-to-end encrypted messages to any peer using either syntax:
* **Inline Syntax:**
  ```text
  @Bob Hi Bob, this message is encrypted with Noise XX!
  ```
* **Command Syntax:**
  ```text
  /dm Bob Hi Bob, this message is encrypted with Noise XX!
  ```
* Messages are authenticated using Ed25519 signatures, encrypted with ChaCha20-Poly1305, and protected by a 1024-entry replay window.

### 8. Switching Conversation Contexts
* To switch your active focus to a private 1-on-1 room with a peer without sending an immediate message, type:
  ```text
  @Bob
  ```
* The prompt changes from `#public >` to `@Bob >`. Messages you type will now be routed directly to Bob.
* To return to the public broadcast room, type:
  ```text
  /public
  ```

### 9. Command Palette & Autocomplete
* Type `/` to open the command palette above the prompt.
* Use `Up` and `Down` arrow keys to browse commands.
* Press `Tab` or `Enter` to complete the command into the input box.
* Type `@` to view suggestions for online and known peers, and press `Tab` to complete their name.

### 10. Appearance & Theme Customization (F2)
Press `F2` (or click `Edit Theme` or type `/edit`) to open the theme dialogue:
* **Display Density:**
  * **Comfortable:** Default multi-line layout with generous spacing.
  * **Compact:** High-density single-line view maximizing visible chat history.
* **Message Timestamps:**
  * **Show Timestamps:** Displays timestamps (`12:34:56`).
  * **Hide Timestamps:** Hides timestamps for a cleaner view.
* **Accent Tone:**
  * **Midnight Blue** (`#58a6ff`)
  * **Cyber Cyan** (`#39c5bb`)
  * **Terminal Emerald** (`#3fb950`)
  * **Amethyst Purple** (`#bc8cff`)
* Click **Apply Theme** to save changes immediately to `~/.bitchat/config.json`.

### 11. Dynamic Keybindings & Settings (F3)
Press `F3` (or click `Settings` or type `/settings`) to configure:
* **Transport Selection:** Toggle active transport medium between **Bluetooth** and **LAN / Wi-Fi**.
* **Node Parameters:** Nickname, channel, and BLE advertisement state.
* **Dynamic Keybindings:** Reassign any of the 7 application actions:
  * Help
  * Edit Theme
  * Settings
  * Clear Chat
  * Quit
  * Scroll Up
  * Scroll Down
* **Conflict Detection:** The UI validates key inputs in real-time, preventing duplicate assignments or empty keys.
* **Restore Defaults:** Resets all keybindings back to factory defaults.
* Click **Save Settings** to atomically write your preferences to `~/.bitchat/config.json`.

---

## Keyboard Shortcuts Reference

| Shortcut (Default) | Action Method | Description |
|---|---|---|
| `F1` | `help` | Toggle the Help Screen dialogue |
| `F2` | `edit_theme` | Toggle the Appearance & Theme Editor |
| `F3` | `settings` | Toggle Node Settings & Keybinding Configuration |
| `Ctrl+L` | `clear_chat` | Clear the current conversation message log |
| `Ctrl+Q` | `quit` | Gracefully terminate and exit BitChat |
| `PageUp` | `scroll_up` | Scroll conversation view upwards |
| `PageDown` | `scroll_down` | Scroll conversation view downwards |
| `Escape` | `dismiss` | Close open modals or dismiss the autocomplete palette |
| `Tab` | Autocomplete | Accept selected command or peer suggestion without submitting |

*Note: All shortcuts can be customized via the Settings modal (`F3`).*

---

## Slash Commands Reference

| Command | Usage | Description | Category |
|---|---|---|---|
| `/transport` | `/transport [bluetooth\|lan]` | Switch network medium and generate fresh peer identity | Network |
| `/connect` | `/connect [address\|peer]` | Connect to peer address or list discovered peers | Network |
| `/disconnect` | `/disconnect [address]` | Disconnect from peer or all connected peers | Network |
| `/scan` | `/scan` | Trigger active scan for nearby BitChat nodes | Network |
| `/online` | `/online` | List connected and known mesh peers | Network |
| `/peers` | `/peers` | Inspect connected and nearby peers | Network |
| `/name` | `/name <nickname>` | Set local nickname and broadcast announcement | Identity |
| `/dm` | `/dm <peer> <message>` | Send Noise XX end-to-end encrypted direct message | Chat |
| `@<peer>` | `@<peer> [message]` | Send direct message or switch conversation context | Chat |
| `/public` | `/public` | Switch active conversation context back to `#public` | Chat |
| `/info` | `/info <peer>` | View peer public key fingerprint and crypto state | Security |
| `/status` | `/status` | Show network, mesh, and security diagnostics | System |
| `/settings` | `/settings` | Open node parameters and keybinding editor | System |
| `/edit` | `/edit` | Open appearance, density, and accent theme editor | UI |
| `/large` | `/large <peer>` | Send 1000B test fragmented packet (testing) | Debug |
| `/clear` | `/clear` | Clear conversation history from screen | System |
| `/help` | `/help` | Display command reference | System |
| `/exit` | `/exit` | Gracefully quit BitChat | System |

---

## OS-Specific Bluetooth Setup & Troubleshooting

### Windows
* Ensure Bluetooth is enabled in **Windows Settings > Bluetooth & devices**.
* BitChat uses native Windows WinRT Bluetooth APIs. No third-party drivers or external tools are required.
* If discovery does not find peers, ensure your Windows device is not in Airplane Mode.

### Linux (Ubuntu / Debian / Arch)
1. Install BlueZ and D-Bus packages:
   ```bash
   # Debian / Ubuntu:
   sudo apt update && sudo apt install -y bluez dbus

   # Arch Linux:
   sudo pacman -S bluez bluez-utils
   ```
2. Enable and start the Bluetooth service:
   ```bash
   sudo systemctl enable --now bluetooth
   ```
3. Grant permissions to your user account:
   ```bash
   sudo usermod -aG bluetooth $USER
   ```
   *(Log out and back in for group changes to take effect).*
4. Check that your Bluetooth adapter is not software-blocked:
   ```bash
   rfkill unblock bluetooth
   bluetoothctl power on
   ```

### macOS
* Ensure Bluetooth is turned ON in **System Settings > Bluetooth**.
* When BitChat is launched for the first time, macOS will request Bluetooth access for your terminal emulator (**Terminal**, **iTerm2**, or **Ghostty**). Click **Allow**.
* If permission was previously denied, navigate to:
  `System Settings > Privacy & Security > Bluetooth` and toggle your terminal application ON.

---

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
- ✅ Implemented: Transport abstraction (`BaseTransport`) decoupling application, protocol, and crypto layers from physical link media
- ✅ Implemented: Local Area Network (LAN / Wi-Fi) transport backend (`LANTransport`) with zero-configuration UDP discovery (port 41234) and framed TCP streaming (port 41235)
- ✅ Implemented: Length-prefixed streaming framer (`StreamFramer`) with 8-byte header (`BC\x01\x00` magic + length) and bounded buffer validation
- ✅ Implemented: Live Windows network interface, IP address, and Wi-Fi SSID telemetry (`NetworkAdapterManager`)
- ✅ Implemented: Dynamic transport switching (`/transport`, Settings `F3`) with automatic session teardown and fresh ephemeral identity generation
- ✅ Implemented: 594 automated test cases covering protocol, crypto, fragmentation, mesh routing, store-and-forward, BLE mocks, LAN discovery, TCP framing, and full interactive TUI lifecycle
- 🚧 Planned: Persistent message database (SQLite)
- 🚧 Planned: Physical multi-PC validation across two distinct physical machines

---

## Hardware & Two-PC Validation Status
- **Automated Integration:** 100% automated integration and end-to-end suite passing (594 tests, including two-node Noise XX over BLE and two-node Noise XX over framed TCP LAN).
- **Windows (WinRT):** GATT Server creation, BLE service advertisement, and local Wi-Fi SSID queries verified on host hardware.
- **LAN / Wi-Fi Localhost & Local Subnet:** Fully verified. UDP discovery beacons and point-to-point framed TCP connections establish encrypted Noise XX handshakes and route messages cleanly.
- **Physical Two-PC Status:** *"Automated integration, simulated multi-node mesh tests, and interactive TUI lifecycle probes are 100% passing. Real two-PC physical over-the-air validation on two separate physical hardware machines remains UNVERIFIED pending availability of a second physical machine."*

---

## Development & Testing

### Running Tests
Execute the full test suite with `pytest`:
```bash
uv run pytest
```

### Static Type Checking
Verify static typing with strict Pyright checks:
```bash
uv run pyright
```

### Code Formatting & Linting
Ensure compliance with PEP 8 and project style guidelines:
```bash
uv run ruff check .
uv run ruff format --check .
```

---

## Reference Implementation
The reference implementation is [bitchat-tui](https://github.com/vaibhav-mattoo/bitchat-tui) written in Rust. This repository aims for protocol compatibility with the Rust implementation but does not copy its code.

---

## Security Notice
This project is in active development. There has been no formal security audit. Do not use for high-risk communications.

---

## License
MIT
