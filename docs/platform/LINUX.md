# Linux Platform Support

> **UNTESTED**

## BLE Considerations
- Requires BlueZ 5.43+
- Uses D-Bus for Bluetooth access via the `bleak` library.
- May require specific user permissions or group assignments (e.g., `bluetooth` group) to access BLE interfaces.
