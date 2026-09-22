# Bitchat Binary Packet Layout

This document describes the exact binary format of a `BitchatPacket`, adhering to the Phase 1 protocol extraction specifications.

---

## 1. Binary Packet Structure

The `BitchatPacket` has the following binary layout, serialized in this exact order:

| Field | Size (bytes) | Type | Offset (No Recipient) | Offset (With Recipient) | Description |
|---|---|---|---|---|---|
| **Version** | 1 | `u8` | 0 | 0 | Must be `1` (`0x01`). The protocol version string is `"v1.0.0"`. |
| **Message Type** | 1 | `u8` | 1 | 1 | Enum value (`0x01`–`0x25`). |
| **TTL** | 1 | `u8` | 2 | 2 | Time-to-Live. Default is 7. Decremented on relay. Dropped at 0. |
| **Timestamp** | 8 | `u64` | 3 | 3 | Big-endian, milliseconds since Unix epoch. |
| **Flags** | 1 | Bitmask | 11 | 11 | Bitmask for optional fields and payload compression. |
| **Payload Length**| 2 | `u16` | 12 | 12 | Big-endian byte length of the Payload field. |
| **Sender ID** | 8 | `[u8; 8]` | 14 | 14 | Fixed 8-byte array representing sender peer ID. |
| **Recipient ID** | 8 (Optional)| `[u8; 8]` | N/A | 22 | **Conditional:** Present iff `FLAG_HAS_RECIPIENT` (0x01) is set. Broadcast = `[0xFF; 8]`. |
| **Payload** | Variable | bytes | 22 | 30 | Length equals `Payload Length`. LZ4-compressed iff `FLAG_IS_COMPRESSED` (0x04) is set. |
| **Signature** | 64 (Optional)| `[u8; 64]`| 22+L | 30+L | **Conditional:** Present iff `FLAG_HAS_SIGNATURE` (0x02) is set. Ed25519 signature over Payload. |
| **Padding** | Variable | bytes | 22+L+S | 30+L+S | Random bytes to block boundary. Last byte = padding count. |

*(Note: `L` = Payload Length in bytes; `S` = 64 if signature present, else 0)*

---

### Visual ASCII Diagram

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|    Version    | Message Type  |      TTL      | Timestamp ... |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   ... Timestamp (8 bytes) ...                 |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
| Timestamp ... |     Flags     |      Payload Length (2)       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Sender ID (8 bytes)                       |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Recipient ID (8 bytes, Conditional)             |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
.                                                               .
.                       Payload (Variable)                      .
.                                                               .
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|               Signature (64 bytes, Conditional)               |
|                              ...                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
.                                                               .
.                       Padding (Variable)                      .
.                    (Last byte = padding size)                 .
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

---

## 2. Fixed Header Sizes

- **Without Recipient ID:** 22 bytes (`1 + 1 + 1 + 8 + 1 + 2 + 8`)
- **With Recipient ID:** 30 bytes (`22 + 8`)

> [!NOTE]
> **Reference Implementation Discrepancy:**
> In `packet_creation.rs` of the Rust reference implementation, comments casually state the header before Sender ID as "13 bytes" (`1 + 1 + 1 + 8 + 1 + 2`). However, the arithmetic sum of Version (1) + Type (1) + TTL (1) + Timestamp (8) + Flags (1) + PayloadLength (2) is mathematically **14 bytes**.
> The reference implementation's actual runtime code serializes all 14 bytes into the buffer before pushing the 8-byte Sender ID, confirming the wire minimum unpadded packet size is 22 bytes (14 + 8). Both reference code execution and this Python implementation use 14 bytes for the fixed header preceding Sender ID.

---

## 3. Broadcast Recipient Representation

When a packet is addressed to all peers (broadcast), the recipient is represented as:
```text
[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
```
The packet **still sets** `FLAG_HAS_RECIPIENT` (`0x01`) and explicitly carries these 8 `0xFF` bytes in the recipient position.

---

## 4. Packet Header Flags (`Flags`)

The outer packet `Flags` field (byte offset 11) is a 1-byte bitmask:

| Flag Name | Mask | Description |
|---|---|---|
| `FLAG_HAS_RECIPIENT` | `0x01` | When set, the 8-byte Recipient ID field is present at offset 22. |
| `FLAG_HAS_SIGNATURE` | `0x02` | When set, a 64-byte Ed25519 signature follows immediately after the payload. |
| `FLAG_IS_COMPRESSED` | `0x04` | When set, the payload bytes are compressed using LZ4. |

---

## 5. Inner Message Payload Flags (`MSG_FLAG_*`)

When the outer packet type is `MessageType::Message` (`0x04`), the inner payload begins with its own 1-byte flag bitmask:

| Flag Name | Mask | Description |
|---|---|---|
| `MSG_FLAG_IS_RELAY` | `0x01` | Message is being relayed by an intermediate hop |
| `MSG_FLAG_IS_PRIVATE` | `0x02` | Direct private message (1-on-1) |
| `MSG_FLAG_HAS_ORIGINAL_SENDER` | `0x04` | Contains `original_sender` string field |
| `MSG_FLAG_HAS_RECIPIENT_NICKNAME` | `0x08` | Contains `recipient_nickname` string field |
| `MSG_FLAG_HAS_SENDER_PEER_ID` | `0x10` | Contains `sender_peer_id` string field |
| `MSG_FLAG_HAS_MENTIONS` | `0x20` | Contains mentions list field |
| `MSG_FLAG_HAS_CHANNEL` | `0x40` | Contains `channel` name string field |
| `MSG_FLAG_IS_ENCRYPTED` | `0x80` | Payload content is ciphertext (channel key or private key) |

---

## 6. Signature Placement and Generation

- **Placement:** The 64-byte Ed25519 signature immediately follows the `Payload` bytes. It precedes any block padding.
- **Scope:** The signature is generated over the raw `Payload` bytes.
- **Conditional:** Only present when `FLAG_HAS_SIGNATURE` (`0x02`) is set.

---

## 7. Payload Length Calculation

- The `Payload Length` field is an unsigned 16-bit integer (`u16`) encoded in Big-Endian byte order.
- It specifies the exact byte length of the `Payload` slice on the wire.
- If `FLAG_IS_COMPRESSED` is set, `Payload Length` is the length of the **compressed** data.

---

## 8. Version Validation

- The parser reads the first byte of every packet as `version`.
- **Validation Rule:** The version byte must strictly equal `1` (`0x01`).
- If `version != 1`, the packet is immediately rejected and discarded as unsupported.

---

## 9. Block Padding and Sizing Strategy

To obscure actual message lengths against traffic analysis:
- **Valid Block Sizes:** `256`, `512`, `1024`, `2048` bytes.
- **Block Selection:** The smallest block size that satisfies `target_size >= header_size + payload_length + signature_size + 16` (reserving 16 bytes for tag overhead).
- **Padding Format:** PKCS#7-style random bytes fill the remainder of the chosen block. The final byte in the block encodes the count of padding bytes added (value range `1`–`255`).

---

## 10. Primitive Binary Encoding Conventions (`BinaryDataExt`)

All multi-byte numeric primitives use **Big-Endian** network byte order:
- **`u16`:** 2 bytes Big-Endian
- **`u32`:** 4 bytes Big-Endian
- **`u64`:** 8 bytes Big-Endian
- **Strings (length <= 255):** 1-byte length prefix + UTF-8 bytes
- **Strings (length > 255):** 2-byte Big-Endian length prefix + UTF-8 bytes
- **Binary Data / Byte Arrays:** 2-byte Big-Endian length prefix + raw bytes (max 65535 bytes)
- **Dates / Timestamps:** Stored as milliseconds since epoch (`u64` Big-Endian)
- **UUIDs:** Hexadecimal string with hyphens stripped, stored as 16 raw bytes

---

## 11. Malformed and Invalid Packet Conditions

A packet is considered malformed and rejected if any of the following occur:
1. Total received packet length is less than the minimum header size (22 bytes).
2. `version` byte does not equal `1`.
3. `payload_length` exceeds the remaining bytes in the packet buffer.
4. `FLAG_HAS_RECIPIENT` is set, but fewer than 8 bytes remain for the recipient field.
5. `FLAG_HAS_SIGNATURE` is set, but fewer than 64 bytes remain after the payload for the signature.
6. The padding length (read from the final byte of the packet) is `0` or exceeds the remaining available padding space.
7. `FLAG_IS_COMPRESSED` is set, but LZ4 decompression fails or returns malformed data.
