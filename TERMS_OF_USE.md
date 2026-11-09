# BitChat Terms of Use & Operational Notice

> **DRAFT — LEGAL REVIEW REQUIRED:** This document is a draft operational notice and terms disclosure for the open-source BitChat project (`v0.3.1`). It supplements — and does not restrict, replace, or override — the permissions granted under the [MIT License](LICENSE). Before distributing BitChat in a commercial, enterprise, or regulated environment, this notice should be reviewed by the project publisher or qualified legal counsel.

**Effective Date:** November 9, 2026  
**Applicable Release:** BitChat `v0.3.1`  
**Repository:** [https://github.com/Java-Mx/bitchat-python](https://github.com/Java-Mx/bitchat-python)

---

## 1. Relationship to the MIT License

BitChat is free and open-source software licensed under the [MIT License](LICENSE).

- Nothing in this document restricts or diminishes your rights under the MIT License to use, copy, modify, merge, publish, distribute, sublicense, or sell copies of the software.
- In the event of any conflict between this document and the [MIT License](LICENSE) regarding copyright permissions or software redistribution, the [MIT License](LICENSE) governs.
- Displaying this document in the repository or inside an installer acknowledgment step provides transparent operational and security disclosures; whether an installer checkbox or use of the software forms a binding contract beyond the MIT License depends on applicable local law.

---

## 2. Permitted Use & Attribution

Subject to the conditions of the [MIT License](LICENSE):

1. You may install, run, inspect, modify, and redistribute BitChat in source or binary form for personal, academic, research, or commercial purposes.
2. All copies or substantial portions of the software must retain the copyright notice and permission notice specified in [`LICENSE`](LICENSE).
3. You may not use the names of the project authors, maintainers, or contributors to endorse or promote derived products without prior written permission.

---

## 3. User Responsibilities & Lawful Operation

Because BitChat operates directly between user-controlled devices without central moderation or intermediary servers, **you are solely responsible for how you configure and operate the software**:

- **Lawful Communications:** You are responsible for ensuring that all messages, payloads, and files you transmit or relay through BitChat comply with applicable local, national, and international laws.
- **Radio & Spectrum Compliance:** When enabling the Bluetooth Low Energy (BLE) transport, you are responsible for complying with local radio-frequency and wireless regulations (including restrictions in aircraft, healthcare facilities, or restricted industrial environments).
- **Network Authorization:** When enabling the Local Area Network (LAN) transport (UDP discovery default port `41234`, TCP transport default port `41235`), you are responsible for complying with the acceptable-use and firewall policies of the network to which your device is connected.
- **No Malicious Use:** You should not use BitChat to conduct denial-of-service floods, unauthorized network scanning, spoofing attacks, or distribution of unlawful or malicious payloads.

---

## 4. Peer-to-Peer & Multi-Hop Mesh Behavior

By running BitChat with an active transport (`Bluetooth LE` or `Local Network (LAN)`), you understand and acknowledge how the peer-to-peer protocol operates:

1. **Direct Broadcast & Discovery:** Your device broadcasts BLE advertisements (Service UUID `F47B5E2D-4A9E-4C5A-9B3F-8E1D2C3A4B5C`) or LAN UDP discovery beacons (default port `41234`, including your `peer_id`, `nickname`, listening port, and detected Wi-Fi `ssid`) so nearby peers can discover and connect to you.
2. **Multi-Hop Packet Relaying:** When `max_hops` / packet `ttl` is greater than `1` (default `3`, maximum `7`), your BitChat node participates in mesh routing and may automatically deduplicate, buffer in memory (`StoreAndForwardQueue`), and forward packets on behalf of other nearby peers.
3. **Untrusted Remote Peers:** Any device within BLE radio range or on the same LAN segment can attempt to connect to your node, read unencrypted outer packet headers, or receive public broadcast messages (`0x04 Message`). Once a message is transmitted to a remote peer, the sender has no technical ability to recall or delete it from the recipient's device.

---

## 5. Identity, Key Management & Local Data Security

- **Local Key Ownership:** BitChat generates and stores your persistent X25519 and Ed25519 private keys locally in `~/.bitchat/identity.json` (`%USERPROFILE%\.bitchat\identity.json` on Windows). There is no central key escrow, password reset, or account recovery mechanism.
- **Unencrypted At-Rest Storage:** While `identity.json` is restricted to your OS user account (`0600` on POSIX, current-user DACL on Windows), private keys are stored as hexadecimal strings on disk and are **not** encrypted with a user passphrase. Anyone with administrative/root access or access to your unlocked OS user session can read `identity.json`.
- **Fingerprint Verification (TOFU):** BitChat uses Trust-On-First-Use (TOFU) in `normal` security mode and requires out-of-band fingerprint verification (`/verify` / `/trust`) in `maximum` security mode to protect against active Man-in-the-Middle (MitM) impersonation on first contact.

---

## 6. Security Limitations & No Independent Audit

BitChat is an evolving open-source engineering project (`v0.3.1`):

- **No Formal Third-Party Audit:** While BitChat uses established cryptographic primitives (`Noise_XX_25519_ChaChaPoly_SHA256`, `X25519`, `Ed25519`, `ChaCha20-Poly1305`, `AES-256-GCM`, `HKDF-SHA256`, `PBKDF2-HMAC-SHA256`) and automated test suites, **the software has not undergone an independent third-party cryptographic or security audit**.
- **High-Risk Environments:** Do not rely on BitChat as your sole communication channel in life-safety, emergency-response, medical, or high-threat national-security situations where software defects, radio interference, metadata leakage, or undiscovered vulnerabilities could lead to physical harm or severe loss.
- Please review [`SECURITY.md`](SECURITY.md) and [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md) for a detailed breakdown of implemented protections, known limitations, and unverified assumptions.

---

## 7. Data Loss & Availability Disclaimers

- **Ephemeral Chat History:** Chat messages are held in volatile memory (RAM) during your active session and are not persisted to disk in `v0.3.1`. Exiting the application or running `/clear` permanently erases displayed chat history.
- **Best-Effort Delivery:** Wireless BLE links, LAN broadcasts, and multi-hop mesh relays are best-effort transports subject to radio range, packet loss, OS Bluetooth stack limitations, and firewall rules. BitChat does not guarantee message delivery, ordering, or latency.

---

## 8. Third-Party Open-Source Dependencies

BitChat incorporates open-source Python and Rust libraries (including `cryptography`, `bleak`, `textual`, `rich`, `pyo3`, and platform backends such as `winrt` on Windows and `dbus-fast` on Linux). Each dependency remains subject to its own upstream open-source license as declared in `pyproject.toml`, `Cargo.toml`, and `uv.lock`.

---

## 9. Disclaimer of Warranty & Limitation of Liability

Consistent with the [MIT License](LICENSE):

> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

---

## 10. Contact & Reporting

- **General Support & Bug Reports:** See [`SUPPORT.md`](SUPPORT.md) or open an issue at [https://github.com/Java-Mx/bitchat-python/issues](https://github.com/Java-Mx/bitchat-python/issues)
- **Security Vulnerabilities:** Do **not** file public issues for security vulnerabilities. Use [GitHub Security Advisories](https://github.com/Java-Mx/bitchat-python/security/advisories/new) as described in [`SECURITY.md`](SECURITY.md).
- **Code of Conduct:** Community participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
