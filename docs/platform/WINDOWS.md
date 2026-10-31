# Windows Platform & Installer 2.0 Guide

<p align="center">
  <img src="../download/assets/bitchat-wordmark-dark.png" alt="BitChat" width="260" />
</p>

> **BLE LOGIC VERIFIED VIA MOCKS — PHYSICAL TWO-MACHINE HARDWARE TESTING PENDING**
> **WINDOWS INSTALLER 2.0 (`BitChat-0.2.0-windows-x64.exe`) — VERIFIED ON WINDOWS 11 x64**

---

## Contents

1. [System Requirements](#1-system-requirements)
2. [Download & Checksum Verification](#2-download--checksum-verification)
3. [Code Signing, Publisher Identity & Windows SmartScreen](#3-code-signing-publisher-identity--windows-smartscreen)
4. [Windows Installation (Setup Wizard, WinGet & Silent CLI)](#4-windows-installation-setup-wizard-winget--silent-cli)
5. [PATH & Command-Line Integration](#5-path--command-line-integration)
6. [Start BitChat When Windows Starts (Per-User Sign-In Startup)](#6-start-bitchat-when-windows-starts-per-user-sign-in-startup)
7. [Upgrades & Identity Preservation](#7-upgrades--identity-preservation)
8. [Uninstallation & User Data Management](#8-uninstallation--user-data-management)
9. [Legal Documents (Terms of Use & Privacy Policy)](#9-legal-documents-terms-of-use--privacy-policy)
10. [BLE & WinRT Architecture on Windows](#10-ble--winrt-architecture-on-windows)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. System Requirements

- **Operating System:** Windows 10 (version 1809 / build 17763+) or Windows 11 (`x64`).
- **Bluetooth / Network:**
  - Bluetooth 4.0+ BLE-capable adapter with Windows WinRT support, **and/or**
  - Wi-Fi or Ethernet Local Area Network (LAN) for UDP discovery (`24024`/`41234`) and framed TCP (`24025`/`41235`).
- **Disk Space:** Minimum 80 MB free disk space.
- **Privileges:** Standard user account (default user-scope installation into `%LOCALAPPDATA%\Programs\BitChat` requires no Administrator privileges).
- **Bundled Runtime:** Self-contained executable bundle (Python 3 runtime, Textual TUI, Bleak WinRT backend, and Cryptography are bundled; no manual Python, Git, or pip installation is required).

---

## 2. Download & Checksum Verification

Official Windows installers are distributed through [GitHub Releases](https://github.com/Java-Mx/bitchat-python/releases) and the official [Download Page](../download/index.html) ([`docs/DOWNLOAD.md`](../DOWNLOAD.md)).

- **Package Identifier:** `Java-Mx.BitChat`
- **Publisher:** `Java-Mx`
- **Current Installer:** `BitChat-0.2.0-windows-x64.exe`

Before running the installer, verify its cryptographic SHA-256 checksum in PowerShell against the published `BitChat-0.2.0-windows-x64.exe.sha256` release asset:

```powershell
Get-FileHash .\BitChat-0.2.0-windows-x64.exe -Algorithm SHA256
Get-Content .\BitChat-0.2.0-windows-x64.exe.sha256
```

---

## 3. Code Signing, Publisher Identity & Windows SmartScreen

### Understanding Windows Trust Mechanisms

It is critical to distinguish between four separate Windows security concepts:

| Mechanism | What It Proves | How It Is Verified |
|---|---|---|
| **1. Authenticode Signature Validity** | The binary has not been modified or tampered with since it was signed, and the signing certificate chain is valid (plus an RFC3161 timestamp proving when it was signed). | `Get-AuthenticodeSignature .\BitChat-0.2.0-windows-x64.exe` (`Status: Valid`, `TimeStamperCertificate` present). |
| **2. Publisher Identity** | Identifies the legal entity or developer (`SignerCertificate.Subject`) holding the code-signing certificate issued by a trusted Certificate Authority (CA). | Inspecting `SignerCertificate.Subject` and `SignerCertificate.Issuer` in `Get-AuthenticodeSignature` or File Properties → Digital Signatures. |
| **3. Windows Defender SmartScreen Reputation** | Microsoft's cloud reputation scoring for downloaded executables based on aggregate download volume, certificate history, and telemetry across Windows devices. | A valid Authenticode signature provides publisher identity and integrity, **not** immediate SmartScreen reputation. Newly signed certificates (and unsigned open-source binaries) may still display a SmartScreen prompt until download reputation is established. |
| **4. WinGet / Microsoft Store Distribution Trust** | Package manifest validation and automated malware scanning performed by Microsoft's `winget-pkgs` pipeline or Microsoft Store certification. | `winget validate` and upstream PR review in [`microsoft/winget-pkgs`](https://github.com/microsoft/winget-pkgs). |

### Current Release Signing Status

- **Current Local / Community Build Status:** `NotSigned` (no commercial code-signing certificate is currently configured in the build environment). Until a certificate issued to the legal publisher (`Java-Mx`) is configured in GitHub Actions secrets, the installer **cannot** be presented as a Microsoft-verified publisher.
- **Configured CI Signing Pipeline:** Both `packaging/windows/build.py` and `.github/workflows/release.yml` implement full SHA-256 + RFC3161 timestamped Authenticode signing for both `bitchat.exe` and `BitChat-<version>-windows-x64.exe`.
- To enable verified publisher signing in GitHub Actions, configure the following repository secrets/variables:
  - `secrets.WINDOWS_SIGNING_CERT` — Base64-encoded `.pfx` code-signing certificate (never committed to git).
  - `secrets.WINDOWS_SIGNING_PASSWORD` — Password for the `.pfx` certificate.
  - `secrets.WINDOWS_SIGNING_THUMBPRINT` — *(Alternative)* Certificate thumbprint if using a hardware token or cloud signing store.
  - `vars.WINDOWS_TIMESTAMP_URL` — RFC3161 timestamp server (defaults to `http://timestamp.digicert.com`).
  - `vars.WINDOWS_SIGNING_PUBLISHER` — Expected certificate Subject substring to enforce during verification.
  - `vars.WINDOWS_SIGNING_REQUIRED` — Set to `true` to fail the release pipeline if signing credentials are missing or signature verification fails.

### Verifying a Signed Installer

```powershell
$sig = Get-AuthenticodeSignature .\BitChat-0.2.0-windows-x64.exe
$sig | Format-List Status, StatusMessage, SignerCertificate, TimeStamperCertificate
```

---

## 4. Windows Installation (Setup Wizard, WinGet & Silent CLI)

### Interactive Setup Wizard (7 Screens)

Running `BitChat-0.2.0-windows-x64.exe` launches the BitChat Setup Wizard:

1. **Screen 1 — Welcome:** Displays official BitChat branding, version (`0.2.0`), publisher (`Java-Mx`), application summary, and official repository links.
2. **Screen 2 — Terms of Use:** Displays the [`TERMS_OF_USE.md`](../../TERMS_OF_USE.md) draft with a clickable link to the online document and a required, initially unchecked checkbox (`I have read and agree to the BitChat Terms of Use.`). The **Next** button stays disabled until checked.
3. **Screen 3 — Privacy Policy:** Displays the [`PRIVACY_POLICY.md`](../../PRIVACY_POLICY.md) draft with a clickable link and required acknowledgment checkbox (`I have read the BitChat Privacy Policy.`). Clarifies that BitChat collects zero telemetry or account data and that acknowledgment is never consent to tracking or marketing.
4. **Screen 4 — Installation Location:** Defaults to `%LOCALAPPDATA%\Programs\BitChat` (user scope, no admin elevation required). Validates write permissions, free disk space (≥ 80 MB), existing installations, and blocks conflicting paths (drive roots, Windows system folders, or `~/.bitchat` user data directory).
5. **Screen 5 — Installation Options:**

   | Option | Task Name | Default | Behavior |
   |---|---|---|---|
   | Create desktop shortcut | `desktopicon` | **Enabled** | Creates `BitChat.lnk` on the user's Desktop |
   | Create Start Menu shortcut | `startmenuicon` | **Enabled** | Creates Start Menu program group and shortcuts |
   | Add BitChat to current user's PATH | `envPath` | **Enabled** | Appends `{app}` to `HKCU\Environment\Path` without duplication |
   | Launch BitChat after installation | `launchapp` | **Enabled** | Pre-selects immediate launch on the Completion screen |
   | Start BitChat when Windows starts | `startupicon` | **Disabled** | Creates per-user sign-in shortcut in `%APPDATA%\...\Startup\BitChat.lnk` |
   | Create uninstaller entry in Installed Apps | `uninstallentry` | **Enabled** | Registers BitChat in Windows Settings → Apps → Installed apps |

6. **Screen 6 — Installation Progress:** Extracts runtime files, updates shortcuts/environment, and safely rolls back incomplete installations if cancelled or interrupted.
7. **Screen 7 — Completion:** Summarizes the installed version, installation location, `PATH` status, Windows startup state, user data preservation status, and provides the **Launch BitChat** checkbox and **Finish** button.

### WinGet Installation

```powershell
# Once upstream PR (microsoft/winget-pkgs#443445) is merged:
winget install Java-Mx.BitChat

# Or install directly using the local manifest in this repository:
winget install --manifest manifests/j/Java-Mx/BitChat/0.2.0/
```

### Unattended / Silent CLI Installation

```powershell
# Silent install to default user directory (%LOCALAPPDATA%\Programs\BitChat):
.\BitChat-0.2.0-windows-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

# Silent install to a custom directory with Windows sign-in startup enabled:
.\BitChat-0.2.0-windows-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="D:\Apps\BitChat" /TASKS="desktopicon,startmenuicon,envPath,startupicon,uninstallentry,!launchapp"
```

---

## 5. PATH & Command-Line Integration

When **Add BitChat to the current user's PATH** (`envPath`) is enabled:

- Setup appends the installation directory (e.g. `%LOCALAPPDATA%\Programs\BitChat`) to `HKCU\Environment\Path` without overwriting existing entries or adding duplicates.
- System-wide `HKLM` `PATH` is never modified unless the installer is explicitly run in administrative mode (`/ALLUSERS`).
- Setup records the installer-managed path in `HKCU\Software\Java-Mx\BitChat` (`PathAddedByInstaller`) so upgrades to a new directory replace the old entry cleanly and uninstallation removes **only** the entry created by BitChat.

> **Important:** Existing PowerShell or Command Prompt windows keep their startup environment snapshot. Close and reopen your terminal after installation (or refresh `$env:Path`) to run `bitchat`:

```powershell
bitchat
bitchat --help
bitchat --version
bitchat --cli
bitchat --tui
bitchat --configure
```

---

## 6. Start BitChat When Windows Starts (Per-User Sign-In Startup)

- **User Sign-In vs. System Boot:** BitChat's startup integration uses a standard per-user Windows Startup shortcut (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\BitChat.lnk` invoking `bitchat.exe --startup-launch`). It launches **after you sign in to your Windows user account**—it never installs a hidden Windows system service or pre-login boot daemon, and never requires Administrator privileges.
- **Default State:** Disabled by default during fresh installations.
- **Duplicate Instance Protection:** `bitchat.exe --startup-launch` acquires a per-user Windows named mutex (`Local\BitChatAppRunningMutex`). If BitChat is already running in your user session, the startup invocation exits cleanly without opening a duplicate window.
- **Managing Startup at Any Time:**
  1. **From the Command Line:**
     ```powershell
     bitchat --startup status
     bitchat --startup enable
     bitchat --startup disable
     ```
  2. **From Installer Maintenance Mode:** Re-run `BitChat-0.2.0-windows-x64.exe` and check or uncheck **Start BitChat automatically when Windows starts**.
  3. **From Windows Settings:** Toggle or remove `BitChat.lnk` in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

---

## 7. Upgrades & Identity Preservation

When you run a newer BitChat installer over an existing installation:

- **Automatic Detection:** Setup detects the existing installed version and location via `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{B17CHA70-B1EC-4E87-99B7-4DA78D0B7001}_is1`.
- **Running Instance Handling:** If `bitchat.exe` is currently running from the installation folder, Setup closes it cleanly before updating files so no file-lock errors occur.
- **Preserved User Data (`%USERPROFILE%\.bitchat\`):**
  - `identity.json` (Ed25519 and X25519 private keys, peer ID, fingerprint) is **never** deleted or overwritten.
  - `config.json` (nickname, transport selection, theme settings, keybindings) is **never** deleted or overwritten.
- **Preserved Preferences:** Custom installation directory (`UsePreviousAppDir=yes`), shortcut tasks (`UsePreviousTasks=yes`), and existing Windows startup registration survive upgrades automatically.

---

## 8. Uninstallation & User Data Management

You can uninstall BitChat from **Windows Settings → Apps → Installed apps**, the Start Menu **Uninstall BitChat** shortcut, `winget uninstall Java-Mx.BitChat`, or by running `{app}\unins000.exe`.

The uninstaller removes:
- Application binaries (`{app}\bitchat.exe`, `{app}\_internal\`, `{app}\assets\`, legal docs).
- Desktop and Start Menu shortcuts created by BitChat.
- The per-user Windows Startup shortcut (`%APPDATA%\...\Startup\BitChat.lnk`) if enabled.
- The user `PATH` entry if it was added by the BitChat installer.
- The `HKCU\Software\Java-Mx\BitChat` and Windows Uninstall registry keys.

### Preserving vs. Deleting User Data (`%USERPROFILE%\.bitchat\`)

- **Default Behavior (Preserved):** Both interactive and silent uninstallations preserve `%USERPROFILE%\.bitchat\` by default so you do not accidentally lose your cryptographic identity (`identity.json`) or configuration (`config.json`).
- **Interactive Option to Delete User Data:** During interactive uninstallation, Setup displays a clear warning explaining that deleting `%USERPROFILE%\.bitchat\` permanently destroys your cryptographic private keys (`identity.json`) and cannot be undone, with **No (Keep data)** selected as the default button.
- **Explicit CLI Option to Delete User Data:** For automated cleanup or scripts, pass `/REMOVEUSERDATA`:
  ```powershell
  & "$env:LOCALAPPDATA\Programs\BitChat\unins000.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /REMOVEUSERDATA
  ```

---

## 9. Legal Documents (Terms of Use & Privacy Policy)

- **[`TERMS_OF_USE.md`](../../TERMS_OF_USE.md)** — Draft Terms of Use prepared for BitChat Windows Installer 2.0 (clearly marked as a draft requiring publisher/legal review prior to formal public legal reliance).
- **[`PRIVACY_POLICY.md`](../../PRIVACY_POLICY.md)** — Draft Privacy Policy prepared following a code audit of `src/bitchat/`, documenting that BitChat collects no telemetry, analytics, or account data and stores private keys locally in `%USERPROFILE%\.bitchat\identity.json`.

---

## 10. BLE & WinRT Architecture on Windows

### BLE Considerations
- Requires Windows 10 (version 1809+) or Windows 11.
- Requires Bluetooth 4.0+ BLE-capable adapter with WinRT support.
- Backed by the `bleak` library using Windows WinRT Bluetooth APIs.
- The `bitchat.ble` transport pipeline (scanning, connection state machine, GATT discovery, 20ms pacing, queueing, and reassembly) has been verified using simulated Bleak adapters. Physical hardware validation is pending Phase 8.

### Platform Selection and BLE Roles
- Windows is selected centrally by `bitchat.platform.detection.detect_platform()` (`sys.platform == "win32"`); no Linux-only module or command is imported or run.
- WinRT (installed automatically by `bleak` through environment markers) provides adapter discovery, radio state events, the GATT server, and advertising. `BLEAdapterManager` reports the adapter and its roles from WinRT at runtime; a missing `winrt` backend is reported as an unavailable adapter, not as working hardware.
- Advertising can be aborted by the OS (GATT status 3) even with the radio on. BitChat then keeps BLE central scanning, records the failure, and offers **Retry Adapter**, **Continue Wi-Fi/LAN**, or **Continue Offline**. Each retry releases the failed provider, publisher, and event handlers before starting again.
- Windows behaviour is covered by tests against an in-memory fake of the WinRT API (`tests/ble/fake_winrt.py`); it has not been validated on physical Windows hardware in this change.

---

## 11. Troubleshooting

1. **Windows SmartScreen Warning ("Windows protected your PC"):**
   - Because community builds are compiled without a commercial EV/OV certificate (`Status: NotSigned`), Windows Defender SmartScreen displays an unknown publisher prompt.
   - Verify the SHA-256 hash using `Get-FileHash .\BitChat-0.2.0-windows-x64.exe -Algorithm SHA256` against `BitChat-0.2.0-windows-x64.exe.sha256`. If it matches, click **More info → Run anyway**. Never disable SmartScreen or Microsoft Defender system-wide.
2. **`bitchat` is not recognized in PowerShell:**
   - Close and reopen your terminal window so the updated user `PATH` is loaded, or refresh it in your current session:
     ```powershell
     $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User") + ";" + [System.Environment]::GetEnvironmentVariable("Path","Machine")
     ```
3. **Installation fails with permission error:**
   - Ensure you selected a user-writable directory such as `%LOCALAPPDATA%\Programs\BitChat`, or run the installer as Administrator if installing to `C:\Program Files\BitChat`.
   - Generate a diagnostic setup log with:
     ```powershell
     .\BitChat-0.2.0-windows-x64.exe /LOG="bitchat-install.log"
     ```
