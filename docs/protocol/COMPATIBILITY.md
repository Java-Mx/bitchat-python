# Rust ↔ Python Compatibility Checklist

This document provides a concrete compatibility verification checklist and test vector specification between the Rust reference implementation (`bitchat-tui`) and the future Python implementation.

---

## 1. Binary Packet Encoding Checklist

- [x] **Protocol Version:** Exactly byte `0x01` (`1`)
- [x] **Message Type:** Byte matches `MessageType` enum value (`0x01`–`0x25`)
- [x] **TTL (Time to Live):** 1 byte (`u8`), default 7, decremented on relay, dropped at 0
- [x] **Timestamp:** 8 bytes, Big-Endian `u64` representing milliseconds since Unix epoch
- [x] **Packet Flags:** 1 byte bitmask:
  - [x] `FLAG_HAS_RECIPIENT` (`0x01`)
  - [x] `FLAG_HAS_SIGNATURE` (`0x02`)
  - [x] `FLAG_IS_COMPRESSED` (`0x04`)
- [x] **Payload Length:** 2 bytes, Big-Endian `u16`
- [x] **Sender ID:** 8 raw bytes (`[u8; 8]`)
- [x] **Recipient ID:** 8 raw bytes (`[u8; 8]`), included if and only if `FLAG_HAS_RECIPIENT` (0x01) is set
- [x] **Broadcast Recipient ID:** Exactly `[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]`
- [x] **Payload Content:** `payload_length` bytes (LZ4 compression payload handler in Phase 4)
- [x] **Signature Placement:** Exactly 64 bytes immediately following payload, included if and only if `FLAG_HAS_SIGNATURE` (0x02) is set (wire placement implemented; signing semantics verified in Phase 4)
- [x] **Block Padding:** BitChat random block padding (PKCS#7-style length delimiter) to 256, 512, 1024, or 2048 bytes; final byte encodes padding count (1–255)

---

## Defensive Parsing & Reference Parity

| Property | Rust Reference (`bitchat-tui`) | Python Implementation (`bitchat-python`) | Rationale |
|---|---|---|---|
| **Padding Removal** | Permissive: strips `data[-1]` bytes without verifying against expected packet length | Strict: verifies `len(data) - expected_unpadded_size == data[-1]` | Rejects corrupted, truncated, or ambiguous trailing bytes |
| **Packet Immutability** | Rust move/borrow semantics | Python frozen dataclass with byte normalization | Prevents external `bytearray` modification of packet data |
| **Reserved Flags** | Preserved | Preserved | Forward compatibility with future protocol revisions |
| **Header Pre-Sender Size** | 14 bytes (arithmetic sum; code comment casually noted 13 bytes) | 14 bytes (`FIXED_HEADER_SIZE`) | Exact match with runtime wire bytes |
| **Minimum Unpadded Packet** | 22 bytes (`14 + 8`) | 22 bytes (`MINIMUM_PACKET_SIZE`) | Fixed header + SenderID |

---

## 2. Primitive Binary Encoding Checklist (`BinaryDataExt`)

- [ ] **Big-Endian u16:** 2 bytes (`>H` in Python `struct`)
- [ ] **Big-Endian u32:** 4 bytes (`>I` in Python `struct`)
- [ ] **Big-Endian u64:** 8 bytes (`>Q` in Python `struct`)
- [ ] **Short String (<= 255 bytes):** 1-byte length prefix + UTF-8 bytes
- [ ] **Long String (> 255 bytes):** 2-byte Big-Endian length prefix + UTF-8 bytes
- [ ] **Byte Data Array:** 2-byte Big-Endian length prefix + raw bytes
- [ ] **UUID (128-bit):** 16 raw big-endian bytes (hyphens stripped from string representation)
- [ ] **Timestamp / Date:** Milliseconds as 8-byte Big-Endian `u64`

---

## 3. Message Type Checklist (All 22 Types)

- [x] `0x01`: `Announce` (Nickname broadcast)
- [x] `0x02`: `KeyExchange` (96-byte combined key data)
- [x] `0x03`: `Leave` (Channel departure / `#channel` payload)
- [x] `0x04`: `Message` (Standard chat message format)
- [x] `0x05`: `FragmentStart` (First fragment with 13-byte header)
- [x] `0x06`: `FragmentContinue` (Intermediate fragment with 13-byte header)
- [x] `0x07`: `FragmentEnd` (Final fragment with 13-byte header)
- [x] `0x08`: `ChannelAnnounce` (Pipe-delimited `#channel|isProtected|creator|commitment`)
- [x] `0x09`: `ChannelRetention` (Swift v2 compatibility)
- [x] `0x0A`: `DeliveryAck` (Delivery confirmation UUID)
- [x] `0x0B`: `DeliveryStatusRequest` (Delivery status query)
- [x] `0x0C`: `ReadReceipt` (Read confirmation UUID)
- [x] `0x10`: `NoiseHandshakeInit` (Noise XX Message 1)
- [x] `0x11`: `NoiseHandshakeResp` (Noise XX Message 2)
- [x] `0x12`: `NoiseEncrypted` (ChaCha20-Poly1305 transport payload)
- [x] `0x13`: `NoiseIdentityAnnounce` (Static public key + identity hash)
- [x] `0x20`: `VersionHello` (Version negotiation proposal)
- [x] `0x21`: `VersionAck` (Version negotiation acknowledgment)
- [x] `0x22`: `ProtocolAck` (Low-level frame ACK)
- [x] `0x23`: `ProtocolNack` (Low-level frame NACK with error code)
- [x] `0x24`: `SystemValidation` (Session validation ping)
- [x] `0x25`: `HandshakeRequest` (Tie-breaking handshake request)

---

## 4. Fragmentation and Reassembly Checklist

- [ ] **Fragment Threshold:** Fragment only if packet wire size strictly > 500 bytes (`MAX_FRAGMENT_SIZE`)
- [ ] **Chunk Size:** Maximum 150 bytes payload per fragment
- [ ] **Inter-fragment Timing:** 20ms sleep between consecutive BLE packet transmissions
- [ ] **13-Byte Header:**
  - [ ] 8 bytes random `fragment_id`
  - [ ] 2 bytes Big-Endian `u16` `index`
  - [ ] 2 bytes Big-Endian `u16` `total`
  - [ ] 1 byte `u8` `original_type`
- [ ] **Reassembly:** Out-of-order index insertion into collector; reassemble when all `0..total-1` arrive
- [ ] **Relay:** Relay individual fragments independently if `TTL > 1`

---

## 5. Cryptography Checklist

- [x] **Ed25519 Signatures:** 64 bytes, signing raw payload bytes
- [x] **Ed25519 Keys:** 32-byte seed / private key, 32-byte verifying / public key
- [x] **X25519 DH:** 32-byte private key, 32-byte public key; scalar multiplication
- [x] **96-Byte KeyExchange Payload:**
  - [x] Bytes 0–31: Ephemeral X25519 public key
  - [x] Bytes 32–63: Ephemeral Ed25519 verifying key
  - [x] Bytes 64–95: Persistent Ed25519 identity verifying key
- [x] **Legacy Shared Key Derivation:** HKDF-SHA256 with salt `b"bitchat-v1"`, info empty, output 32 bytes
- [x] **Legacy Symmetric Encryption:** AES-256-GCM with 12-byte random nonce prefix: `[12B nonce][ciphertext + 16B tag]`
- [x] **Channel Key Derivation:** PBKDF2-HMAC-SHA256, 100,000 iterations, salt = channel name bytes, output 32 bytes
- [x] **Identity Fingerprint:** `SHA256(X25519_static_public_key)` full 64 lowercase hex characters (or 32 hex chars for compact UI display)
- [ ] **Local Password Encryption:** AES-256-GCM, key = `SHA256(b"bitchat-password-encryption" + identity_key_bytes)` (Phase 6 persistence)

---

## 6. Noise Protocol Checklist

- [x] **Protocol Suite:** `Noise_XX_25519_ChaChaPoly_SHA256`
- [x] **Handshake Pattern:** XX (3-message mutual authentication)
  - [x] Message 1: `-> e`
  - [x] Message 2: `<- e, ee, s, es`
  - [x] Message 3: `-> s, se`
- [x] **Split:** Derive separate send and receive `CipherState` instances after Message 3
- [x] **Transport Nonce:** 4-byte little-endian counter placed at offset 0 of ciphertext payload
- [x] **ChaCha20-Poly1305 Nonce Padding:** 4-byte LE nonce copied to bytes 4–7 of 12-byte nonce array (bytes 0–3 and 8–11 are zero)
- [x] **Replay Window:** 1024-entry sliding window; reject nonces < `(highest_received - 1024)` or duplicate nonces in window
- [ ] **Decrypted Inner Payload:** `[ 0x04 (Message) ] + [ Message Payload bytes ]` (Phase 5/6 payload handling)

---

## 7. Compression Checklist

- [ ] **Threshold:** Compress only if uncompressed payload length >= 100 bytes
- [ ] **Algorithm:** LZ4
- [ ] **Format:** Big-endian uncompressed size prepended to LZ4 compressed block
- [ ] **Rejection Rule:** Drop compression and send uncompressed if compressed length >= original length
- [ ] **Swift Interop:** Decompress payloads starting with Apple Compression magic headers `bv41` and `bv4-`

---

## 8. Test Vector Requirements for Phase 2+

To guarantee complete interoperability between Python and Rust implementations, the following deterministic test vectors must be extracted from the Rust codebase or generated via scripts:

### Test Vector 1: Packet Binary Serialization
- **Rust Input:** Fixed timestamp (`1700000000000`), sender ID (`0x0102030405060708`), recipient ID (`0x090A0B0C0D0E0F10`), type `0x04` (`Message`), TTL `7`, payload `b"Hello, BitChat!"`, unsigned, uncompressed.
- **Expected Wire Bytes:** Exact byte-for-byte hex dump including block padding to 256 bytes.
- **Verification Direction:** Rust serialized bytes → decoded by Python; Python serialized bytes → decoded by Rust.

### Test Vector 2: Inner Message Payload Serialization
- **Rust Input:** `Message` payload with `MSG_FLAG_HAS_CHANNEL | MSG_FLAG_HAS_SENDER_PEER_ID`, channel `"#general"`, text `"Hi"`, timestamp `1700000000000`.
- **Expected Wire Bytes:** Exact hex dump of inner payload.

### Test Vector 3: 96-Byte KeyExchange Serialization
- **Rust Input:** Fixed X25519 ephemeral key, Ed25519 signing key, Ed25519 identity key.
- **Expected Wire Bytes:** Exact 96-byte hex dump.

### Test Vector 4: PBKDF2 Channel Key Derivation
- **Password:** `"secret123"`
- **Channel / Salt:** `"#test"`
- **Iterations:** `100000`
- **Expected Derived Key:** 32-byte hex string.

### Test Vector 5: HKDF-SHA256 Shared Secret Derivation
- **Input Shared Secret:** 32-byte known test secret
- **Salt:** `b"bitchat-v1"`
- **Expected Derived Key:** 32-byte AES key hex string.

### Test Vector 6: Noise XX Handshake Messages
- **Static & Ephemeral Keys:** Pre-defined private scalar bytes for Initiator and Responder.
- **Expected Handshake Messages 1, 2, and 3:** Exact wire bytes for each message.
- **Expected Cipher State:** Verification of derived encryption/decryption keys and initial transport nonces.
