# Bitchat Protocol: Fragmentation and Reassembly

This document details the message fragmentation and reassembly mechanisms in the Bitchat protocol.

## 1. Fragmentation Constants

*   **`MAX_FRAGMENT_SIZE`**: 500 bytes — This is the threshold for deciding to fragment a packet. If the packet data is larger than this, it will be fragmented.
*   **Chunk Size**: 150 bytes — Actual payload chunk size used for each fragment, chosen conservatively for iOS BLE MTU (which is typically 185 bytes).
*   **Inter-fragment Delay**: 20ms — A sleep delay of 20 milliseconds is applied between sending consecutive fragments.

## 2. Fragment Packet Structure

When a packet is fragmented, its payload is wrapped in fragment structures. The fragment payload format includes a 13-byte metadata header followed by the actual data chunk.

### Serialization Format (13 bytes metadata + data)

1.  **Fragment ID**: 8 bytes (Random data, e.g., generated via `rand::thread_rng().fill`)
2.  **Index**: 2 bytes (Big-endian `u16`, 0-based fragment index)
3.  **Total**: 2 bytes (Big-endian `u16`, total number of fragments)
4.  **Original Type**: 1 byte (The original `MessageType` of the unfragmented packet)
5.  **Data**: Variable length (The chunk of the payload)

### Fragment Types

The outer `BitchatPacket` uses the following `MessageType` values to denote fragment packets:

*   **`FragmentStart`**: `0x05`
*   **`FragmentContinue`**: `0x06`
*   **`FragmentEnd`**: `0x07`

## 3. Fragmentation Logic

*   **Condition**: `should_fragment(packet_data)` returns `true` if the payload length strictly exceeds 500 bytes.
*   **Chunking**: The payload is split into chunks of 150 bytes.
*   **Type Assignment**:
    *   **First chunk**: Uses `FragmentStart` (`0x05`).
    *   **Middle chunks**: Use `FragmentContinue` (`0x06`).
    *   **Last chunk**: Uses `FragmentEnd` (`0x07`).
    *   *Note*: If there are exactly two fragments, the first is `Start` and the second is `End` (no `Continue`).

## 4. Sending Logic

When `send_packet_with_fragmentation` is invoked:

*   **If packet <= 500 bytes**: Sent directly as a single write.
    *   Uses `WriteType::WithoutResponse`. (Code has a check for `> 512` bytes to use `WriteType::WithResponse`, but it is logically unreachable since the fragmentation condition is `<= 500` bytes).
*   **If packet > 500 bytes**:
    *   Split into chunks (maximum 150 bytes of data per chunk).
    *   Sent sequentially with a 20ms delay (`time::sleep(Duration::from_millis(20))`) between each transmission.
    *   Uses `WriteType::WithoutResponse` for all fragments.

## 5. Reassembly Logic

*   A `FragmentCollector` tracks fragments grouped by their 8-byte `fragment_id`.
*   Fragments are inserted into the collection based on their `index`.
*   **Out-of-order handling**: Supported. Fragments are stored by index and will be concatenated in order once all are received.
*   **Completion**: Reassembly is complete when all indices from `0` to `total - 1` have been received.
*   Upon completion, the reassembled data is concatenated in index order. The complete payload is then parsed as a standard `BitchatPacket`.

### Missing / Unknown Behavior

*   **Timeout for incomplete fragment sets**: UNKNOWN — Requires runtime verification. Current Rust implementation does not appear to implement explicit cleanup or timeouts for stale/incomplete fragments.
*   **Duplicate fragment handling**: UNKNOWN — Since fragments are inserted by index, duplicate indices would simply overwrite existing chunks.
*   **Maximum fragments limit**: Limited by the `u16` `total` field (max 65535 fragments).

## 6. Relay of Fragments

*   Each fragment is an individual packet and is relayed independently if its `TTL > 1`.
*   The `TTL` is decremented on relay (`relay_data[2] = packet.ttl - 1`).
*   Relaying uses `WriteType::WithoutResponse`.
*   A random delay of 10-50ms is applied before relaying each packet.

## 7. Concrete Example

Consider a message with a payload of 500 bytes that is subject to fragmentation (e.g., total packet data is > 500 bytes):

*   **Original packet payload**: > 500 bytes
*   **Chunk size**: 150 bytes

Fragmentation steps:
*   **Fragment 0 (Start)**: 13 bytes header + 150 bytes data = 163 bytes payload in outer packet.
*   **Fragment 1 (Continue)**: 13 bytes header + 150 bytes data = 163 bytes payload.
*   **Fragment 2 (Continue)**: 13 bytes header + 150 bytes data = 163 bytes payload.
*   **Fragment 3 (End)**: 13 bytes header + remaining bytes payload.

Each fragment is wrapped in a standard `BitchatPacket` with the respective `FragmentStart`, `FragmentContinue`, or `FragmentEnd` message type.

## Diagrams

### Fragmentation Flow

```mermaid
flowchart TD
    A[Original Packet > 500 bytes] --> B[Generate 8-byte Random Fragment ID]
    B --> C[Chunk Payload into 150-byte blocks]
    
    C --> D[Fragment 0: Start <br/> Type: 0x05 <br/> Payload: Header + Data]
    C --> E[Fragment 1: Continue <br/> Type: 0x06 <br/> Payload: Header + Data]
    C --> F[...]
    C --> G[Fragment N-1: End <br/> Type: 0x07 <br/> Payload: Header + Data]
    
    D -->|Send without response| H[BLE MTU Transmit]
    H -.->|20ms delay| I[Send Next]
    I -->|Send without response| E
    E -.->|20ms delay| I2[Send Next]
    I2 --> G
```

### Reassembly Flow

```mermaid
flowchart TD
    A[Receive Fragment Packet] --> B[Extract Fragment ID, Index, Total]
    B --> C{ID in FragmentCollector?}
    C -->|No| D[Create new collector for ID]
    C -->|Yes| E[Add to existing collector]
    
    D --> F[Store chunk at Index]
    E --> F
    
    F --> G{All indices 0..Total-1 received?}
    G -->|No| H[Wait for more fragments]
    G -->|Yes| I[Concatenate chunks in order]
    
    I --> J[Parse as complete BitchatPacket]
```
