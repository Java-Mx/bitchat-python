# Protocol Overview

BitChat is a peer-to-peer messaging protocol designed to operate over Bluetooth Low Energy (BLE).

> **UNVERIFIED**: All details regarding the protocol transport mechanism, message format, encryption, and routing must be investigated and verified against the Rust reference implementation ([bitchat-tui](https://github.com/vaibhav-mattoo/bitchat-tui)).

## Investigation Requirements
The following areas need to be fully documented based on the reference:
- BLE Transport characteristics (GATT services, characteristics)
- Message serialization format
- Encryption framework specifics
- Mesh routing rules
