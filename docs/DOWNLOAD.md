# Download BitChat for Windows (x64)

<p align="center">
  <img src="download/assets/bitchat-wordmark-dark.png" alt="BitChat" width="280" />
</p>

## Official Windows Release Package

| Field | Value |
|---|---|
| **Application** | BitChat (`Java-Mx.BitChat`) |
| **Version** | `0.3.1` |
| **Publisher** | `Java-Mx` |
| **Platform / Architecture** | Windows 10 (1809+) & Windows 11 (`x64`) |
| **Installer Filename** | `BitChat-0.3.1-windows-x64.exe` |
| **Installer File Size** | 17.32 MB (18,165,765 bytes) |
| **Release Date** | `2026-11-09` |
| **SHA-256 Checksum** | `2A2D68F5B7B975620AF7197030A6DD068C8A0D096AEEECFC69F5DBB3FA84A75A` |
| **Digital Signature Status** | NotSigned — No commercial code-signing certificate configured yet. Do not treat as a Microsoft-verified publisher until a real certificate signature is verified. Always verify the SHA-256 checksum below. |
| **Official Download URL** | [https://github.com/Java-Mx/bitchat-python/releases/download/v0.3.1/BitChat-0.3.1-windows-x64.exe](https://github.com/Java-Mx/bitchat-python/releases/download/v0.3.1/BitChat-0.3.1-windows-x64.exe) |
| **All Releases** | [GitHub Releases](https://github.com/Java-Mx/bitchat-python/releases) |

---

## Legal Notices & Pre-Download Review

Before downloading or installing BitChat, please review:

1. **[BitChat Terms of Use](../TERMS_OF_USE.md)** *(Draft — pending publisher/legal review)*
2. **[BitChat Privacy Policy](../PRIVACY_POLICY.md)** *(Draft — audited zero-telemetry, no accounts, local-only identity keys)*
3. **[MIT License](../LICENSE)** and **[Security Policy](../SECURITY.md)**

> **Privacy Commitment:** No personal information, email address, account creation, tracking, or marketing consent is required to download or use BitChat. Acknowledging the Privacy Policy during download or installation is informational only and never authorizes optional data collection.

---

## System Requirements

- **Operating System:** Windows 10 version 1809 (build 17763) or later, or Windows 11 (x64).
- **Hardware / Network:** Bluetooth 4.0+ Low Energy (BLE) adapter with Windows WinRT support, and/or Wi-Fi or Ethernet Local Area Network (LAN).
- **Disk Space:** At least 80 MB of free disk space.
- **Permissions:** Standard user account (installs to `%LOCALAPPDATA%\Programs\BitChat` by default; no Administrator privileges required).
- **Dependencies:** None (Python 3 runtime, Rust `bitchat._bitchat_core` native extension, Textual TUI, Bleak WinRT stack, and Cryptography are fully bundled).

---

## All Official `v0.3.1` Release Assets & SHA-256 Checksums

All 13 release artifacts are available on the [Official GitHub Release (`v0.3.1`)](https://github.com/Java-Mx/bitchat-python/releases/tag/v0.3.1):

| Platform / Format | Asset Filename | SHA-256 Checksum |
|---|---|---|
| **Windows x64 Installer** | `BitChat-0.3.1-windows-x64.exe` | `2A2D68F5B7B975620AF7197030A6DD068C8A0D096AEEECFC69F5DBB3FA84A75A` |
| **Linux Debian/Ubuntu (`amd64`)** | `bitchat_0.3.1_amd64.deb` | `78102FE305DFC09FFCC2B125C2E3F415800673BEFE5BA8712224B96AFD7C466F` |
| **Linux AppImage (`x86_64`)** | `BitChat-0.3.1-x86_64.AppImage` | `3DE90657D6383DC11A753CA008B9162BC74C46AD8F5158F4B956F96393773152` |
| **Linux Flatpak (`x86_64`)** | `BitChat-0.3.1-x86_64.flatpak` | `DBCFDBB8456A5D68BA87003A328B1D53C00AA0B400B104DB0D353A31C114FA95` |
| **Windows Wheel (`cp312`)** | `bitchat_python-0.3.1-cp312-cp312-win_amd64.whl` | `303C0AE1D97D0C5594A222EC74FC142158DF9D45BBF37FCBC00AE3766DC3CA08` |
| **Linux Wheel (`cp312`)** | `bitchat_python-0.3.1-cp312-cp312-linux_x86_64.whl` | `BB13B8C8469ED15EC0AA1E176D84F3EDB37010903DE3C9A3B76B6F0C08B230E3` |
| **Source Archive (`sdist`)** | `bitchat_python-0.3.1.tar.gz` | `8AD4DC5DCDA52E2A027E2EB6D12A13E7FAEF5F350B972F94093EB4A7B80684E9` |

---

## Checksum & Signature Verification

After downloading `BitChat-0.3.1-windows-x64.exe`, verify its integrity in PowerShell before running Setup:

```powershell
# 1. Verify SHA-256 Checksum
Get-FileHash .\BitChat-0.3.1-windows-x64.exe -Algorithm SHA256
# Expected: 2A2D68F5B7B975620AF7197030A6DD068C8A0D096AEEECFC69F5DBB3FA84A75A

# 2. Inspect Authenticode Signature
Get-AuthenticodeSignature .\BitChat-0.3.1-windows-x64.exe | Format-List *
```

---

## Installation, Startup, Upgrade & Uninstallation

### Interactive Setup Wizard
Run `BitChat-0.3.1-windows-x64.exe` to step through the 7-screen setup wizard:
1. **Welcome** — BitChat branding, version `0.3.1`, and publisher (`Java-Mx`).
2. **Terms of Use** — Scrollable Terms of Use with required acceptance checkbox.
3. **Privacy Policy** — Scrollable Privacy Policy with required acknowledgment checkbox.
4. **Installation Location** — Defaults to `%LOCALAPPDATA%\Programs\BitChat` with permission, disk-space, and conflict validation.
5. **Installation Options** — Configure Desktop shortcut (enabled), Start Menu shortcut (enabled), user `PATH` integration (enabled), Launch after installation (enabled), Start with Windows after sign-in (disabled by default), and Windows Installed Apps uninstaller entry (enabled).
6. **Installation Progress** — Real-time extraction progress and automatic rollback on interruption.
7. **Completion** — Summary of installed version, path, `PATH` status, startup configuration, and immediate launch option.

### Command-Line & WinGet Usage
```powershell
# Launch interactive TUI
bitchat --tui

# Launch headless CLI mode
bitchat --cli

# Inspect version, help, and hardware diagnostics
bitchat --version
bitchat --help
bitchat --configure

# Check or toggle per-user Windows sign-in startup
bitchat --startup status
bitchat --startup enable
bitchat --startup disable

# Preview or run uninstallation (see docs/UNINSTALLATION.md)
bitchat --uninstall --dry-run
bitchat --uninstall
bitchat --uninstall --remove-user-data --yes
```

### Troubleshooting
- **`bitchat` command not recognized:** Reopen your PowerShell or Command Prompt window after installation so the updated user `PATH` environment variable is loaded.
- **Uninstalling completely:** See [`docs/UNINSTALLATION.md`](UNINSTALLATION.md) for normal vs. complete removal (`--remove-user-data`).
- **Windows Defender SmartScreen:** See [`docs/platform/WINDOWS.md`](platform/WINDOWS.md) for the distinction between Authenticode signature validity, publisher identity, and SmartScreen download reputation. Never disable Windows Defender or SmartScreen; always verify the SHA-256 checksum above.
