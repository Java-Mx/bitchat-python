---
name: Interoperability Issue
description: Report an interoperability problem between bitchat-python and another BitChat implementation
title: "[INTEROP] "
labels: ["interoperability", "bug"]
assignees: []
---

## Environment & Versions
- **Python version**: <!-- e.g., 3.12.3, 3.13.0 -->
- **Rust / Reference client version**: <!-- e.g., bitchat-rust v0.2.1, bitchat iOS commit 4a2b1c -->
- **Operating systems**:
  - Python host OS: <!-- e.g., Windows 11 23H2, Ubuntu 24.04, macOS 14.5 -->
  - Peer host OS: <!-- e.g., Linux 6.8, iOS 17.5, Android 14 -->

## Communication Details
- **Direction of communication**: <!-- e.g., Python -> Rust/Reference, Rust/Reference -> Python, Bidirectional -->
- **Packet / Message type**: <!-- e.g., BLE Advertisement, Handshake Init, Encrypted Message, Channel Broadcast, Ping/Pong -->

## Description of the Interoperability Issue
<!-- A clear description of the interoperability breakdown observed between the two clients. -->

## Expected Behavior
<!-- What behavior is expected according to the BitChat protocol specification when interacting. -->

## Observed Behavior
<!-- What actually happens (e.g., handshake rejected, decrypt failure, connection reset, packet truncated). -->

## Logs / Test Results
<!-- Provide logs and test output from both sides of the communication. -->

### Python Client Logs
```
<!-- Paste bitchat-python logs here -->
```

### Rust / Reference Client Logs
```
<!-- Paste reference client logs here -->
```

### Packet Captures / Test Traces (if available)
```
<!-- Paste pcap/Wireshark summary or hex bytes here -->
```

## Additional Context
<!-- Any additional hardware or environmental details (e.g., BLE adapter models, RSSI / proximity). -->
