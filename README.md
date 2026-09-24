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

## Table of Contents
- [Overview](#overview)
- [Architecture Overview](#architecture-overview)
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
  - [3. Discovering Nearby BLE Nodes](#3-discovering-nearby-ble-nodes)
  - [4. Connecting to a Peer](#4-connecting-to-a-peer)
  - [5. Public Mesh Broadcasting](#5-public-mesh-broadcasting)
  - [6. Encrypted Direct Messaging (Noise XX)](#6-encrypted-direct-messaging-noise-xx)
  - [7. Switching Conversation Contexts](#7-switching-conversation-contexts)
  - [8. Command Palette & Autocomplete](#8-command-palette--autocomplete)
  - [9. Appearance & Theme Customization (F2)](#9-appearance--theme-customization-f2)
  - [10. Dynamic Keybindings & Settings (F3)](#10-dynamic-keybindings--settings-f3)
- [Keyboard Shortcuts Reference](#keyboard-shortcuts-reference)
- [Slash Commands Reference](#slash-commands-reference)
- [OS-Specific Bluetooth Setup & Troubleshooting](#os-specific-bluetooth-setup--troubleshooting)
  - [Windows](#windows)
  - [Linux (Ubuntu / Debian / Arch)](#linux-ubuntu--debian--arch)
  - [macOS](#macos)
- [Feature Status](#feature-status)
- [Hardware & Two-PC BLE Validation Status](#hardware--two-pc-ble-validation-status)
- [Development & Testing](#development--testing)
- [Reference Implementation](#reference-implementation)
- [Security Notice](#security-notice)
- [License](#license)

---

## Overview
BitChat Python is an asynchronous terminal client implementing the BitChat protocol over Bluetooth Low Energy (BLE). It aims to be fully protocol-compatible with the Rust reference implementation.

**Current Status:** Phase 10 — Strict Functional Repair, TUI Interaction Hardening, and Full-System Integration complete and verified. Features an edge-to-edge terminal dashboard composition utilizing 100% of the viewport, an authoritative dynamic keybinding subsystem with atomic configuration persistence, runtime appearance customization (density, timestamps, accent palettes), centered panel titles, non-shifting borderless buttons, standard IDE-style command completion, natural `@peer` direct messaging / context switching, multi-hop mesh routing with store-and-forward delivery, and 563 passing automated tests.

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
BLE Transport (BLEManager, BLEScanner, BLEConnection, BLETransport, BLEServer)
  │
  ▼
Operating System Bluetooth APIs (WinRT / Bleak)
```

---

## Prerequisites & System Requirements

Before downloading and installing BitChat Python, ensure your system satisfies:

1. **Python 3.12 or Higher:**
   - Check with: `python --version` or `python3 --version`.
2. **Bluetooth 4.2+ / 5.0+ Hardware Adapter:**
   - Must support BLE (Bluetooth Low Energy) Central and Peripheral roles.
   - Bluetooth must be powered on in your operating system settings.
3. **Operating System Support:**
   - **Windows 10 / 11:** Uses Windows WinRT APIs (no external Bluetooth daemons needed).
   - **Linux:** Requires BlueZ (`bluez`, `dbus`, `bluetoothd`) and a running Bluetooth service.
   - **macOS (12+):** Requires Bluetooth permission granted to your Terminal / iTerm.
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

### 3. Discovering Nearby BLE Nodes
* BitChat automatically scans in the background upon launch.
* To explicitly trigger a discovery cycle, type:
  ```text
  /scan
  ```
* Nearby BitChat nodes will appear in the `Peers (BLE Mesh)` sidebar.

### 4. Connecting to a Peer
* To list discovered peers and their signal strengths in the chat view:
  ```text
  /connect
  ```
* To establish a direct BLE connection:
  ```text
  # Connect by nickname:
  /connect Bob

  # Connect by BLE MAC / device address:
  /connect 11:22:33:44:55:66
  ```

### 5. Public Mesh Broadcasting
* To broadcast a message across the entire local mesh room:
  ```text
  Hello everyone on the mesh!
  ```
* Messages sent to `#public` are relayed hop-by-hop up to TTL 7 with anti-looping deduplication and 10–50ms randomized jitter. If intermediate nodes are offline, the Store-and-Forward queue holds packets until routes become available.

### 6. Encrypted Direct Messaging (Noise XX)
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

### 7. Switching Conversation Contexts
* To switch your active focus to a private 1-on-1 room with a peer without sending an immediate message, type:
  ```text
  @Bob
  ```
* The prompt changes from `#public >` to `@Bob >`. Messages you type will now be routed directly to Bob.
* To return to the public broadcast room, type:
  ```text
  /public
  ```

### 8. Command Palette & Autocomplete
* Type `/` to open the command palette above the prompt.
* Use `Up` and `Down` arrow keys to browse commands.
* Press `Tab` or `Enter` to complete the command into the input box.
* Type `@` to view suggestions for online and known peers, and press `Tab` to complete their name.

### 9. Appearance & Theme Customization (F2)
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

### 10. Dynamic Keybindings & Settings (F3)
Press `F3` (or click `Settings` or type `/settings`) to configure:
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
| `/connect` | `/connect [address\|peer]` | Connect to peer BLE address or list discovered peers | Network |
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
- ✅ Implemented: 563 automated test cases covering protocol, crypto, fragmentation, mesh routing, store-and-forward, BLE mocks, and full interactive TUI lifecycle
- 🚧 Planned: Persistent message database (SQLite)
- 🚧 Planned: Physical multi-PC over-the-air validation on two real Bluetooth machines

---

## Hardware & Two-PC BLE Validation Status
- **Automated Integration:** 100% automated integration and end-to-end suite passing (563 tests, including two-node Noise XX and three-node multi-hop mesh relay).
- **Windows (WinRT):** GATT Server creation and BLE service advertisement verified on host hardware.
- **Linux / macOS:** Central scanning and client transport implemented via Bleak; peripheral advertising pending platform-specific daemon bindings.
- **Physical Hardware Status:** *"Automated integration, simulated multi-node mesh tests, and interactive TUI lifecycle probes are 100% passing. Real two-PC physical over-the-air BLE validation remains UNVERIFIED pending availability of a second physical machine."*

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
