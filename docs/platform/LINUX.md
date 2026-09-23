# Linux Platform Support

> **LOGIC VERIFIED VIA MOCKS — HARDWARE TESTING PENDING**

## BLE Considerations
- Requires BlueZ 5.43+ and systemd/dbus.
- Uses D-Bus for Bluetooth access via the `bleak` library.
- May require specific user permissions or group assignments (e.g., `bluetooth` group) or polkit rules to access BLE interfaces without root.
- The `bitchat.ble` transport pipeline (scanning, connection state machine, GATT discovery, 20ms pacing, queueing, and reassembly) has been verified using simulated Bleak adapters. Physical hardware validation is pending Phase 8.
