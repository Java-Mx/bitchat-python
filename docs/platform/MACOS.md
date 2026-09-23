# macOS Platform Support

> **LOGIC VERIFIED VIA MOCKS — HARDWARE TESTING PENDING**

## BLE Considerations
- Requires macOS 10.15+ (Catalina or newer).
- Uses CoreBluetooth framework via the `bleak` library.
- Requires Bluetooth permission in System Settings -> Privacy & Security -> Bluetooth for the terminal / Python executable.
- The `bitchat.ble` transport pipeline (scanning, connection state machine, GATT discovery, 20ms pacing, queueing, and reassembly) has been verified using simulated Bleak adapters. Physical hardware validation is pending Phase 8.
