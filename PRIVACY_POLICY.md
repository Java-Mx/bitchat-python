# BitChat Privacy Policy

> [!IMPORTANT]
> **DRAFT — PENDING PUBLISHER AND LEGAL REVIEW BEFORE PUBLIC RELEASE**
> This document is a draft prepared for the BitChat Windows Installer 2.0 distribution based on a technical audit of the `bitchat-python` codebase. It must be reviewed and approved by the publisher (`Java-Mx`) and legal counsel prior to formal public release.

**Application:** BitChat (`Java-Mx.BitChat`)
**Publisher:** Java-Mx
**Official Repository:** https://github.com/Java-Mx/bitchat-python
**Effective Date:** October 2026

---

## 1. Summary: Zero Telemetry, No Accounts, No Central Servers

BitChat is designed from the ground up as a local-first, peer-to-peer terminal messaging application:

- **No Personal Data Collection:** BitChat does **not** collect your name, email address, phone number, IP address, location, or any other personal information.
- **No Analytics or Telemetry:** BitChat contains **no** analytics SDKs, crash reporters, usage tracking, or telemetry transmission code. The application makes zero outbound connections to publisher or third-party servers.
- **No Accounts or Registration:** Downloading, installing, and using BitChat requires no account creation, sign-up, or subscription.
- **No Marketing or Tracking Consent:** Acknowledging this Privacy Policy during download or installation is purely informational and is **never** treated as consent to analytics, tracking, or marketing communications.

*(Technical note for source-code auditors: internal methods named `get_telemetry()` in `src/bitchat/` return strictly local, in-memory hardware and transport state dictionaries used exclusively to display adapter diagnostics in your own local terminal UI and `/status` command. None of this information ever leaves your device).*

---

## 2. Information Stored Locally on Your Device

BitChat stores its local configuration and cryptographic keys in your user profile directory at `%USERPROFILE%\.bitchat\` (or `~/.bitchat/` on Linux and macOS):

1. **Cryptographic Identity (`identity.json`):**
   - Stores your locally generated Ed25519 signing private key, X25519 key-agreement private key, public key fingerprint, and 8-byte peer ID.
   - On Windows, BitChat restricts access to `identity.json` using a protected Windows Discretionary Access Control List (DACL) granting permissions solely to your current Windows user account (`_restrict_windows_file_acl`).
   - Your private keys never leave your device.
2. **Application Configuration (`config.json`):**
   - Stores non-sensitive local preferences: your chosen display nickname (default: `"Anonymous"`), active transport (`"bluetooth"` or `"lan"`), UI theme density and accent color, maximum mesh hop count, fragment pacing delay, and custom keyboard shortcuts.
3. **Installer Settings (Windows Registry & Shortcuts):**
   - When installed via the Windows installer in user scope (default), standard installation metadata is recorded under `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall` and `HKCU\Software\Java-Mx\BitChat` (recording whether the installer added BitChat to your user `PATH`).
   - If you explicitly opt in to "Start BitChat automatically when Windows starts", a per-user shortcut (`BitChat.lnk`) is placed in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

### Retention and Deletion During Upgrades and Uninstallation

- **Upgrades:** Running a newer BitChat installer preserves your `%USERPROFILE%\.bitchat\` directory so your cryptographic identity and configuration are never lost.
- **Uninstallation:** By default, uninstalling BitChat removes the application binaries, shortcuts, startup registration, and installer `PATH` entry while **preserving** `%USERPROFILE%\.bitchat\`. The interactive uninstaller provides an explicit, separate option (and `/REMOVEUSERDATA` flag for CLI uninstallation) if you wish to permanently delete your local user data and cryptographic identity keys.

---

## 3. Information Shared Over Peer-to-Peer Transports

Because BitChat is a peer-to-peer communication tool, running the application with an active transport transmits protocol packets directly to other BitChat nodes within radio range or on your local network:

1. **Bluetooth Low Energy (BLE) Transport:**
   - BitChat scans for and advertises the BitChat GATT service UUID (`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`).
   - Nearby BLE peers can observe your node's BLE advertisement, configured nickname, peer ID, and public cryptographic keys (`Ed25519` / `X25519`).
2. **Local Area Network (LAN / Wi-Fi) Transport:**
   - BitChat broadcasts UDP discovery beacons on port `24024` / `41234` and accepts framed TCP connections on port `24025` / `41235` on your local subnet.
   - Peers on the same local network can observe your local IP address, port, peer ID, configured nickname, and public cryptographic keys.
3. **Messages and Mesh Routing:**
   - Public broadcast messages (`#public`) are shared with reachable nodes in the local mesh (forwarded up to the configured TTL hop limit).
   - Direct messages (`/dm`) are end-to-end encrypted using the Noise XX protocol (`Noise_XX_25519_ChaChaPoly_SHA256`) or AES-256-GCM; intermediate mesh relay nodes can observe packet routing headers (sender/recipient peer IDs, packet type, hop count) but cannot decrypt the message payload.
4. **Ephemeral Identity Switching:**
   - Switching transports at runtime (`/transport lan` or `/transport bluetooth`) generates a fresh ephemeral cryptographic identity and terminates active sessions so prior transport sessions are not linkable to the new session identity.

---

## 4. Software Downloads and Third-Party Hosting

BitChat installers and source code are distributed via **GitHub Releases** (`https://github.com/Java-Mx/bitchat-python/releases`) and the **Windows Package Manager (WinGet)** community repository.

- The BitChat project does not require any personal information, email address, or tracking cookies to download the installer.
- When you download release assets from GitHub, GitHub Inc. processes standard web request metadata (such as IP address and user-agent) in accordance with the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

---

## 5. Future Changes to This Policy

If optional diagnostics, crash reporting, or network services are ever proposed in a future release of BitChat, they will never be enabled silently; separate, informed opt-in consent will be required. Any updates to this Privacy Policy will be published in the repository at `PRIVACY_POLICY.md` and included in subsequent installer releases.

---

## 6. Contact and Questions

For questions regarding privacy or security in BitChat:
- **Complete Privacy Policy:** https://github.com/Java-Mx/bitchat-python/blob/main/PRIVACY_POLICY.md
- **Terms of Use:** https://github.com/Java-Mx/bitchat-python/blob/main/TERMS_OF_USE.md
- **Security Policy:** https://github.com/Java-Mx/bitchat-python/blob/main/SECURITY.md
- **GitHub Issues:** https://github.com/Java-Mx/bitchat-python/issues
