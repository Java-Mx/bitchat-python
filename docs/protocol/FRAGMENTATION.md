# Fragmentation

> **UNVERIFIED**: BLE MTU constraints dictate that larger messages must be fragmented and reassembled. The exact mechanism for this is unverified and must be detailed based on the Rust reference implementation.

## Investigation Needs
- Fragmentation header structure
- Sequence numbering
- Handling dropped fragments
- Timeout and reassembly logic
