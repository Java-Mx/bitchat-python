# Rust ↔ Python Compatibility Checklist

This document provides a concrete compatibility verification checklist and test vector specification between the Rust reference implementation (`bitchat-tui`) and the future Python implementation.

---

## 1. Binary Packet Encoding Checklist

- [ ] **Protocol Version:** Exactly byte `0x01` (`1`)
- [ ] **Message Type:** Byte matches `MessageType` enum value (`0x01`–`0x25`)
- [ ] **TTL (Time to Live):** 1 byte (`u8`), default 7, decremented on relay, dropped at 0
- [ ] **Timestamp:** 8 bytes, Big-Endian `u64` representing milliseconds since Unix epoch
- [ ] **Packet Flags:** 1 byte bitmask:
  - [ ] `FLAG_HAS_RECIPIENT` (`0x01`)
  - [ ] `FLAG_HAS_SIGNATURE` (`0x02`)
  - [ ] `FLAG_IS_COMPRESSED` (`0x04`)
- [ ] **Payload Length:** 2 bytes, Big-Endian `u16`
- [ ] **Sender ID:** 8 raw bytes (`[u8; 8]`)
- [ ] **Recipient ID:** 8 raw bytes (`[u8; 8]`), included if and only if `FLAG_HAS_RECIPIENT` (0x01) is set
- [ ] **Broadcast Recipient ID:** Exactly `[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]`
- [ ] **Payload Content:** `payload_length` bytes (LZ4 decompressed if `FLAG_IS_COMPRESSED` set)
- [ ] **Signature Placement:** Exactly 64 bytes immediately following payload, included if and only if `FLAG_HAS_SIGNATURE` (0x02) is set
- [ ] **Block Padding:** PKCS#7-style random padding to 256, 512, 1024, or 2048 bytes; final byte encodes padding count (1–255)

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

- [ ] `0x01`: `Announce` (Nickname broadcast)
- [ ] `0x02`: `KeyExchange` (96-byte combined key data)
- [ ] `0x03`: `Leave` (Channel departure / `#channel` payload)
- [ ] `0x04`: `Message` (Standard chat message format)
- [ ] `0x05`: `FragmentStart` (First fragment with 13-byte header)
- [ ] `0x06`: `FragmentContinue` (Intermediate fragment with 13-byte header)
- [ ] `0x07`: `FragmentEnd` (Final fragment with 13-byte header)
- [ ] `0x08`: `ChannelAnnounce` (Pipe-delimited `#channel|isProtected|creator|commitment`)
- [ ] `0x09`: `ChannelRetention` (Swift v2 compatibility)
- [ ] `0x0A`: `DeliveryAck` (Delivery confirmation UUID)
- [ ] `0x0B`: `DeliveryStatusRequest` (Delivery status query)
- [ ] `0x0C`: `ReadReceipt` (Read confirmation UUID)
- [ ] `0x10`: `NoiseHandshakeInit` (Noise XX Message 1)
- [ ] `0x11`: `NoiseHandshakeResp` (Noise XX Message 2)
- [ ] `0x12`: `NoiseEncrypted` (ChaCha20-Poly1305 transport payload)
- [ ] `0x13`: `NoiseIdentityAnnounce` (Static public key + identity hash)
- [ ] `0x20`: `VersionHello` (Version negotiation proposal)
- [ ] `0x21`: `VersionAck` (Version negotiation acknowledgment)
- [ ] `0x22`: `ProtocolAck` (Low-level frame ACK)
- [ ] `0x23`: `ProtocolNack` (Low-level frame NACK with error code)
- [ ] `0x24`: `SystemValidation` (Session validation ping)
- [ ] `0x25`: `HandshakeRequest` (Tie-breaking handshake request)

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

- [ ] **Ed25519 Signatures:** 64 bytes, signing raw payload bytes
- [ ] **Ed25519 Keys:** 32-byte seed / private key, 32-byte verifying / public key
- [ ] **X25519 DH:** 32-byte private key, 32-byte public key; scalar multiplication
- [ ] **96-Byte KeyExchange Payload:**
  - [ ] Bytes 0–31: Ephemeral X25519 public key
  - [ ] Bytes 32–63: Ephemeral Ed25519 verifying key
  - [ ] Bytes 64–95: Persistent Ed25519 identity verifying key
- [ ] **Legacy Shared Key Derivation:** HKDF-SHA256 with salt `b"bitchat-v1"`, info empty, output 32 bytes
- [ ] **Legacy Symmetric Encryption:** AES-256-GCM with 12-byte random nonce prefix: `[12B nonce][ciphertext + 16B tag]`
- [ ] **Channel Key Derivation:** PBKDF2-HMAC-SHA256, 100,000 iterations, salt = channel name bytes, output 32 bytes
- [ ] **Identity Fingerprint:** First 16 bytes of `SHA256(X25519_static_public_key)` formatted as 32 lowercase hex characters
- [ ] **Local Password Encryption:** AES-256-GCM, key = `SHA256(b"bitchat-password-encryption" + identity_key_bytes)`

---

## 6. Noise Protocol Checklist

- [ ] **Protocol Suite:** `Noise_XX_25519_ChaChaPoly_SHA256`
- [ ] **Handshake Pattern:** XX (3-message mutual authentication)
  - [ ] Message 1: `-> e`
  - [ ] Message 2: `<- e, ee, s, es`
  - [ ] Message 3: `-> s, se`
- [ ] **Split:** Derive separate send and receive `CipherState` instances after Message 3
- [ ] **Transport Nonce:** 4-byte little-endian counter placed at offset 0 of ciphertext payload
- [ ] **ChaCha20-Poly1305 Nonce Padding:** 4-byte LE nonce copied to bytes 4–7 of 12-byte nonce array (bytes 0–3 and 8–11 are zero)
- [ ] **Replay Window:** 1024-entry sliding window; reject nonces < `(highest_received - 1024)` or duplicate nonces in window
- [ ] **Decrypted Inner Payload:** `[ 0x04 (Message) ] + [ Message Payload bytes ]`

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
