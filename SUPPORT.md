# BitChat Support & Troubleshooting Guide

Welcome to the official support guide for **BitChat** (`v0.3.1`). This document explains how to run built-in diagnostics, troubleshoot common Bluetooth Low Energy (BLE) and Local Area Network (LAN) issues, locate diagnostic logs, uninstall or reset the application, and report bugs effectively.

---

## 1. Quick Self-Service Diagnostics

Before opening an issue, run BitChat's built-in hardware and network diagnostics from your terminal:

```bash
# Check installed version
bitchat --version

# Run full OS, Bluetooth, and LAN capability diagnostics
bitchat --configure
```

Inside the interactive Terminal UI (TUI), you can also inspect live state at any time using slash commands:

- `/configure` — Run and display the system capability and transport diagnostic report.
- `/status` — Show your local Peer ID, 64-character SHA-256 identity fingerprint, active transport (`Bluetooth LE`, `Local Network (LAN)`, or `Offline Mode`), and session metrics.
- `/peers` (or press `F4`) — Inspect discovered and connected peers, signal strength, and handshake states.
- `/help` (or press `F1`) — View all available slash commands and keyboard shortcuts.

---

## 2. Diagnostic Log Files & Local Configuration

BitChat stores its local configuration, cryptographic identity, and rotating diagnostic logs in your user home directory:

- **Windows:** `%USERPROFILE%\.bitchat\` (e.g., `C:\Users\<username>\.bitchat\`)
- **Linux & macOS:** `~/.bitchat/` (e.g., `/home/<username>/.bitchat/`)

| File | Description |
| :--- | :--- |
| `bitchat.log` | Primary rotating diagnostic log (up to 10 MB, with backups `bitchat.log.1` through `bitchat.log.5`). Automatic redaction (`SensitiveDataFilter`) strips 64-character hex keys and secret tokens. |
| `config.json` | User settings (`nickname`, `transport`, `lan_discovery_port`, `lan_tcp_port`, `security_mode`, `contacts`). |
| `identity.json` | Your persistent X25519 and Ed25519 keypair (`0600` on POSIX, current-user DACL on Windows). **Never share or upload `identity.json` to any issue report.** |

---

## 3. Common Troubleshooting Scenarios

### 3.1 "`bitchat` is not recognized" After Installation or Uninstall

- **After Installing via `pip`:** Ensure your Python `Scripts` directory (Windows) or `~/.local/bin` (Linux) is on your `PATH`, or use the standalone installer / `uv tool install bitchat-python`.
- **After Uninstalling on Windows:** If `where.exe bitchat` still shows a path such as `C:\Users\<user>\AppData\Local\Programs\Python\Python3XX\Scripts\bitchat.exe`, a secondary Python installation still has a console-script shim installed. Run:
  ```powershell
  bitchat --uninstall
  ```
  Wait 2 seconds for background self-deletion to complete, then open a new terminal window. See [`docs/UNINSTALLATION.md`](docs/UNINSTALLATION.md) for full details.

### 3.2 Bluetooth Low Energy (BLE) Not Detecting Peers

1. **Verify Hardware & Backend:** Run `bitchat --configure` and check the `Bluetooth` section (`Adapter`, `BLE Central`, `BLE Peripheral`, `GATT`, `Permissions`).
2. **Windows:** Ensure Bluetooth is turned **On** in *Windows Settings → Bluetooth & devices*, and ensure your adapter supports Bluetooth 4.0+ LE Peripheral/Central roles (`WinRT`).
3. **Linux:** Ensure the `bluetooth` systemd service (`BlueZ 5.50+`) is active (`sudo systemctl status bluetooth`), your user belongs to the `bluetooth` group or has `CAP_NET_ADMIN` / `CAP_NET_RAW` permissions, and `dbus-fast` is installed. See [`docs/platform/LINUX.md`](docs/platform/LINUX.md).
4. **macOS:** macOS (`Darwin`) has basic BLE Central scanning via `bleak` (`CoreBluetooth`), but does not currently implement the BitChat BLE Peripheral (GATT server) role (`PlatformKind.OTHER`). Use **Local Network (LAN)** mode on macOS for bidirectional discovery. See [`docs/platform/MACOS.md`](docs/platform/MACOS.md).

### 3.3 Local Network (LAN) Peers Not Appearing

1. **Check Firewall Rules:** Runtime LAN discovery uses **UDP port `41234`** (broadcast) and **TCP port `41235`** (framed stream connections) by default (configurable via `lan_discovery_port` and `lan_tcp_port` in `~/.bitchat/config.json`). Ensure your firewall allows inbound/outbound traffic on these ports. Note that `bitchat --configure` also probes UDP `24024` and TCP `24025` for socket-binding diagnostics.
2. **Client Isolation / Guest Wi-Fi:** Public or corporate Wi-Fi networks with AP Client Isolation block UDP subnet broadcasts and direct peer-to-peer TCP connections. Ensure both devices are on a local subnet that permits local traffic, or switch to `Bluetooth LE`.

### 3.4 Corrupted Configuration or Identity Reset

- If `~/.bitchat/config.json` contains invalid JSON, BitChat warns on startup and falls back to default settings, or you can delete `config.json` to regenerate defaults.
- If `~/.bitchat/identity.json` is corrupted, BitChat automatically backs it up to `identity.json.corrupt.<timestamp>` before generating a new identity when `load_or_create_identity()` runs.

---

## 4. Documentation Resources

Before filing a ticket, check the relevant guide in [`docs/INDEX.md`](docs/INDEX.md):

- **Installation & Downloads:** [`docs/DOWNLOAD.md`](docs/DOWNLOAD.md)
- **Windows Guide:** [`docs/platform/WINDOWS.md`](docs/platform/WINDOWS.md)
- **Linux Guide:** [`docs/platform/LINUX.md`](docs/platform/LINUX.md)
- **macOS Status:** [`docs/platform/MACOS.md`](docs/platform/MACOS.md)
- **Uninstallation & Cleanup:** [`docs/UNINSTALLATION.md`](docs/UNINSTALLATION.md)
- **Architecture & Rust Core:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- **Protocol & Compatibility:** [`docs/protocol/OVERVIEW.md`](docs/protocol/OVERVIEW.md) and [`docs/protocol/COMPATIBILITY.md`](docs/protocol/COMPATIBILITY.md)

---

## 5. Where to Open Issues

| Topic | Where to Report |
| :--- | :--- |
| **Bug Reports** | [Open a Bug Report](https://github.com/Java-Mx/bitchat-python/issues/new?template=bug_report.md) (include `bitchat --version` and `bitchat --configure` output) |
| **Feature Requests** | [Open a Feature Request](https://github.com/Java-Mx/bitchat-python/issues/new?template=feature_request.md) |
| **Protocol / Wire Framing Issues** | [Open a Protocol Issue](https://github.com/Java-Mx/bitchat-python/issues/new?template=protocol_issue.md) |
| **Cross-Client Interoperability** | [Open an Interoperability Issue](https://github.com/Java-Mx/bitchat-python/issues/new?template=interoperability_issue.md) |
| **Security Vulnerabilities** | **DO NOT open a public issue.** Report privately via [GitHub Security Advisories](https://github.com/Java-Mx/bitchat-python/security/advisories/new) (see [`SECURITY.md`](SECURITY.md)). |
| **Code of Conduct Concerns** | See the reporting instructions in [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). |
