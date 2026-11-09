# macOS Platform Support & Status (`v0.3.1`)

> **Platform Classification:** On macOS (`sys.platform == "darwin"`), `bitchat.platform.detection.detect_platform()` classifies the operating system as `PlatformKind.OTHER`. While **Local Area Network (LAN)** messaging, **Offline Mode**, the **Rust native core (`bitchat._bitchat_core`)**, cryptography, and the **Textual TUI / CLI** work on macOS when installed from source, **BLE Peripheral (GATT server & advertising) is not implemented on macOS in `v0.3.1`**.

---

## 1. Capability Matrix on macOS (`v0.3.1`)

| Subsystem | macOS Status | Technical Details |
| :--- | :--- | :--- |
| **Local Area Network (LAN) Transport** | ✅ Supported | Full UDP broadcast discovery (default port `41234`) and framed TCP streaming (default port `41235`). Recommended transport on macOS. |
| **Offline Mode** | ✅ Supported | Full local UI, configuration, identity management, and slash commands with zero radio activity. |
| **Rust Native Core (`bitchat._bitchat_core`)** | ✅ Supported (Source Build) | Compiles natively on macOS (`x86_64` and `arm64` Apple Silicon) via `cargo` and `maturin`. |
| **BLE Central Role (Scanning & Client)** | ⚠️ Experimental | Uses `bleak`'s `CoreBluetooth` backend when Bluetooth permission is granted to your Terminal app; not hardware-validated in CI. |
| **BLE Peripheral Role (GATT Server & Advertising)** | ❌ Not Implemented | `peripheral_backend_implemented()` returns `False` on `PlatformKind.OTHER`. Only Windows (`WinRT`) and Linux (`BlueZ D-Bus`) implement the GATT peripheral server in `v0.3.1`. |
| **Prebuilt Binary Installer (`.dmg` / `.pkg`)** | ❌ Not Shipped | Official `v0.3.1` binary installers target Windows (`x64`) and Linux (`x86_64`). macOS users install from source via `uv`. |

---

## 2. Installing from Source on macOS

1. Install **Python 3.10+**, **Rust (`rustup`)**, and **uv**:
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. Clone the repository and build the native Rust extension:
   ```bash
   git clone https://github.com/Java-Mx/bitchat-python.git
   cd bitchat-python
   uv sync --all-groups
   uv run --no-sync maturin develop --release
   ```
3. Run diagnostics and launch BitChat:
   ```bash
   uv run --no-sync bitchat --configure
   uv run --no-sync bitchat --tui
   ```

---

## 3. macOS Bluetooth & Firewall Notes

- **Bluetooth Permissions (`CoreBluetooth`):** If experimenting with BLE Central scanning on macOS 11+, grant Bluetooth access to your terminal emulator (Terminal.app, iTerm2, Alacritty, or VS Code) under **System Settings → Privacy & Security → Bluetooth**. Because macOS cannot host the BitChat BLE GATT server in `v0.3.1`, two macOS devices cannot discover each other over BLE alone—at least one peer must act as a BLE Peripheral (Windows or Linux), or both peers should switch to **Local Network (LAN)** mode (`/transport lan`).
- **macOS Application Firewall:** When using **Local Network (LAN)** mode, allow incoming connections for Python / `bitchat` if prompted by the macOS firewall (UDP port `41234` and TCP port `41235`).
- **Local Storage Location:** Configuration and keys are stored in `~/.bitchat/` (`~/.bitchat/identity.json` with `0600` permissions, `~/.bitchat/config.json`, and `~/.bitchat/bitchat.log`).
