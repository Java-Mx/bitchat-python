# Cryptographic Architecture

This document specifies the cryptographic architecture of the BitChat protocol as implemented in the Rust reference implementation (`bitchat-tui`).

---

## 1. Overview of Cryptographic Primitives

The BitChat protocol utilizes modern, high-assurance cryptographic primitives:

- **Signatures & Identity:** Ed25519 (Edwards-curve Digital Signature Algorithm over Curve25519)
- **Key Agreement:** X25519 (Elliptic Curve Diffie-Hellman over Curve25519)
- **Symmetric Encryption (Legacy):** AES-256-GCM with 96-bit random nonces
- **Symmetric Encryption (Noise Protocol):** ChaCha20-Poly1305 with 32-bit little-endian sequential nonces padded to 96 bits
- **Key Derivation (Shared Secrets):** HKDF-SHA256 with protocol-specific salts
- **Key Derivation (Channel Passwords):** PBKDF2-HMAC-SHA256 (100,000 iterations)
- **Cryptographic Hashing & Fingerprinting:** SHA-256

---

## 2. Cryptographic Operations: Data Flow Specifications

Every cryptographic operation in BitChat follows a deterministic transformation pipeline:

### 2.1 Identity Fingerprint Generation
Generates a human-verifiable 32-character hexadecimal fingerprint for a peer:
```text
X25519 Static Public Key (32 bytes)
  ↓ SHA-256 Hashing
Digest (32 bytes)
  ↓ Take First 16 Bytes & Hexadecimal Encoding
Hex Fingerprint String (32 lowercase hex characters)
```

### 2.2 Ephemeral Message Signing (Ed25519)
Signs an outgoing message payload before packet transmission:
```text
Unencrypted Message Payload Bytes + Ephemeral Ed25519 SigningKey (32 bytes)
  ↓ Ed25519 Digital Signature Generation
Signature (64 bytes)
```
- **Packet Placement:** Placed immediately following the payload if `FLAG_HAS_SIGNATURE` (`0x02`) is set.

### 2.3 Ephemeral Signature Verification (Ed25519)
Verifies message integrity and authenticity upon receipt:
```text
Message Payload Bytes + Signature (64 bytes) + Ephemeral Ed25519 VerifyingKey (32 bytes)
  ↓ Ed25519 Signature Verification
Boolean (Valid / Invalid)
```

### 2.4 Legacy Key Exchange (X25519 Diffie-Hellman)
Derives a shared symmetric key between two peers using their ephemeral X25519 keys:
```text
Local X25519 Ephemeral Private Secret (32 bytes) + Remote X25519 Ephemeral Public Key (32 bytes)
  ↓ X25519 Elliptic Curve Diffie-Hellman (ECDH)
Shared Secret (32 bytes)
  ↓ HKDF-SHA256 (Salt = b"bitchat-v1", Info = empty)
Symmetric Key (32 bytes, for AES-256-GCM)
```

### 2.5 Legacy Message Encryption (AES-256-GCM)
Encrypts a message payload using the derived legacy symmetric key:
```text
Plaintext Payload Bytes + AES Key (32 bytes) + Random Nonce (12 bytes from OsRng)
  ↓ AES-256-GCM Authenticated Encryption
12-byte Nonce + Ciphertext Bytes + 16-byte Poly1305/GCM Tag
```
- **Payload Format:** `[12-byte Nonce (bytes 0..12)][Ciphertext + 16-byte Tag (bytes 12..end)]`

### 2.6 Legacy Message Decryption (AES-256-GCM)
Decrypts an inbound legacy encrypted message payload:
```text
Encrypted Payload (Nonce + Ciphertext + Tag) + AES Key (32 bytes)
  ↓ Extract Nonce (first 12 bytes) & Ciphertext+Tag (remaining bytes)
  ↓ AES-256-GCM Authenticated Decryption
Plaintext Payload Bytes (or Decryption Failure Error)
```

### 2.7 Channel Password Key Derivation (PBKDF2)
Derives a 256-bit symmetric encryption key from a user-supplied channel password:
```text
Channel Password String (UTF-8 bytes) + Channel Name String (UTF-8 bytes as Salt)
  ↓ PBKDF2-HMAC-SHA256 (100,000 iterations, 32-byte output)
Channel Symmetric Key (32 bytes, for AES-256-GCM)
```

### 2.8 Local Stored State Password Encryption
Encrypts saved channel passwords inside `~/.bitchat/state.json`:
```text
Raw Channel Password String (UTF-8 bytes) + Identity Key Bytes (32 bytes)
  ↓ Derive Key: SHA-256(b"bitchat-password-encryption" || IdentityKeyBytes)
AES Key (32 bytes) + Random Nonce (12 bytes)
  ↓ AES-256-GCM Authenticated Encryption
JSON Object: { "nonce": [u8; 12], "ciphertext": [u8; N] }
```

### 2.9 Noise Handshake Key Exchange (Noise XX Pattern)
During the Noise XX handshake, ephemeral and static Diffie-Hellman operations are mixed into a chaining key:
```text
Chaining Key (32 bytes) + DH Shared Secret (32 bytes from X25519)
  ↓ HKDF-SHA256 (Extract & Expand)
New Chaining Key (32 bytes) + Handshake Cipher Key (32 bytes)
```

### 2.10 Noise Transport Packet Encryption (ChaCha20-Poly1305)
Encrypts transport data once a Noise session has reached the `Established` state:
```text
Plaintext Message (with 0x04 prefix) + Send Cipher Key (32 bytes) + 64-bit Nonce Counter
  ↓ Little-Endian u32 Nonce Encoding (placed in bytes 4..7 of 12-byte nonce, rest zeros)
  ↓ ChaCha20-Poly1305 Authenticated Encryption
4-byte Little-Endian Nonce + Ciphertext + 16-byte Poly1305 MAC Tag
```

---

## 3. Key Formats and Storage

### 3.1 Persistent Identity Key (Ed25519)
- **Generation:** 32 bytes of secure random entropy (`OsRng`).
- **Storage:** Persisted in `~/.bitchat/state.json` as a 32-byte JSON byte array under the key `"identity_key"`.
- **Purpose:** Represents the long-term cryptographic identity of the peer across sessions.

### 3.2 Persistent Noise Static Key (X25519)
- **Generation:** 32 bytes of secure random entropy (`OsRng`).
- **Storage:** Persisted in `~/.bitchat/state.json` as a 32-byte JSON byte array under the key `"noise_static_key"`.
- **Purpose:** Represents the peer's static Curve25519 key used for mutual authentication in the Noise XX handshake.

### 3.3 Ephemeral Keys
- **Ephemeral X25519 Key Pair:** Generated anew each time a session starts.
- **Ephemeral Ed25519 Signing Key Pair:** Generated anew each time a session starts.

### 3.4 Combined 96-Byte Public Key Format (`KeyExchange`)
When broadcasting or responding to key exchanges (`MessageType::KeyExchange`), the payload is structured as follows:

| Byte Range | Length | Key Type | Purpose |
|---|---|---|---|
| `0..32` | 32 B | X25519 Public Key | Ephemeral key for Diffie-Hellman key agreement |
| `32..64` | 32 B | Ed25519 Verifying Key | Ephemeral key for per-message signature verification |
| `64..96` | 32 B | Ed25519 Verifying Key | Persistent long-term identity verifying key |

### 3.5 Android Compatibility Workaround
In the reference implementation (`encryption.rs`), if the 32-byte persistent identity key (bytes 64–96) cannot be parsed as a valid Ed25519 point (a known bug in early Android BitChat clients), the parser automatically falls back to treating the ephemeral signing key (bytes 32–64) as the identity key.

---

## 4. Python Implementation Status (`bitchat.crypto`)

All cryptographic primitives are fully implemented in pure Python using only `cryptography`:

| Primitive | Python Module | Reference Equivalent | Status |
|---|---|---|---|
| **Identity & Fingerprints** | `bitchat.crypto.identity` | `NoiseSessionManager::calculate_fingerprint` | ✅ Implemented |
| **Ed25519 Signatures** | `bitchat.crypto.ed25519` | `SigningKey` / `VerifyingKey` (`encryption.rs`) | ✅ Implemented |
| **X25519 ECDH** | `bitchat.crypto.x25519` | `StaticSecret` / `PublicKey` (`encryption.rs`) | ✅ Implemented |
| **AES-256-GCM** | `bitchat.crypto.aes_gcm` | `encrypt_legacy` / `decrypt_legacy` (`encryption.rs`) | ✅ Implemented |
| **Noise HKDF** | `bitchat.crypto.hkdf` | `NoiseSymmetricState::hkdf` (`noise_protocol.rs`) | ✅ Implemented |
| **Legacy HKDF** | `bitchat.crypto.hkdf` | `Hkdf::<Sha256>::new(b"bitchat-v1", ...)` | ✅ Implemented |
| **PBKDF2** | `bitchat.crypto.pbkdf2` | `EncryptionService::derive_channel_key` | ✅ Implemented |
| **Noise Protocol** | `bitchat.crypto.noise` | `NoiseHandshakeState` (`noise_protocol.rs`) | ✅ Implemented |
| **Session Lifecycle** | `bitchat.crypto.sessions` | `NoiseSession` (`noise_session.rs`) | ✅ Implemented |
| **Role Tie-Breaking** | `determine_handshake_role` | `notification_handlers.rs` line 1771 | ✅ Implemented |

