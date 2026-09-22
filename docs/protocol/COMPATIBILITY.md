# Compatibility

> **UNVERIFIED**: This Python implementation must remain strictly compatible with the Rust reference implementation.

## Strategy
- **Interoperability Testing**: Explicit integration tests simulating communication with the reference client.
- **Protocol Freezes**: Avoid custom protocol extensions that break compatibility.
- Any discrepancy found during development must be resolved in favor of the Rust implementation's behavior.
