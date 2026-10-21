# Windows Platform Support

> **LOGIC VERIFIED VIA MOCKS — HARDWARE TESTING PENDING**

## BLE Considerations
- Requires Windows 10 (version 1809+) or Windows 11.
- Requires Bluetooth 4.0+ BLE-capable adapter with WinRT support.
- Backed by the `bleak` library using Windows WinRT Bluetooth APIs.
- The `bitchat.ble` transport pipeline (scanning, connection state machine, GATT discovery, 20ms pacing, queueing, and reassembly) has been verified using simulated Bleak adapters. Physical hardware validation is pending Phase 8.

## Platform Selection and BLE Roles
- Windows is selected centrally by `bitchat.platform.detection.detect_platform()` (`sys.platform == "win32"`); no Linux-only module or command is imported or run.
- WinRT (installed automatically by `bleak` through environment markers) provides adapter discovery, radio state events, the GATT server, and advertising. `BLEAdapterManager` reports the adapter and its roles from WinRT at runtime; a missing `winrt` backend is reported as an unavailable adapter, not as working hardware.
- Advertising can be aborted by the OS (GATT status 3) even with the radio on. BitChat then keeps BLE central scanning, records the failure, and offers **Retry Adapter**, **Continue Wi-Fi/LAN**, or **Continue Offline**. Each retry releases the failed provider, publisher, and event handlers before starting again.
- Windows behaviour is covered by tests against an in-memory fake of the WinRT API (`tests/ble/fake_winrt.py`); it has not been validated on physical Windows hardware in this change.

## Installation
- Installer/WinGet: no Python required. From source: `uv sync` (Python 3.12 or 3.13). `winrt-*` packages are pulled in by `bleak` only on Windows.
