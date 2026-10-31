# BitChat Terms of Use

> [!IMPORTANT]
> **DRAFT — PENDING PUBLISHER AND LEGAL REVIEW BEFORE PUBLIC RELEASE**
> This document is a draft prepared for the BitChat Windows Installer 2.0 distribution and must be reviewed and approved by the publisher (`Java-Mx`) and legal counsel prior to formal commercial or public legal reliance.

**Application:** BitChat (`Java-Mx.BitChat`)
**Publisher:** Java-Mx
**Official Repository:** https://github.com/Java-Mx/bitchat-python
**License:** MIT License ([`LICENSE`](LICENSE))
**Effective Date:** October 2026

---

## 1. Acceptance of Terms

By downloading, installing, or using the BitChat Windows installer (`BitChat-<version>-windows-x64.exe`) or the BitChat application ("the Software"), you acknowledge that you have read, understood, and agree to these Terms of Use. If you do not agree to these Terms of Use, do not install or use the Software.

---

## 2. Open-Source License Relationship

BitChat is free and open-source software distributed under the **MIT License** (see [`LICENSE`](LICENSE) in the repository root and in the installation directory).

Permission is granted, free of charge, to any person obtaining a copy of the Software and associated documentation files to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the conditions of the MIT License. Nothing in these Terms of Use restricts, limits, or supersedes the permissions granted to you under the MIT License.

---

## 3. Description of Software and Peer-to-Peer Operation

BitChat is a decentralized, peer-to-peer terminal messaging application operating over Bluetooth Low Energy (BLE) and Local Area Networks (LAN / Wi-Fi).

1. **No Central Infrastructure:** BitChat operates without central servers, user accounts, or cloud message relays.
2. **Local Radio and Subnet Discovery:** When running with Bluetooth or LAN transport enabled, BitChat discovers and communicates directly with nearby peers within Bluetooth radio range or on your local network subnet.
3. **User-Controlled Startup and Integration:** The Windows installer allows you to choose your installation directory, `PATH` environment integration, desktop/Start Menu shortcuts, and optional Windows sign-in startup. BitChat does not install hidden background services or system-level daemons.

---

## 4. Security Notice and High-Risk Use Disclaimer

> [!WARNING]
> **No Formal Third-Party Security Audit:** As documented in [`SECURITY.md`](SECURITY.md), `bitchat-python` is in active development and has **not** undergone a formal independent cryptographic or security audit.

1. While BitChat implements standard cryptographic primitives (including Noise XX handshakes with X25519 key agreement, Ed25519 digital signatures, ChaCha20-Poly1305, and AES-256-GCM), software defects or implementation flaws may exist.
2. **Do Not Use for High-Risk Communications:** You must not rely on BitChat for life-safety, emergency response, critical infrastructure, or high-risk communications where software failure or metadata/content exposure could lead to personal injury, legal liability, or severe harm.

---

## 5. User Responsibilities and Key Management

1. **Local Cryptographic Identity:** BitChat generates and stores your cryptographic private keys locally on your device (`%USERPROFILE%\.bitchat\identity.json` on Windows, protected by per-user file ACLs). There is no central key escrow or password recovery service. If you delete your identity keys, your cryptographic node identity cannot be recovered.
2. **Lawful Use:** You are solely responsible for the messages and data you transmit using BitChat and for complying with all applicable local, national, and international laws, including radio-frequency and local network regulations.
3. **Shared Network Environments:** When operating on a Local Area Network (LAN) or Bluetooth mesh, your configured nickname, peer identifier, and public keys are visible to other BitChat nodes on the same radio channel or local subnet.

---

## 6. Disclaimer of Warranties

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. THE PUBLISHER AND CONTRIBUTORS MAKE NO WARRANTY THAT THE SOFTWARE WILL BE ERROR-FREE, UNINTERRUPTED, OR FREE OF SECURITY VULNERABILITIES.

---

## 7. Limitation of Liability

IN NO EVENT SHALL THE AUTHORS, PUBLISHER (`Java-Mx`), OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE, INCLUDING WITHOUT LIMITATION ANY LOSS OF DATA, LOSS OF CRYPTOGRAPHIC KEYS, OR UNAUTHORIZED ACCESS TO TRANSMISSIONS.

---

## 8. Official Resources and Contact

- **Official Repository:** https://github.com/Java-Mx/bitchat-python
- **Complete Terms of Use:** https://github.com/Java-Mx/bitchat-python/blob/main/TERMS_OF_USE.md
- **Privacy Policy:** https://github.com/Java-Mx/bitchat-python/blob/main/PRIVACY_POLICY.md
- **Security Policy & Vulnerability Reporting:** https://github.com/Java-Mx/bitchat-python/blob/main/SECURITY.md
- **Issue Tracker:** https://github.com/Java-Mx/bitchat-python/issues
