# Protocol Message Types

This document provides the complete specification of all 22 protocol message types and their binary payload formats, extracted from the Rust reference implementation (`bitchat-tui`).

---

## 1. MessageType Enum Summary

The outer `BitchatPacket` header field `msg_type` is encoded as a single unsigned byte (`u8`).

| Value (`u8`) | Hex | Identifier | Default TTL | Description / Category |
|---|---|---|---|---|
| 1 | `0x01` | `Announce` | 7 | Peer discovery and presence broadcast |
| 2 | `0x02` | `KeyExchange` | 7 | Ephemeral and identity key exchange |
| 3 | `0x03` | `Leave` | 3 | Channel departure or peer disconnect notification |
| 4 | `0x04` | `Message` | 7 | Regular channel, public, or private chat message |
| 5 | `0x05` | `FragmentStart` | 7 | Initial fragment of a large packet |
| 6 | `0x06` | `FragmentContinue` | 7 | Intermediate fragment of a large packet |
| 7 | `0x07` | `FragmentEnd` | 7 | Final fragment of a large packet |
| 8 | `0x08` | `ChannelAnnounce` | 5 | Channel metadata and password commitment announcement |
| 9 | `0x09` | `ChannelRetention` | 7 | Channel retention policy announcement (Swift v2 compatibility) |
| 10 | `0x0A` | `DeliveryAck` | 3 | End-to-end delivery acknowledgment |
| 11 | `0x0B` | `DeliveryStatusRequest` | 7 | Request delivery status for an earlier message |
| 12 | `0x0C` | `ReadReceipt` | 7 | End-to-end read receipt notification |
| 16 | `0x10` | `NoiseHandshakeInit` | 7 | Noise protocol handshake initiation (XX Pattern Message 1) |
| 17 | `0x11` | `NoiseHandshakeResp` | 7 | Noise protocol handshake response (XX Pattern Message 2) |
| 18 | `0x12` | `NoiseEncrypted` | 7 | Noise encrypted transport container |
| 19 | `0x13` | `NoiseIdentityAnnounce` | 7 | Noise static public key announcement |
| 32 | `0x20` | `VersionHello` | 7 | Protocol version negotiation announcement |
| 33 | `0x21` | `VersionAck` | 7 | Protocol version negotiation acknowledgment |
| 34 | `0x22` | `ProtocolAck` | 7 | Low-level protocol frame acknowledgment |
| 35 | `0x23` | `ProtocolNack` | 7 | Low-level protocol frame negative acknowledgment |
| 36 | `0x24` | `SystemValidation` | 7 | Session validation ping |
| 37 | `0x25` | `HandshakeRequest` | 7 | Explicit request to initiate Noise handshake |

---

## 2. BinaryMessageType (Internal Type Identifiers)

Used within higher-level binary protocol serialization routines:

| Value (`u8`) | Hex | Identifier |
|---|---|---|
| 1 | `0x01` | `DeliveryAck` |
| 2 | `0x02` | `ReadReceipt` |
| 7 | `0x07` | `VersionHello` |
| 8 | `0x08` | `VersionAck` |
| 9 | `0x09` | `NoiseIdentityAnnouncement` |
| 10 | `0x0A` | `NoiseMessage` |

---

## 3. Detailed Message Type Specifications

### 0x01 — Announce
- **Numeric Value:** `0x01` (`1`)
- **Purpose:** Broadcasts peer identity, presence, and nickname to nearby devices over BLE.
- **Sender Requirements:** Broadcast recipient ID `[0xFF; 8]`, TTL default 7.
- **Recipient Requirements:** Processed by all listening peers.
- **Encryption Requirements:** Plaintext payload.
- **Signature Requirements:** Optional (typically unsigned in reference).
- **TTL Behavior:** Default 7; decremented and relayed by intermediate nodes when TTL > 1.
- **Payload Structure:** UTF-8 encoded nickname string (raw bytes of string).
  ```text
  [ Nickname bytes (UTF-8, trimmed) ]
  ```
- **Receiver Behavior:** Extracts nickname via `String::from_utf8_lossy(&packet.payload).trim()`. Updates or inserts entry in peer map with `sender_id_str`. If new peer, displays `<nickname> connected` in UI.

---

### 0x02 — KeyExchange
- **Numeric Value:** `0x02` (`2`)
- **Purpose:** Exchanges cryptographic public keys between peers for legacy end-to-end encryption.
- **Sender Requirements:** Recipient is target peer ID or broadcast.
- **Recipient Requirements:** Verified by recipient.
- **Encryption Requirements:** Unencrypted public key material.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure:** Exactly 96 bytes:
  | Byte Range | Size | Field Name | Description |
  |---|---|---|---|
  | 0–31 | 32 B | `ephemeral_public_key` | Ephemeral X25519 public key |
  | 32–63 | 32 B | `ephemeral_signing_key` | Ephemeral Ed25519 verifying key |
  | 64–95 | 32 B | `identity_public_key` | Persistent Ed25519 identity key |
- **Receiver Behavior:** Registers peer public keys in `EncryptionService`. Derives shared secret via X25519 Diffie-Hellman, derives 32-byte AES key via HKDF-SHA256 (`salt = b"bitchat-v1"`). If new peer, automatically replies with local `KeyExchange` packet. Fallback logic: if identity key bytes fail Ed25519 validation (Android bug compatibility), falls back to ephemeral signing key.

---

### 0x03 — Leave
- **Numeric Value:** `0x03` (`3`)
- **Purpose:** Informs peers that the sender is leaving a channel or disconnecting.
- **Sender Requirements:** Sent when user executes `/leave` command.
- **Recipient Requirements:** Broadcast or channel-wide.
- **Encryption Requirements:** None.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Set to 3 (reduced propagation).
- **Payload Structure:** UTF-8 encoded channel name string (e.g., `"#general"`).
  ```text
  [ Channel name bytes (UTF-8) ]
  ```
- **Receiver Behavior:** Extracts channel string. If payload starts with `'#'`, logs/displays `« <nickname> left <channel>` to users currently viewing that channel.

---

### 0x04 — Message
- **Numeric Value:** `0x04` (`4`)
- **Purpose:** Transmits public, channel, or private chat messages.
- **Sender Requirements:** Valid sender ID, target recipient ID (or broadcast `[0xFF; 8]`).
- **Recipient Requirements:** Intended recipient or channel subscribers.
- **Encryption Requirements:** Encrypted if `MSG_FLAG_IS_ENCRYPTED` (0x80) is set (via channel key or direct session key).
- **Signature Requirements:** Signed with sender's ephemeral Ed25519 key if `FLAG_HAS_SIGNATURE` is set.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure (Inner Binary Format):**
  | Offset / Order | Size | Field Name | Description |
  |---|---|---|---|
  | 0 | 1 B | `flags` | Bitmask: `IS_RELAY(0x01)`, `IS_PRIVATE(0x02)`, `HAS_ORIGINAL_SENDER(0x04)`, `HAS_RECIPIENT_NICKNAME(0x08)`, `HAS_SENDER_PEER_ID(0x10)`, `HAS_MENTIONS(0x20)`, `HAS_CHANNEL(0x40)`, `IS_ENCRYPTED(0x80)` |
  | 1 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
  | 9 | 1 + N B | `message_id` | 1-byte length prefix + UTF-8 UUID string |
  | 10+N | 1 + N B | `sender_nickname` | 1-byte length prefix + UTF-8 nickname |
  | Var | 2 + N B | `content` | Big-endian `u16` length prefix + payload bytes (plaintext UTF-8 or encrypted ciphertext) |
  | Var | 1 + N B | `original_sender` | *Conditional* (`flags & 0x04`): 1-byte len + UTF-8 string |
  | Var | 1 + N B | `recipient_nickname` | *Conditional* (`flags & 0x08`): 1-byte len + UTF-8 string |
  | Var | 1 + N B | `sender_peer_id` | *Conditional* (`flags & 0x10`): 1-byte len + UTF-8 string |
  | Var | Var | `mentions` | *Conditional* (`flags & 0x20`): 1-byte count + sequence of (1-byte len + UTF-8 string) |
  | Var | 1 + N B | `channel` | *Conditional* (`flags & 0x40`): 1-byte len + UTF-8 string |
- **Receiver Behavior:** Checks sender against blocklist. Checks Bloom filter to detect duplicate message ID. If private, attempts decryption. Updates peer status. Displays in TUI. If `should_send_ack` returns true, replies with `DeliveryAck` (TTL=3). Relays packet if TTL > 1.

---

### 0x05 — FragmentStart
### 0x06 — FragmentContinue
### 0x07 — FragmentEnd
- **Numeric Values:**
  - `FragmentStart`: `0x05` (`5`)
  - `FragmentContinue`: `0x06` (`6`)
  - `FragmentEnd`: `0x07` (`7`)
- **Purpose:** Transmits fragmented chunks of packets whose wire size exceeds `MAX_FRAGMENT_SIZE` (500 bytes).
- **Sender Requirements:** Chunks sized at 150 bytes maximum. 20ms sleep delay between successive fragment sends.
- **Recipient Requirements:** Reassembled by target peer.
- **Encryption Requirements:** Carries encrypted data if the underlying packet was encrypted.
- **Signature Requirements:** Fragments are not individually signed; the reassembled packet carries the original signature.
- **TTL Behavior:** Default 7. Relayed individually if TTL > 1.
- **Payload Structure (13 Bytes Header + Data Chunk):**
  | Offset | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 8 B | `fragment_id` | 8-byte random identifier (common to all fragments of the message) |
  | 8 | 2 B | `index` | Big-endian `u16` (0-based fragment index) |
  | 10 | 2 B | `total` | Big-endian `u16` (total number of fragments) |
  | 12 | 1 B | `original_type` | `u8` MessageType of the original unfragmented packet |
  | 13 | Var | `data` | Fragment chunk payload (up to 150 bytes) |
- **Receiver Behavior:** Passed to `FragmentCollector`. Stored by `fragment_id` and `index`. Once all indices `0..total-1` arrive, reassembles payload in index order and reparses as a full `BitchatPacket`. Relays fragment if TTL > 1.

---

### 0x08 — ChannelAnnounce
- **Numeric Value:** `0x08` (`8`)
- **Purpose:** Advertises a public or password-protected channel, creator identity, and cryptographic key commitment.
- **Sender Requirements:** Broadcast recipient ID `[0xFF; 8]`, TTL 5.
- **Recipient Requirements:** Processed by all peers.
- **Encryption Requirements:** None (commitment is public).
- **Signature Requirements:** Optional.
- **TTL Behavior:** Explicitly set to 5 for wide propagation.
- **Payload Structure:** Pipe-delimited UTF-8 string:
  ```text
  "{channel}|{isProtected}|{creatorID}|{keyCommitment}"
  ```
  - `channel`: String name including `#` prefix (e.g., `"#crypto"`)
  - `isProtected`: `"1"` if password-protected, `"0"` if open
  - `creatorID`: 8-byte hex peer ID of channel creator
  - `keyCommitment`: Hex string of cryptographic commitment hash (or empty)
- **Receiver Behavior:** Parses pipe-separated string. Adds channel to discovered channels list. Displays in sidebar channel list if not `#public`.

---

### 0x09 — ChannelRetention
- **Numeric Value:** `0x09` (`9`)
- **Purpose:** Advertises message retention policies for channels (Swift v2 compatibility).
- **Sender Requirements:** Defined in protocol enum.
- **Recipient Requirements:** Not implemented in reference Rust implementation.
- **Encryption Requirements:** UNKNOWN — requires runtime verification.
- **Signature Requirements:** UNKNOWN — requires runtime verification.
- **TTL Behavior:** Default 7.
- **Payload Structure:** UNKNOWN — requires runtime/test-vector verification with Swift v2 client.
- **Receiver Behavior:** Not dispatched in Rust event loop.

---

### 0x0A — DeliveryAck
- **Numeric Value:** `0x0A` (`10`)
- **Purpose:** Confirms receipt of a private or mentioned message back to the sender.
- **Sender Requirements:** Directed unicast to message sender, TTL 3.
- **Recipient Requirements:** Matches sender of original message.
- **Encryption Requirements:** Encrypted if acknowledging a private message.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Set to 3. Relayed if TTL > 1.
- **Payload Structure:**
  | Offset / Order | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 16 B | `original_message_id` | 16-byte raw UUID |
  | 16 | 16 B | `ack_id` | 16-byte raw UUID |
  | 32 | 8 B | `recipient_id` | 8-byte peer ID of acknowledger |
  | 40 | 1 B | `hop_count` | `u8` hop counter |
  | 41 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
  | 49 | 1 + N B | `recipient_nickname` | 1-byte length prefix + UTF-8 string |
- **Receiver Behavior:** Matches `original_message_id` against `delivery_tracker`. Marks message status as delivered (updating UI tick). Relays if TTL > 1.

---

### 0x0B — DeliveryStatusRequest
- **Numeric Value:** `0x0B` (`11`)
- **Purpose:** Inquires about delivery status of a sent message.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Not implemented in reference Rust implementation.
- **Encryption Requirements:** UNKNOWN — requires runtime verification.
- **Signature Requirements:** UNKNOWN — requires runtime verification.
- **TTL Behavior:** Default 7.
- **Payload Structure:** UNKNOWN — reference contains stub handler only.
- **Receiver Behavior:** Logs `[<-- RECV] Delivery status request (not implemented)`.

---

### 0x0C — ReadReceipt
- **Numeric Value:** `0x0C` (`12`)
- **Purpose:** Notifies sender that recipient has opened/viewed their message.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Target peer.
- **Encryption Requirements:** Encrypted for private sessions.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure:**
  | Offset / Order | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 16 B | `original_message_id` | 16-byte raw UUID |
  | 16 | 16 B | `receipt_id` | 16-byte raw UUID |
  | 32 | 8 B | `reader_id` | 8-byte peer ID of reader |
  | 40 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
  | 48 | 1 + N B | `reader_nickname` | 1-byte length prefix + UTF-8 string |
- **Receiver Behavior:** In reference implementation, logs `[<-- RECV] Read receipt (not implemented)` (handler stub).

---

### 0x10 — NoiseHandshakeInit
- **Numeric Value:** `0x10` (`16`)
- **Purpose:** Initiates Noise XX handshake (Message 1: `-> e`).
- **Sender Requirements:** Initiator node; creates `NoiseSession` in `Handshaking` state. Target recipient ID set.
- **Recipient Requirements:** Responder creates `NoiseSession` in `Handshaking` state.
- **Encryption Requirements:** Ephemeral public key transmitted in clear; handshake cipher state initialized.
- **Signature Requirements:** Unsigned outer packet.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure:** Raw Noise handshake Message 1 bytes (32-byte ephemeral public key).
- **Receiver Behavior:** Calls `handle_noise_handshake_init`. If no session exists, creates Responder session. Processes handshake message. Responds with `NoiseHandshakeResp` (0x11).

---

### 0x11 — NoiseHandshakeResp
- **Numeric Value:** `0x11` (`17`)
- **Purpose:** Responds to Noise XX handshake (Message 2: `<- e, ee, s, es`).
- **Sender Requirements:** Responder node in response to `NoiseHandshakeInit`.
- **Recipient Requirements:** Initiator node.
- **Encryption Requirements:** Encrypted static key and authentication tag included.
- **Signature Requirements:** Unsigned outer packet.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure:** Raw Noise handshake Message 2 bytes.
- **Receiver Behavior:** Initiator processes message, sends Message 3 (`-> s, se`), marks session `Established`, splits cipher state into send/receive ciphers, flushes queued pending messages as `NoiseEncrypted` packets.

---

### 0x12 — NoiseEncrypted
- **Numeric Value:** `0x12` (`18`)
- **Purpose:** Encapsulates an end-to-end encrypted transport message within an established Noise session.
- **Sender Requirements:** Established Noise session with recipient. Nonce auto-incremented.
- **Recipient Requirements:** Recipient holding corresponding receive cipher state.
- **Encryption Requirements:** ChaCha20-Poly1305 encrypted.
- **Signature Requirements:** Inner payload contains original sender signature if applicable.
- **TTL Behavior:** Default 7. Relayed if TTL > 1.
- **Payload Structure:**
  | Offset | Size | Description |
  |---|---|---|
  | 0 | 4 B | Little-endian `u32` nonce |
  | 4 | Var | ChaCha20-Poly1305 ciphertext + 16-byte Poly1305 MAC tag |
- **Decrypted Inner Format:**
  ```text
  [ 1 byte MessageType (0x04) ] + [ Bitchat Message Payload (Binary Format) ]
  ```
- **Receiver Behavior:** Checks replay window (1024 messages). Decrypts using peer's `receive_cipher`. Decrypted plaintext is parsed as inner `BitchatPacket` of type `Message` and routed to standard message processing pipeline.

---

### 0x13 — NoiseIdentityAnnounce
- **Numeric Value:** `0x13` (`19`)
- **Purpose:** Broadcasts Noise static public key and identity hash for out-of-band peer discovery.
- **Sender Requirements:** Broadcast recipient `[0xFF; 8]`.
- **Recipient Requirements:** All listening peers.
- **Encryption Requirements:** Plaintext.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Default 7.
- **Payload Structure (Handler-Parsed Wire Format):**
  | Offset | Size | Field Name | Description |
  |---|---|---|---|
  | 0 | 32 B | `static_public_key` | Raw 32-byte X25519 static public key |
  | 32 | 32 B | `identity_hash` | SHA-256 hash of static public key |
  | 64 | Var | `nickname` | UTF-8 encoded nickname string |
- **Receiver Behavior:** Stores peer's static public key and fingerprint in `NoiseSessionManager`. Updates nickname in peer table.

---

### 0x20 — VersionHello
- **Numeric Value:** `0x20` (`32`)
- **Purpose:** Advertises supported protocol versions and client capabilities.
- **Sender Requirements:** Target peer or broadcast.
- **Recipient Requirements:** All peers.
- **Encryption Requirements:** None.
- **Signature Requirements:** None.
- **TTL Behavior:** Default 7.
- **Payload Structure:**
  | Field Name | Type / Format | Notes |
  |---|---|---|
  | `flags` | 1 B bitfield | Bit 0: `hasCapabilities` |
  | `supported_versions_count` | 1 B `u8` | Number of supported protocol versions |
  | `supported_versions` | N bytes (`u8` each) | List of version numbers (e.g., `[1]`) |
  | `preferred_version` | 1 B `u8` | Preferred protocol version (e.g., `1`) |
  | `client_version` | 1-byte len + UTF-8 | Client software version string (e.g., `"v1.0.0"`) |
  | `platform` | 1-byte len + UTF-8 | OS / platform string (e.g., `"linux"`, `"macos"`) |
  | `capabilities` | *Conditional* (flag bit 0) | 1-byte count + sequence of (1-byte len + UTF-8 capability string) |
- **Receiver Behavior:** Evaluates compatible version. Replies with `VersionAck` (0x21).

---

### 0x21 — VersionAck
- **Numeric Value:** `0x21` (`33`)
- **Purpose:** Acknowledges or rejects protocol version negotiation.
- **Sender Requirements:** Direct reply to `VersionHello`.
- **Recipient Requirements:** VersionHello sender.
- **Encryption Requirements:** None.
- **Signature Requirements:** None.
- **TTL Behavior:** Default 7.
- **Payload Structure:**
  | Field Name | Type / Format | Notes |
  |---|---|---|
  | `flags` | 1 B bitfield | Bit 0: `hasCapabilities`, Bit 1: `hasReason` |
  | `agreed_version` | 1 B `u8` | Negotiated protocol version |
  | `server_version` | 1-byte len + UTF-8 | Responder client version |
  | `platform` | 1-byte len + UTF-8 | Responder platform string |
  | `rejected` | 1 B `u8` | `0` = accepted, `1` = rejected |
  | `capabilities` | *Conditional* (flag bit 0) | 1-byte count + sequence of (1-byte len + UTF-8) |
  | `reason` | *Conditional* (flag bit 1) | 1-byte len + UTF-8 rejection reason |
- **Receiver Behavior:** If rejected, logs failure. If accepted, marks connection negotiated at `agreed_version`.

---

### 0x22 — ProtocolAck
- **Numeric Value:** `0x22` (`34`)
- **Purpose:** Generic protocol-level packet acknowledgment.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Sender of acknowledged packet.
- **Encryption Requirements:** None.
- **Signature Requirements:** None.
- **TTL Behavior:** Default 7.
- **Payload Structure:**
  | Offset | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 16 B | `original_packet_id` | 16-byte raw UUID |
  | 16 | 16 B | `ack_id` | 16-byte raw UUID |
  | 32 | 8 B | `sender_id` | 8-byte sender peer ID |
  | 40 | 8 B | `receiver_id` | 8-byte receiver peer ID |
  | 48 | 1 B | `packet_type` | `u8` acknowledged packet type |
  | 49 | 1 B | `hop_count` | `u8` hop counter |
  | 50 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
- **Receiver Behavior:** Confirms low-level transport receipt.

---

### 0x23 — ProtocolNack
- **Numeric Value:** `0x23` (`35`)
- **Purpose:** Generic protocol-level packet rejection / negative acknowledgment.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Sender of rejected packet.
- **Encryption Requirements:** None.
- **Signature Requirements:** None.
- **TTL Behavior:** Default 7.
- **Payload Structure:**
  | Offset | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 16 B | `original_packet_id` | 16-byte raw UUID |
  | 16 | 16 B | `ack_id` | 16-byte raw UUID |
  | 32 | 8 B | `sender_id` | 8-byte sender peer ID |
  | 40 | 8 B | `receiver_id` | 8-byte receiver peer ID |
  | 48 | 1 B | `packet_type` | `u8` rejected packet type |
  | 49 | 1 B | `hop_count` | `u8` hop counter |
  | 50 | 1 B | `error_code` | `u8` numeric error code |
  | 51 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
  | 59 | 1 + N B | `reason` | 1-byte length prefix + UTF-8 reason string |
- **Receiver Behavior:** Logs failure and notifies calling subsystem.

---

### 0x24 — SystemValidation
- **Numeric Value:** `0x24` (`36`)
- **Purpose:** Session validation ping between peers.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Target peer.
- **Encryption Requirements:** UNKNOWN — requires runtime verification.
- **Signature Requirements:** UNKNOWN — requires runtime verification.
- **TTL Behavior:** Default 7.
- **Payload Structure:** UNKNOWN — parsed by packet parser, not handled in Rust reference event loop.
- **Receiver Behavior:** Currently unhandled / dropped.

---

### 0x25 — HandshakeRequest
- **Numeric Value:** `0x25` (`37`)
- **Purpose:** Requests a peer to initiate a Noise handshake when pending messages are queued.
- **Sender Requirements:** Target peer recipient.
- **Recipient Requirements:** Target peer.
- **Encryption Requirements:** None.
- **Signature Requirements:** Optional.
- **TTL Behavior:** Default 7.
- **Payload Structure:**
  | Offset | Size | Field Name | Type / Format |
  |---|---|---|---|
  | 0 | 16 B | `request_id` | 16-byte raw UUID |
  | 16 | 8 B | `requester_id` | 8-byte peer ID of requester |
  | 24 | 8 B | `target_id` | 8-byte peer ID of target |
  | 32 | 1 B | `pending_message_count` | `u8` count of queued messages |
  | 33 | 8 B | `timestamp` | Big-endian `u64` milliseconds |
  | 41 | 1 + N B | `requester_nickname` | 1-byte length prefix + UTF-8 nickname |
- **Receiver Behavior:** Tie-breaker logic: compares `my_peer_id < request.requester_id`. If local ID is lower, local peer initiates handshake (`NoiseHandshakeInit`). If higher, yields.
