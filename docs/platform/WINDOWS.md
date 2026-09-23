# Windows Platform Support

> **LOGIC VERIFIED VIA MOCKS — HARDWARE TESTING PENDING**

## BLE Considerations
- Requires Windows 10 (version 1809+) or Windows 11.
- Requires Bluetooth 4.0+ BLE-capable adapter with WinRT support.
- Backed by the `bleak` library using Windows WinRT Bluetooth APIs.
- The `bitchat.ble` transport pipeline (scanning, connection state machine, GATT discovery, 20ms pacing, queueing, and reassembly) has been verified using simulated Bleak adapters. Physical hardware validation is pending Phase 8.
