---
name: Protocol Issue
description: Report a discrepancy or bug related to the BitChat protocol specification
title: "[PROTOCOL] "
labels: ["protocol", "bug"]
assignees: []
---

## Protocol Component
<!-- Specify which protocol layer or component is involved:
- BLE Advertising / Discovery (GATT service UUIDs, manufacturer data)
- Connection & GATT Characteristics (TX/RX characteristics, MTU negotiation)
- Framing & Packet Structure (headers, flags, payload length)
- TLV Encoding / Decoding
- Cryptographic Handshake / Noise Protocol
- Routing / Mesh Relay
-->

## Reference Implementation Behavior
<!-- Describe how the BitChat reference implementation (e.g., bitchat-rust, official spec) behaves under identical conditions. Reference specific protocol documentation sections if applicable. -->

## Observed Behavior
<!-- Describe what bitchat-python actually does that diverges from the protocol specification or reference implementation. -->

## Expected Behavior
<!-- Describe what bitchat-python should do in conformance with the BitChat protocol. -->

## Packet / Test Information
<!-- Provide packet captures (Wireshark/pcap), hex dumps, raw payload bytes, or reproducible test cases showing the issue. -->
```hex
<!-- Paste packet bytes or hex dump here -->
```

## Additional Context
<!-- Provide any other relevant details or observations. -->
