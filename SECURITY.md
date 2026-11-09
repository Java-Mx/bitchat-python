# Security Policy

BitChat is an open-source, peer-to-peer encrypted terminal messenger operating over Bluetooth Low Energy (BLE) and Local Area Network (LAN) transports. This document defines how to report security vulnerabilities privately, which versions receive security updates, and the exact boundaries between implemented protections, tested properties, known limitations, and future security work.

---

## 1. Supported Versions

Security fixes are applied to the latest release on the `main` branch. Earlier pre-release and `0.1.x` / `0.2.x` / `0.3.0` builds are not maintained with backported patches.

| Version | Supported | Status |
| :--- | :--- | :--- |
| **`0.3.1` (`main`)** | ✅ Yes | Current release (Hybrid Python + Rust `bitchat._bitchat_core`) |
| `< 0.3.1` | ❌ No | Upgrade to `0.3.1` |

---

## 2. Reporting a Vulnerability Privately

**Do NOT report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Please report suspected vulnerabilities privately using **GitHub Security Advisories**:

- **Private Reporting URL:** [https://github.com/Java-Mx/bitchat-python/security/advisories/new](https://github.com/Java-Mx/bitchat-python/security/advisories/new)

### 2.1 What to Include in Your Report

To help maintainers reproduce and evaluate the issue quickly, please include:

1. **Affected Component:** Python module path (e.g., `src/bitchat/crypto/noise.py`), Rust crate module (e.g., `rust/bitchat-core/src/lib.rs`), or packaging script.
2. **Version & Environment:** BitChat version (`bitchat --version`), operating system, Python version, and whether the native Rust core (`bitchat._bitchat_core`) was active.
3. **Vulnerability Type & Impact:** What an attacker can achieve (e.g., handshake authentication bypass, nonce reuse, remote crash / denial of service via malformed frame, local privilege escalation in uninstaller/installer, or key exposure).
4. **Reproduction Steps or Proof-of-Concept:** Minimal packet bytes, test case, or command sequence that demonstrates the flaw.
5. **Suggested Mitigation (Optional):** Any proposed fix or design hardening.

### 2.2 Response & Coordinated Disclosure Process

BitChat is maintained as an open-source project on a best-effort basis without commercial SLA guarantees:

1. **Receipt & Triage:** Maintainers review incoming GitHub Security Advisories as capacity permits and will respond within the advisory thread to confirm receipt and initial severity assessment.
2. **Remediation:** Confirmed vulnerabilities are fixed privately in a temporary security advisory branch with regression tests covering both Python and Rust code paths where applicable.
3. **Coordinated Disclosure:** Once a patched release is published (or a mutually agreed disclosure window is reached), the advisory is published along with release notes crediting the reporter (unless anonymity is requested).

We ask researchers to act in good faith, avoid disrupting other users' devices or networks, and give maintainers a reasonable opportunity to remediate issues before public disclosure.

---

## 3. Audit Status

> **Important Notice:** BitChat `v0.3.1` has **not** undergone an independent third-party cryptographic or security audit. While the codebase uses standard cryptographic primitives and automated test suites, it should not be relied upon for life-safety, critical infrastructure, or high-threat adversarial operations.

---

## 4. Scope

### 4.1 In Scope

- **Cryptographic Implementation (`src/bitchat/crypto/`):** `Noise_XX_25519_ChaChaPoly_SHA256` handshake state machine, session cipher state (`ChaCha20-Poly1305` with 1024-entry replay window), channel/symmetric `AES-256-GCM`, `X25519` key agreement, `Ed25519` signature verification, `HKDF-SHA256`, `PBKDF2-HMAC-SHA256`, and peer ID / public key binding checks.
- **Rust Native Extension (`rust/bitchat-core/`):** Binary packet header encoding/decoding (`encode_packet_raw`, `decode_packet_raw`), block padding (`pad_packet_data`, `unpad_packet_data`), fragmentation, bounded fragment reassembly (`NativeFragmentReassembler`), TCP stream framing (`NativeStreamFramer`), deduplication (`NativePacketDeduplicator`), and per-peer rate limiting (`NativePeerRateLimiter`) across the PyO3 FFI boundary.
- **Python Protocol & Mesh Fallback (`src/bitchat/protocol/`, `src/bitchat/mesh/`):** Any discrepancy, parser crash, or memory exhaustion vulnerability in packet decoding, fragmentation, reassembly, or multi-hop routing.
- **BLE & LAN Transports (`src/bitchat/ble/`, `src/bitchat/network/`):** Length-prefixed TCP stream framing (`BC\x01\x00` + 4-byte length, `MAX_FRAME_SIZE = 65536`), UDP discovery beacon parsing (`MAX_DISCOVERY_PACKET_SIZE = 1024`), rate limiting, and connection bounds (`MAX_CONCURRENT_CONNECTIONS = 32`).
- **Local Storage, Logging & Uninstaller (`src/bitchat/storage/`, `src/bitchat/logging/`, `src/bitchat/platform/uninstaller.py`):** File permissions (`0600` on POSIX, current-user DACL on Windows), atomic writes, log secret redaction (`SensitiveDataFilter`), and safe `PATH`/file removal logic.
- **Packaging & Release Workflows (`packaging/`, `.github/workflows/`):** Supply-chain integrity, installer privilege boundaries, and build script safety.

### 4.2 Out of Scope

- Physical or local access attacks against an already unlocked OS user session or root/Administrator account.
- Standard radio-frequency jamming or OS-level Bluetooth / Wi-Fi driver crashes outside BitChat's process control.
- Traffic analysis of outer BLE advertisements, LAN UDP broadcasts, or unencrypted outer packet routing headers (documented below as known protocol characteristics).
- Social engineering or user failure to verify peer fingerprints out-of-band when operating in `normal` (TOFU) security mode.
- Vulnerabilities in archived or non-runtime reference directories (such as `nim/`, which is retained solely as a historical FFI prototype and is not shipped or executed by BitChat).

---

## 5. Security Architecture Matrix

To help users and auditors evaluate BitChat accurately, the table below distinguishes what is implemented and tested today from known limitations, unverified assumptions, and planned future work:

### 5.1 Implemented Protections (`v0.3.1`)

- **Mutual Authenticated Key Agreement:** Direct peer sessions use the `Noise_XX_25519_ChaChaPoly_SHA256` handshake pattern (`src/bitchat/crypto/noise.py`), providing mutual static key authentication and forward secrecy via ephemeral X25519 keys.
- **Authenticated Encryption & Replay Window:** Established Noise sessions encrypt payloads with `ChaCha20-Poly1305` using 4-byte little-endian counter prefixes and enforce a 1,024-entry sliding replay window. Channel/legacy symmetric encryption uses `AES-256-GCM` with 96-bit OS CSPRNG nonces.
- **Strict Post-Handshake Peer ID Binding:** After the Noise handshake completes, BitChat verifies that the remote peer's advertised 8-byte `peer_id` matches `SHA-256(remote_x25519_public)[:8]`, rejecting peers whose static key does not match their routing ID.
- **Trust-On-First-Use (TOFU) & Maximum Security Mode:** In `normal` mode, peer fingerprints are pinned on first contact in `~/.bitchat/config.json` (`contacts`) and subsequent mismatches are rejected. In `maximum` security mode (`security_mode = "maximum"`), unverified peers are blocked until explicitly trusted (`/trust` / `/verify`).
- **Bounded Buffers & Resource Caps:**
  - Maximum wire payload: `65,535` bytes; maximum application chat message size: `32,768` bytes (`MAX_MESSAGE_SIZE`).
  - Maximum fragments per assembly: `1,000` (`MAX_FRAGMENTS_PER_ASSEMBLY`); maximum active reassembly buffers: `100` (`MAX_ACTIVE_ASSEMBLIES`); maximum reassembled bytes: `150,000` (`MAX_REASSEMBLED_BYTES`); reassembly timeout: `30.0` seconds.
  - Store-and-forward queue bounded to `100` packets total, `20` packets per peer, `256 KB` total memory, and `300.0` seconds TTL.
  - Mesh peer rate limiter bounded to `50` packets/sec per peer (`NativePeerRateLimiter`), and deduplicator bounded to `1,000` entries with `300.0` seconds TTL (`NativePacketDeduplicator`).
  - LAN server bounded to `32` concurrent TCP connections (`MAX_CONCURRENT_CONNECTIONS`), `65,536`-byte maximum TCP frame length, and `10` UDP discovery packets/sec per IP (`MAX_DISCOVERY_RATE_PER_IP`).
- **Restricted Identity File Permissions:** `~/.bitchat/identity.json` is written atomically with `0600` permissions on POSIX and a protected current-user-only DACL (`SetNamedSecurityInfoW`) on Windows, guarded by an advisory file lock (`identity.json.lock`).
- **Diagnostic Log Redaction:** `SensitiveDataFilter` automatically redacts 64-character hex strings, bearer tokens, and secret key-value pairs before writing to `bitchat.log`.

### 5.2 Automated Security & Correctness Tests

- Cryptographic unit tests covering `X25519`, `Ed25519`, `ChaCha20-Poly1305`, `AES-256-GCM`, `HKDF-SHA256`, `PBKDF2`, `LocalIdentity`, and full 3-message `Noise_XX` handshakes (including tampered ciphertext, wrong static keys, and out-of-order/replayed nonces).
- Adversarial boundary tests (`tests/e2e/`, `tests/protocol/test_defensive_bounds.py`, `tests/stress/`) and differential equivalence tests (`tests/unit/test_native_core.py`) verifying identical behavior between the Rust `bitchat._bitchat_core` extension and the Python reference implementation across valid, truncated, and malformed inputs.
- Automated CI security gates (`.github/workflows/security.yml`) running `pip-audit` against locked dependencies and `bandit` static analysis on `src/bitchat`.

### 5.3 Known Security Limitations

1. **Unencrypted Outer Routing Headers:** The outer BitChat binary packet header (`version`, `message_type`, `ttl`, `timestamp`, `flags`, `payload_len`, `sender_id`, and optional `recipient_id`) is transmitted in plaintext so intermediate nodes can route, deduplicate, and reassemble packets (though PKCS#7-style block padding to `256`/`512`/`1024`/`2048` bytes obscures exact payload lengths). Passive observers in radio range or on the same LAN can observe sender/recipient IDs and timing.
2. **Public Broadcast Messages (`0x04 Message`):** Messages sent to the public broadcast channel (`recipient_id = ffffffffffffffff`) are not encrypted for a specific peer and can be read by any connected peer within hop range.
3. **Unencrypted Private Keys at Rest:** `~/.bitchat/identity.json` stores `x25519_private` and `ed25519_private` as hexadecimal strings protected by OS file permissions (`0600` / Windows user DACL), not encrypted with a user passphrase or hardware security module (TPM / OS keychain).
4. **Python Memory Zeroization Limits:** In `v0.3.1`, cryptographic keys and plaintext strings pass through Python `bytes` and `str` objects managed by the CPython allocator and garbage collector, which cannot be deterministically zeroized in RAM before collection.
5. **TOFU First-Contact Exposure:** In `normal` security mode, the very first connection to a previously unknown peer trusts the presented public key unless an active attacker is detected via out-of-band fingerprint comparison (`/fingerprint`, `/verify`).
6. **Unsigned Windows Binaries When Built Without Signing Secrets:** Official release builds only attach an Authenticode signature if code-signing secrets (`WINDOWS_SIGNING_CERT`) are configured in the build environment; otherwise, Windows SmartScreen will display an unknown-publisher warning and users should verify the `.sha256` checksum.

### 5.4 Unverified Assumptions

- Correctness and side-channel resistance of the underlying operating system CSPRNG (`os.urandom`) and the upstream Python `cryptography` (OpenSSL) library.
- Isolation provided by the host OS Bluetooth stack (Windows WinRT, Linux BlueZ / D-Bus) and TCP/IP stack.
- Absence of an independent formal verification or third-party penetration test of the custom binary framing and session coordinator state machine.

### 5.5 Planned Future Security Work

As part of the multi-stage Rust migration roadmap (see [`docs/ROADMAP.md`](docs/ROADMAP.md)):

- **Stage 2 (Planned):** Migrate `X25519`, `Ed25519`, `AES-256-GCM`, `HKDF-SHA256`, and the `Noise_XX` state machine into Rust (`rust/bitchat-core`) with explicit `zeroize::ZeroizeOnDrop` for private keys and session cipher states.
- **Future Hardening (Planned):** Optional passphrase-derived encryption at rest (`Argon2id` / `PBKDF2`) or OS keychain integration for `identity.json`.

---

## 6. Related Security Documentation

- [`docs/security/CRYPTOGRAPHY.md`](docs/security/CRYPTOGRAPHY.md) — Cryptographic primitives, parameters, and key derivation.
- [`docs/security/NOISE.md`](docs/security/NOISE.md) — `Noise_XX_25519_AESGCM_SHA256` handshake flow and wire payload structure.
- [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md) — Adversary capabilities, trust boundaries, and mitigations.
- [`docs/security/DATA_HANDLING.md`](docs/security/DATA_HANDLING.md) — Technical inventory of local files, network beacons, and in-memory retention.
